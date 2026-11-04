"""Read-side of the snapshot store: what a page needs to render, plus how fresh it is."""
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from src.models import EarlyVote, Notice, RaceData, Severity
from src.officials import OfficialResult
from src.poller import EARLY_VOTE, OFFICIALS, RACES
from src.sources import StatePreference, apply_preferred_sources
from src.store import SnapshotStore

EASTERN = ZoneInfo("America/New_York")

STALE_AFTER_INTERVALS = 4
"""Data is called stale when no fetch has succeeded for this many poll intervals."""


def _clock(t: datetime) -> str:
    return t.astimezone(EASTERN).strftime("%-I:%M:%S %p ET")


@dataclass(frozen=True)
class LiveData:
    """Everything a page renders, decoded from the latest snapshots.

    Attributes:
        races: Latest race results; empty before the first successful fetch.
        races_checked_at: When a fetch last confirmed those results (UTC), if ever.
        officials: State code -> official feed result.
        early_vote: Early-vote turnout, if the source publishes it.
        notices: Freshness and failure messages for the top of the page.
    """

    races: List[RaceData] = field(default_factory=list)
    races_checked_at: Optional[datetime] = None
    officials: Dict[str, OfficialResult] = field(default_factory=dict)
    early_vote: Optional[EarlyVote] = None
    notices: List[Notice] = field(default_factory=list)


class LiveDataReader:
    """Decodes the store's latest snapshots and judges their freshness.

    Args:
        store: The snapshot store the poller writes.
        races_interval: The poller's race interval in seconds, used to judge staleness.
        source_name: Data source name for messages, e.g. ``"civicapi"``.
        preferences: State code -> preferred results source (see :mod:`src.sources`).
        now: Clock; replaced in tests.
    """

    def __init__(self, store: SnapshotStore, races_interval: int, source_name: str,
                 preferences: Optional[Dict[str, StatePreference]] = None,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.store = store
        self.preferences = preferences or {}
        self.races_interval = races_interval
        self.source_name = source_name
        self.now = now

    def read(self) -> LiveData:
        """Return the latest data. Never contacts the data source."""
        races_snap = self.store.latest(RACES)
        officials_snap = self.store.latest(OFFICIALS)
        early_snap = self.store.latest(EARLY_VOTE)
        races = [RaceData.from_dict(r) for r in races_snap.payload] if races_snap else []
        officials = ({s: OfficialResult.from_dict(r) for s, r in officials_snap.payload.items()}
                     if officials_snap else {})
        early = EarlyVote.from_dict(early_snap.payload) if early_snap and early_snap.payload else None
        races = apply_preferred_sources(races, officials, self.preferences)
        checked = races_snap.checked_at if races_snap else None
        return LiveData(races, checked, officials, early, self._notices(checked))

    def _notices(self, checked: Optional[datetime]) -> List[Notice]:
        attempt = self.store.last_attempt(RACES)
        if checked is None:
            if attempt and not attempt.ok:
                return [Notice(Severity.ERROR, f"Could not load results from {self.source_name} yet "
                                               f"({attempt.error}). Retrying automatically.")]
            return [Notice(Severity.INFO, "Waiting for the first results update…")]
        notices = []
        if attempt and not attempt.ok:
            notices.append(Notice(Severity.WARNING,
                                  f"Latest update from {self.source_name} failed at {_clock(attempt.at)}; "
                                  f"showing results from {_clock(checked)}. Retrying automatically."))
        elif self.now() - checked > timedelta(seconds=self.races_interval * STALE_AFTER_INTERVALS):
            notices.append(Notice(Severity.WARNING, f"No new update since {_clock(checked)}."))
        return notices


@dataclass(frozen=True)
class MarginPoint:
    """One race's lead at one moment: dem-side minus rep-side share of counted votes."""

    at: datetime
    margin: float
    pct_reporting: float


class MarginHistory:
    """Each race's margin over the night, built incrementally from the stored race snapshots.

    Only snapshots newer than the last one seen are read on each call, so the cost stays
    small however long the night runs. One instance is shared by every viewer; a lock
    keeps concurrent refreshes from reading the same snapshots twice.

    Args:
        store: The snapshot store the poller writes.
    """

    def __init__(self, store: SnapshotStore):
        self.store = store
        self._points: Dict[str, List[MarginPoint]] = {}
        self._last_seen: Optional[datetime] = None
        self._lock = threading.Lock()

    def refresh(self) -> None:
        """Read snapshots stored since the last call."""
        with self._lock:
            for snap in self.store.history(RACES, since=self._last_seen):
                for item in snap.payload:
                    race = RaceData.from_dict(item)
                    counted = race.total_counted_votes
                    if counted:
                        margin = (race.dem_candidate.votes - race.rep_candidate.votes) / counted
                        self._points.setdefault(race.race_id, []).append(
                            MarginPoint(snap.fetched_at, margin, race.reporting_percentage))
                self._last_seen = snap.fetched_at

    def series(self, race_id: str) -> List[MarginPoint]:
        """The race's margin at every stored change, oldest first (empty before any votes)."""
        self.refresh()
        with self._lock:
            return list(self._points.get(race_id, []))
