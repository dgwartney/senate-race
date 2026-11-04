"""Background fetching, independent of page rendering.

A :class:`Poller` runs one daemon thread per :class:`PollJob`. Each job fetches on its
own interval, writes successful payloads to the :class:`~src.store.SnapshotStore`, logs
every attempt, and backs off after failures. Nothing a fetch raises can stop the loop.

Pages call :meth:`Poller.ensure_running` on every render, which restarts any thread that
has died, so the poller heals itself without a process supervisor.
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional

from src.officials import configured_feeds, fetch_all
from src.providers import ProviderError, create_provider
from src.store import SnapshotStore

log = logging.getLogger(__name__)

RACES, OFFICIALS, EARLY_VOTE = "races", "officials", "early_vote"
"""Snapshot kinds written by the default jobs."""

MAX_BACKOFF_STEPS = 2
"""After repeated failures the wait grows to interval x 2, then x 4, and stays there."""


@dataclass(frozen=True)
class PollJob:
    """One kind of data to fetch on a schedule.

    Attributes:
        kind: Snapshot kind it writes, e.g. ``"races"``.
        interval: Seconds between fetches while they succeed.
        fetch: Returns a JSON-serialisable payload, or raises on failure.
    """

    kind: str
    interval: float
    fetch: Callable[[], Any]

    def delay_after(self, consecutive_failures: int) -> float:
        """Seconds to wait before the next fetch, given how many fetches in a row have failed."""
        steps = min(max(consecutive_failures - 1, 0), MAX_BACKOFF_STEPS)
        return self.interval * (2 ** steps)


class Poller:
    """Runs :class:`PollJob` s in background threads and records results in a store.

    Args:
        store: Where payloads and attempts are written.
        jobs: What to fetch.
        sleep: Waits between fetches; replaced in tests. Receives seconds and a stop event.
    """

    def __init__(self, store: SnapshotStore, jobs: List[PollJob],
                 sleep: Optional[Callable[[float, threading.Event], None]] = None):
        self.store = store
        self.jobs = jobs
        self._sleep = sleep or (lambda seconds, stop: stop.wait(seconds))
        self._stop = threading.Event()
        self._threads: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self.failures: Dict[str, int] = {job.kind: 0 for job in jobs}

    def poll_once(self, job: PollJob) -> bool:
        """Fetch one job now and record the outcome. Never raises.

        Returns:
            True if the fetch succeeded.
        """
        started = time.monotonic()
        try:
            payload = job.fetch()
        except Exception as e:  # noqa: BLE001 - any failure must be recorded, not propagated
            self.failures[job.kind] += 1
            message = f"{type(e).__name__}: {e}"
            log.warning("poll %s failed (%d in a row): %s", job.kind, self.failures[job.kind], message)
            self._record(job.kind, False, message, started)
            return False
        try:
            self.store.save_snapshot(job.kind, payload)
        except Exception as e:  # noqa: BLE001
            self.failures[job.kind] += 1
            log.exception("poll %s fetched but could not be stored", job.kind)
            self._record(job.kind, False, f"store: {type(e).__name__}: {e}", started)
            return False
        self.failures[job.kind] = 0
        self._record(job.kind, True, None, started)
        return True

    def _record(self, kind: str, ok: bool, error: Optional[str], started: float) -> None:
        try:
            self.store.record_attempt(kind, ok, error, int((time.monotonic() - started) * 1000))
        except Exception:  # noqa: BLE001 - logging the attempt is best effort
            log.exception("could not record %s attempt", kind)

    def _run(self, job: PollJob) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            self.poll_once(job)
            self._sleep(self.wait_after(job, time.monotonic() - started), self._stop)

    def wait_after(self, job: PollJob, took: float) -> float:
        """Seconds to wait after a fetch that took ``took`` seconds.

        The interval is measured from the start of the fetch, so a slow source (civicAPI takes
        ~20 s on election night) doesn't stretch a 30 s cycle to 50 s.
        """
        return max(0.0, job.delay_after(self.failures[job.kind]) - took)

    def ensure_running(self) -> None:
        """Start a thread for every job that doesn't have a live one. Cheap to call often."""
        with self._lock:
            for job in self.jobs:
                thread = self._threads.get(job.kind)
                if thread and thread.is_alive():
                    continue
                if thread:
                    log.error("poller thread for %s died; restarting", job.kind)
                thread = threading.Thread(target=self._run, args=(job,), name=f"poll-{job.kind}", daemon=True)
                self._threads[job.kind] = thread
                thread.start()

    def stop(self, timeout: float = 5) -> None:
        """Ask every thread to finish and wait for them (used by tests and shutdown)."""
        self._stop.set()
        for thread in self._threads.values():
            thread.join(timeout)


def default_jobs(env: Mapping[str, str], races_seconds: int, officials_seconds: int,
                 early_vote_seconds: int) -> List[PollJob]:
    """The dashboard's standard jobs: live races, official state feeds and early vote.

    Each job builds its own provider so no HTTP session is shared between threads.

    Raises:
        ProviderError: The configured provider cannot be created.
    """
    races_provider, early_provider = create_provider(env), create_provider(env)

    def races() -> list:
        races = races_provider.get_live_races()
        if not races:
            # An empty answer (as on 1 Nov, when civicAPI's search changed) must not replace good data.
            raise ProviderError(f"{races_provider.name} returned no Senate races")
        return [r.to_dict() for r in races]

    def officials() -> dict:
        return {state: result.to_dict() for state, result in fetch_all(configured_feeds(env)).items()}

    def early_vote() -> Optional[dict]:
        ev = early_provider.get_early_vote()
        return ev.to_dict() if ev else None

    return [PollJob(RACES, races_seconds, races),
            PollJob(OFFICIALS, officials_seconds, officials),
            PollJob(EARLY_VOTE, early_vote_seconds, early_vote)]
