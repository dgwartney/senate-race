"""Poller: recording outcomes, backoff, and self-healing threads."""
import threading

import pytest

from src.poller import RACES, Poller, PollJob, default_jobs
from src.store import SnapshotStore


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path / "s.db")


def test_success_is_stored(store):
    job = PollJob("races", 30, lambda: [1, 2])
    assert Poller(store, [job]).poll_once(job)
    assert store.latest("races").payload == [1, 2] and store.last_attempt("races").ok


@pytest.mark.parametrize("error", [RuntimeError("boom"), KeyError("x"), ZeroDivisionError()])
def test_any_exception_is_recorded_not_raised(store, error):
    def fail():
        raise error
    job = PollJob("races", 30, fail)
    poller = Poller(store, [job])
    assert not poller.poll_once(job)
    attempt = store.last_attempt("races")
    assert not attempt.ok and type(error).__name__ in attempt.error
    assert store.latest("races") is None and poller.failures["races"] == 1


def test_unserialisable_payload_is_a_recorded_failure(store):
    job = PollJob("races", 30, lambda: object())
    assert not Poller(store, [job]).poll_once(job)
    assert "store:" in store.last_attempt("races").error


def test_backoff_doubles_then_caps_and_resets(store):
    job = PollJob("races", 30, lambda: 1)
    assert [job.delay_after(n) for n in range(6)] == [30, 30, 60, 120, 120, 120]
    poller = Poller(store, [job])
    poller.failures["races"] = 3
    poller.poll_once(job)
    assert poller.failures["races"] == 0


def test_thread_loop_survives_failures_and_restarts_when_dead(store):
    calls = []
    ran_twice = threading.Event()

    def flaky():
        calls.append(1)
        if len(calls) >= 3:
            ran_twice.set()
        if len(calls) % 2:
            raise RuntimeError("odd call fails")
        return len(calls)

    poller = Poller(store, [PollJob("races", 30, flaky)], sleep=lambda s, stop: stop.wait(0.01))
    poller.ensure_running()
    assert ran_twice.wait(5)
    poller.stop()
    assert store.latest("races") is not None
    # A stopped (dead) thread is replaced by ensure_running.
    poller._stop.clear()
    first = poller._threads["races"]
    poller.ensure_running()
    assert poller._threads["races"] is not first and poller._threads["races"].is_alive()
    poller.stop()


def test_empty_race_list_is_a_failure_so_good_data_survives(store, monkeypatch):
    jobs = {j.kind: j for j in default_jobs({"ELECTION_PROVIDER": "mock", "OFFICIAL_FEEDS": ""}, 30, 60, 3600)}
    poller = Poller(store, list(jobs.values()))
    assert poller.poll_once(jobs[RACES])
    monkeypatch.setattr("src.providers.mock.MockProvider.get_live_races", lambda self: [])
    assert not poller.poll_once(jobs[RACES])
    assert len(store.latest(RACES).payload) == 2 and "no Senate races" in store.last_attempt(RACES).error


def test_default_jobs_payloads_are_storable(store):
    jobs = default_jobs({"ELECTION_PROVIDER": "mock", "OFFICIAL_FEEDS": ""}, 30, 60, 3600)
    poller = Poller(store, jobs)
    assert all(poller.poll_once(job) for job in jobs)
    assert store.latest("officials").payload == {} and store.latest("early_vote").payload is None


def test_interval_counts_from_the_start_of_a_fetch(store):
    job = PollJob("races", 30, lambda: 1)
    poller = Poller(store, [job])
    assert poller.wait_after(job, 22) == 8 and poller.wait_after(job, 45) == 0
    poller.failures["races"] = 2
    assert poller.wait_after(job, 22) == 38  # backoff still applies
