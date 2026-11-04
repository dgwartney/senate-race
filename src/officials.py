"""Official state results feeds, shown next to the main provider's numbers as a cross-check.

Only states whose election office publishes a machine-readable live feed are covered (checked
30 Oct 2026): Iowa (Clarity ENR JSON), Ohio (Ohio-ENR JSON API) and Texas (Civix IVIS JSON).
Kansas asks robots not to poll its page, Maine has no statewide live results, Michigan's file sits
behind a bot challenge and Alaska posts a large CSV only occasionally, so they aren't included.
"""
import base64
import json
import os
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional

import requests

from src.models import surname as display_surname
from src.providers.base import ProviderError

USER_AGENT = "senate-race-dashboard/0.1 (+https://github.com/dgwartney/senate-race)"

@dataclass(frozen=True)
class OfficialCount:
    """A state's own statewide U.S. Senate count.

    Attributes:
        state: Postal code, e.g. ``"OH"``.
        source: Publisher, e.g. ``"Ohio Secretary of State"``.
        url: The human-readable results page.
        votes: Candidate name as published -> votes.
        reporting: Progress as published, e.g. ``"0 of 8,834 precincts"``.
    """

    state: str
    source: str
    url: str
    votes: Dict[str, int]
    reporting: str


@dataclass(frozen=True)
class OfficialResult:
    """Outcome of fetching one state's feed: a count, or the reason there isn't one."""

    state: str
    count: Optional[OfficialCount] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when a count was retrieved."""
        return self.count is not None

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe representation for the snapshot store."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfficialResult":
        """Inverse of :meth:`to_dict`."""
        count = data.get("count")
        return cls(state=data["state"], count=OfficialCount(**count) if count else None, error=data.get("error"))

class OfficialFeed(ABC):
    """Base class for one state's live results feed; subclasses implement :meth:`fetch`."""

    state: str
    source: str
    url: str

    def __init__(self, session: Optional[requests.Session] = None, timeout: float = 15):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT  # some feeds block the python-requests default
        self.timeout = timeout

    @abstractmethod
    def fetch(self) -> OfficialCount:
        """Current statewide U.S. Senate count, or raise ProviderError."""

    def _get(self, url: str, params: Optional[dict] = None) -> requests.Response:
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as e:
            raise ProviderError(f"{self.source}: {e}") from e
        if response.headers.get("x-amzn-waf-action") == "challenge":
            # Iowa's CDN challenges requests from cloud servers; we don't try to get around that.
            raise ProviderError(f"{self.source}: blocked by the site's bot protection")
        return response

    def _shape_error(self, e: Exception) -> ProviderError:
        return ProviderError(f"{self.source} returned an unexpected shape: {e!r}")

class IowaFeed(OfficialFeed):
    """Iowa Secretary of State (Clarity ENR). Blocked from cloud hosts by an AWS WAF challenge."""

    state, source = "IA", "Iowa Secretary of State"

    def __init__(self, election_id: int = 127077, **kwargs):
        super().__init__(**kwargs)
        self.base = f"https://electionresults.iowa.gov/IA/{election_id}"
        self.url = f"{self.base}/"

    def fetch(self) -> OfficialCount:
        """Read the current version marker, then that version's summary."""
        version = self._get(f"{self.base}/current_ver.txt").text.strip()
        try:
            summary = self._get(f"{self.base}/{version}/json/en/summary.json").json()
            race = next(c for c in summary if c.get("C") == "United States Senator")
            votes = {name: int(v) for name, v in zip(race["CH"], race["V"], strict=True) if name != "Write-in"}
            return OfficialCount(self.state, self.source, self.url, votes, f"{race['PR']} of {race['TP']} counties")
        except (ValueError, KeyError, TypeError, StopIteration) as e:
            raise self._shape_error(e) from e

