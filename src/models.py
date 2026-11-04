"""Domain data types shared by providers, the forecasting engine, the snapshot store and the UI.

All types are plain dataclasses. Those stored in the snapshot database have ``to_dict`` /
``from_dict`` so they round-trip through JSON without pickling.
"""
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional

from src.geo import race_state_code

PARTY_ABBREVIATIONS = {"Democratic": "DEM", "Republican": "REP", "Independent": "IND",
                       "Libertarian": "LIB", "Green": "GRN", "Constitution": "CON"}


NAME_SUFFIXES = ("jr", "sr", "ii", "iii", "iv")


def party_label(party: str) -> str:
    """Short party label for display; unknown parties keep their full name."""
    return PARTY_ABBREVIATIONS.get(party, party or "?")


def surname(name: str) -> str:
    """A candidate's last name as written, ignoring suffixes and quoted nicknames.

    ``'Michael "Dr. Mike" Katz'`` -> ``"Katz"``; ``"Daniel J. Jr. Sullivan"`` -> ``"Sullivan"``.
    Returns ``""`` for an empty name.
    """
    parts = [p for p in name.replace('"', " ").replace(",", " ").split()
             if p.lower().rstrip(".") not in NAME_SUFFIXES]
    return parts[-1] if parts else ""


@dataclass(frozen=True)
class Candidate:
    """One candidate's name, party (as the source spells it) and votes counted so far."""

    name: str
    party: str
    votes: int


@dataclass
class RaceData:
    """A race as a provider reports it: the two leading sides plus the engine's inputs.

    The "dem" side is the leading Democrat, or the strongest non-Republican challenger
    (e.g. an independent) where no Democrat runs; the "rep" side is the leading Republican.

    Attributes:
        race_id: Stable ID such as ``"TX-SEN"``.
        state: Display name, e.g. ``"Ohio (special)"``.
        expected_total_turnout: Estimated two-side total votes when counting finishes.
        prior_uncounted_dem_share: Expected dem-side share of votes not yet counted.
        uncertainty_sd: Standard deviation of that share.
        source: Who supplied the vote totals when not the main provider, e.g. ``"Ohio Secretary of State"``.
    """

    race_id: str
    state: str
    dem_candidate: Candidate
    rep_candidate: Candidate
    expected_total_turnout: int
    prior_uncounted_dem_share: float
    uncertainty_sd: float
    source: str = ""

    @property
    def total_counted_votes(self) -> int:
        """Votes counted so far for the two sides."""
        return self.dem_candidate.votes + self.rep_candidate.votes

    @property
    def remaining_votes(self) -> int:
        """Two-side votes still expected; never negative."""
        return max(0, self.expected_total_turnout - self.total_counted_votes)

    @property
    def reporting_percentage(self) -> float:
        """Counted votes as a percentage of expected turnout, capped at 100."""
        if self.expected_total_turnout == 0:
            return 0.0
        return min(100.0, (self.total_counted_votes / self.expected_total_turnout) * 100.0)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe representation for the snapshot store."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RaceData":
        """Inverse of :meth:`to_dict`."""
        return cls(**{**data, "dem_candidate": Candidate(**data["dem_candidate"]),
                      "rep_candidate": Candidate(**data["rep_candidate"])})


@dataclass(frozen=True)
class Side:
    """One side of a forecast race, as shown to viewers."""

    name: str
    party: str
    votes: int
    win_prob: float

    @property
    def label(self) -> str:
        """Short party label such as ``"DEM"``."""
        return party_label(self.party)


@dataclass(frozen=True)
class ForecastResult:
    """The engine's output for one race: counts so far plus each side's win probability."""

    race_id: str
    state: str
    dem_name: str
    dem_party: str
    dem_votes: int
    rep_name: str
    rep_party: str
    rep_votes: int
    pct_reporting: float
    dem_win_prob: float
    rep_win_prob: float
    projected_winner: Optional[str]
    source: str = ""
    """Who supplied the vote totals when not the main provider (see :attr:`RaceData.source`)."""

    @property
    def state_code(self) -> str:
        """Postal code of the race's state, e.g. ``"TX"``."""
        return race_state_code(self.race_id)

    @property
    def total_votes(self) -> int:
        """Votes counted for the two sides."""
        return self.dem_votes + self.rep_votes

    @property
    def has_votes(self) -> bool:
        """True once any vote has been counted."""
        return self.total_votes > 0

    @property
    def dem(self) -> Side:
        """The Democratic (or non-Republican challenger) side."""
        return Side(self.dem_name, self.dem_party, self.dem_votes, self.dem_win_prob)

    @property
    def rep(self) -> Side:
        """The Republican side."""
        return Side(self.rep_name, self.rep_party, self.rep_votes, self.rep_win_prob)

    @property
    def leader(self) -> Optional[Side]:
        """The side ahead in votes counted, or None before any votes or when level.

        This is the single definition of "leading" used across the dashboard.
        """
        if self.dem_votes == self.rep_votes:
            return None
        return self.dem if self.dem_votes > self.rep_votes else self.rep

    @property
    def margin(self) -> float:
        """Dem-side share minus rep-side share of counted votes (-1..1); 0 before votes."""
        return (self.dem_votes - self.rep_votes) / self.total_votes if self.has_votes else 0.0


@dataclass(frozen=True)
class EarlyVote:
    """Ballots already cast, by voters' party registration (not votes for candidates).

    Attributes:
        snapshot_date: Date the source last updated, as the source writes it.
        by_category: Category ("Mail returned", "In person") -> state code -> party -> ballots.
    """

    snapshot_date: str
    by_category: Dict[str, Dict[str, Dict[str, int]]]

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe representation for the snapshot store."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EarlyVote":
        """Inverse of :meth:`to_dict`."""
        return cls(**data)


class Severity(Enum):
    """How prominently a :class:`Notice` is shown; values name the Streamlit call."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Notice:
    """A status message for the top of the page."""

    severity: Severity
    text: str
