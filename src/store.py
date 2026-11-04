"""SQLite snapshot store: the hand-off between the background poller and the pages.

The poller writes; every page view reads. Reads never touch the network, so a slow or
failing data source can delay updates but never blank the page.

Two tables:

* ``snapshots`` holds each distinct payload per kind (``"races"``, ``"officials"``,
  ``"early_vote"``). A payload identical to the latest one is not stored again, so the
  table is a history of changes and stays small.
* ``attempts`` logs every fetch, successful or not, so pages can say "last update failed".

Each call opens its own connection: SQLite connections must not be shared across
threads, and Streamlit serves each viewer on its own thread. WAL mode lets readers
proceed while the poller writes.
"""
import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, List, Optional, Union

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshots_kind_time ON snapshots (kind, fetched_at);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT,
    duration_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_kind_time ON attempts (kind, at);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Snapshot:
    """A stored payload and when it was fetched (UTC).

    ``checked_at`` is the latest successful fetch that returned this same payload, so
    an unchanged result still reads as fresh.
    """

    fetched_at: datetime
    checked_at: datetime
    payload: Any


@dataclass(frozen=True)
class Attempt:
    """One logged fetch."""

    at: datetime
    ok: bool
    error: Optional[str]
    duration_ms: int


class SnapshotStore:
    """Thread-safe, process-safe store of fetched payloads (see module docstring).

    Args:
        path: SQLite file; its directory is created if missing.
    """

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived connection, commit on success, and always close it."""
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db

    def save_snapshot(self, kind: str, payload: Any, at: Optional[datetime] = None) -> bool:
        """Store a JSON-serialisable payload unless it equals the latest one of that kind.

        Returns:
            True if a new row was written, False if the payload was unchanged.
        """
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self._connect() as db:
            row = db.execute("SELECT payload_hash FROM snapshots WHERE kind = ? ORDER BY id DESC LIMIT 1",
                             (kind,)).fetchone()
            if row and row[0] == digest:
                return False
            db.execute("INSERT INTO snapshots (kind, fetched_at, payload_hash, payload) VALUES (?, ?, ?, ?)",
                       (kind, (at or _now()).isoformat(), digest, text))
            return True

    def record_attempt(self, kind: str, ok: bool, error: Optional[str] = None, duration_ms: int = 0,
                       at: Optional[datetime] = None) -> None:
        """Log one fetch attempt."""
        with self._connect() as db:
            db.execute("INSERT INTO attempts (kind, at, ok, error, duration_ms) VALUES (?, ?, ?, ?, ?)",
                       (kind, (at or _now()).isoformat(), int(ok), error, duration_ms))

    def latest(self, kind: str) -> Optional[Snapshot]:
        """The most recent payload of a kind, or None if nothing has been fetched yet."""
        with self._connect() as db:
            row = db.execute("SELECT fetched_at, payload FROM snapshots WHERE kind = ? ORDER BY id DESC LIMIT 1",
                             (kind,)).fetchone()
            if not row:
                return None
            ok = db.execute("SELECT MAX(at) FROM attempts WHERE kind = ? AND ok = 1", (kind,)).fetchone()
        fetched = datetime.fromisoformat(row[0])
        checked = datetime.fromisoformat(ok[0]) if ok and ok[0] else fetched
        return Snapshot(fetched, max(fetched, checked), json.loads(row[1]))

    def last_attempt(self, kind: str) -> Optional[Attempt]:
        """The most recent fetch attempt of a kind, or None."""
        with self._connect() as db:
            row = db.execute("SELECT at, ok, error, duration_ms FROM attempts WHERE kind = ? ORDER BY id DESC LIMIT 1",
                             (kind,)).fetchone()
        return Attempt(datetime.fromisoformat(row[0]), bool(row[1]), row[2], row[3]) if row else None

    def history(self, kind: str, since: Optional[datetime] = None) -> List[Snapshot]:
        """Every stored payload of a kind, oldest first, optionally only those after ``since``."""
        query = "SELECT fetched_at, payload FROM snapshots WHERE kind = ?"
        args: list = [kind]
        if since is not None:
            query += " AND fetched_at > ?"
            args.append(since.isoformat())
        with self._connect() as db:
            rows = db.execute(query + " ORDER BY id", args).fetchall()
        return [Snapshot(datetime.fromisoformat(t), datetime.fromisoformat(t), json.loads(p)) for t, p in rows]
