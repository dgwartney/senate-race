"""SnapshotStore: persistence, de-duplication and attempt logging."""
import threading
from datetime import datetime, timedelta, timezone

from src.store import SnapshotStore

T0 = datetime(2026, 11, 3, 23, 0, tzinfo=timezone.utc)


def test_round_trip(tmp_path):
    store = SnapshotStore(tmp_path / "s.db")
    assert store.latest("races") is None
    assert store.save_snapshot("races", [{"a": 1}], at=T0)
    snap = store.latest("races")
    assert snap.payload == [{"a": 1}] and snap.fetched_at == T0


def test_unchanged_payload_is_not_stored_twice(tmp_path):
    store = SnapshotStore(tmp_path / "s.db")
    assert store.save_snapshot("races", {"x": 1}, at=T0)
    assert not store.save_snapshot("races", {"x": 1}, at=T0 + timedelta(minutes=1))
    assert store.save_snapshot("races", {"x": 2}, at=T0 + timedelta(minutes=2))
    assert [s.payload for s in store.history("races")] == [{"x": 1}, {"x": 2}]
    assert [s.payload for s in store.history("races", since=T0)] == [{"x": 2}]


def test_checked_at_follows_latest_successful_attempt(tmp_path):
    store = SnapshotStore(tmp_path / "s.db")
    store.save_snapshot("races", {"x": 1}, at=T0)
    store.record_attempt("races", True, at=T0 + timedelta(minutes=5))
    store.record_attempt("races", False, "timeout", at=T0 + timedelta(minutes=6))
    snap = store.latest("races")
    assert snap.fetched_at == T0 and snap.checked_at == T0 + timedelta(minutes=5)


def test_failed_attempt_keeps_latest_and_is_reported(tmp_path):
    store = SnapshotStore(tmp_path / "s.db")
    store.save_snapshot("races", {"x": 1})
    store.record_attempt("races", False, "ReadTimeout: slow", duration_ms=25000)
    assert store.latest("races").payload == {"x": 1}
    attempt = store.last_attempt("races")
    assert not attempt.ok and attempt.error == "ReadTimeout: slow" and attempt.duration_ms == 25000


def test_kinds_are_independent(tmp_path):
    store = SnapshotStore(tmp_path / "s.db")
    store.save_snapshot("races", 1)
    store.save_snapshot("officials", 2)
    assert store.latest("races").payload == 1 and store.latest("officials").payload == 2


def test_reads_while_another_thread_writes(tmp_path):
    store = SnapshotStore(tmp_path / "s.db")
    store.save_snapshot("races", 0)
    errors = []

    def write():
        for i in range(1, 200):
            store.save_snapshot("races", i)

    def read():
        try:
            for _ in range(200):
                assert store.latest("races") is not None
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=write)] + [threading.Thread(target=read) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and store.latest("races").payload == 199