class OhioFeed(OfficialFeed):
    """Ohio Secretary of State (Ohio-ENR JSON API)."""

    state, source, url = "OH", "Ohio Secretary of State", "https://liveresults.ohiosos.gov/"

    def __init__(self, contest_id: str = "_55A742EA56A709A3E0633390EE0AE290", **kwargs):
        super().__init__(**kwargs)
        self.contest_id = contest_id

    def fetch(self) -> OfficialCount:
        """Read the Senate contest's candidate totals and precinct statistics."""
        data = self._get("https://liveresults.ohiosos.gov/Api/v1/Contest/getMyResults",
                         params={"cId": self.contest_id})
        try:
            data = data.json()
            # "totalVotes" is the whole contest's total, repeated on every candidate; "vCount" is theirs.
            votes = {c["primaryCandidate"]: int(c["vCount"])
                     for c in data["contestList"][0]["candidatesRunning"] if not c.get("isWriteIn")}
            stats = {s["name"]: s["value"] for s in data["contestStatistics"]["allStatistics"]}
            reported = stats["Election Day Precincts Reporting"].split()[0]
            total = stats["Total Number of Election Day Precincts"]
            return OfficialCount(self.state, self.source, self.url, votes, f"{reported} of {total} precincts")
        except (ValueError, KeyError, TypeError, IndexError) as e:
            raise self._shape_error(e) from e

TEXAS_API = "https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election"


class TexasFeed(OfficialFeed):
    """Texas Secretary of State (Civix IVIS; each section is base64-encoded JSON)."""

    state, source = "TX", "Texas Secretary of State"
    url = "https://goelect.txelections.civixapps.com/ivis-enr-ui/races"

    def __init__(self, election_id: int = 53815, **kwargs):
        super().__init__(**kwargs)
        self.election_id = election_id

    def fetch(self) -> OfficialCount:
        """Read the election's Home and Federal sections and pick the Senate race."""
        data = self._get(f"{TEXAS_API}/{self.election_id}")
        try:
            data = data.json()
            # Each section's value is base64-encoded JSON.
            decode = lambda key: json.loads(base64.b64decode(data[key]))
            home, federal = decode("Home"), decode("Federal")
            race = next(r for r in federal["Races"] if "SENATOR" in r["N"].upper())
            votes = {c["N"].title(): int(c["V"]) for c in race["Candidates"] if c.get("P") != "W"}  # W = write-in
            polling = home["PollingReporting"]
            return OfficialCount(self.state, self.source, self.url, votes,
                                 f"{polling['PLR']:,} of {polling['PLT']:,} polling places")
        except (ValueError, KeyError, TypeError, StopIteration, json.JSONDecodeError) as e:
            raise self._shape_error(e) from e

FEEDS = {cls.state: cls for cls in (IowaFeed, OhioFeed, TexasFeed)}

def configured_feeds(env: Optional[Mapping[str, str]] = None) -> List[OfficialFeed]:
    """Feeds named in OFFICIAL_FEEDS (comma-separated state codes; default all, empty for none)."""
    env = os.environ if env is None else env
    wanted = env.get("OFFICIAL_FEEDS", ",".join(FEEDS))
    return [FEEDS[s]() for s in (x.strip().upper() for x in wanted.split(",")) if s in FEEDS]

def fetch_all(feeds: Optional[List[OfficialFeed]] = None) -> Dict[str, OfficialResult]:
    """Fetch every feed in parallel: state code -> result. One failing feed never fails the rest."""
    feeds = feeds if feeds is not None else configured_feeds()

    def one(feed: OfficialFeed) -> OfficialResult:
        try:
            return OfficialResult(feed.state, count=feed.fetch())
        except ProviderError as e:
            return OfficialResult(feed.state, error=str(e))
    with ThreadPoolExecutor(max_workers=len(feeds) or 1) as pool:
        return {feed.state: result for feed, result in zip(feeds, pool.map(one, feeds), strict=True)}

def surname(name: str) -> str:
    """Last name for matching across sources ("KEN PAXTON" / "Ken Paxton" -> "paxton")."""
    return display_surname(name).lower()

def votes_for(count: OfficialCount, candidate_name: str) -> Optional[int]:
    """The official vote total for a candidate named as in the main provider, if found."""
    target = surname(candidate_name)
    return next((v for name, v in count.votes.items() if surname(name) == target), None)
