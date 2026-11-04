"""civicAPI (https://civicapi.org) provider: free live results for every U.S. race."""
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import requests

from src.geo import US_STATES
from src.models import Candidate, EarlyVote, RaceData
from src.providers.base import ElectionDataProvider, ProviderError

BASE_URL = "https://civicapi.org/api/v2"


EARLY_VOTE_CATEGORIES = {"returned": "Mail returned", "inperson": "In person"}

def _clean(name: str) -> str:
    # civicAPI names sometimes contain doubled spaces ("Pete  Ricketts").
    return " ".join(name.split())

class CivicApiProvider(ElectionDataProvider):
    """Live results from civicAPI (https://civicapi.org). Free, no API key.

    Attribution is required for non-personal projects, which the app shows via
    `attribution`. One search request returns every matching race with vote counts.
    In test mode each race is fetched separately with `?testdata`, which returns
    random, unrealistic counts for exercising the pipeline before results exist.
    """

    name = "civicapi"
    attribution = "Results: civicAPI (civicapi.org)"

    def __init__(self, election_date: str = "2026-11-03", race_type: str = "US Senate",
                 test_data: bool = False, fallback_turnout: int = 1_000_000,
                 matchups: Optional[Dict[str, Tuple[str, str]]] = None,
                 prior_dem_share: float = 0.50, uncertainty_sd: float = 0.035,
                 session: Optional[requests.Session] = None, timeout: float = 25):
        self.election_date = election_date
        self.race_type = race_type
        self.test_data = test_data
        self.fallback_turnout = fallback_turnout
        # race_id -> (challenger side, Republican side) candidate names, for ambiguous listings.
        self.matchups = {k.upper(): tuple(_clean(n) for n in v) for k, v in (matchups or {}).items()}
        self.prior_dem_share = prior_dem_share
        self.uncertainty_sd = uncertainty_sd
        # requests.Session isn't guaranteed thread-safe, and test mode fetches races from a
        # thread pool, so each thread gets its own session unless the caller injected one.
        self.session = session
        self._local = threading.local()
        self.timeout = timeout

    def get_live_races(self) -> List[RaceData]:
        """Every U.S. Senate general-election race on the election date, with current counts."""
        races = self._search()
        if self.test_data:
            with ThreadPoolExecutor(max_workers=8) as pool:
                details = list(pool.map(self._race_with_test_data, [r["id"] for r in races]))
            races = [{**detail, "id": r["id"]} for r, detail in zip(races, details, strict=True)]
        try:
            return [self._to_race(r) for r in races if len(r.get("candidates") or []) >= 2]
        except (KeyError, TypeError, ValueError) as e:
            raise ProviderError(f"civicAPI returned an unexpected shape: {e!r}") from e

    def _search(self) -> List[dict]:
        # Filter by race type, not `query`: since ~1 Nov 2026 a "US Senate" text query matches
        # only the Virgin Islands legislature, while `type` returns every U.S. Senate race.
        params = {"startDate": self.election_date, "endDate": self.election_date,
                  "country": "US", "type": self.race_type, "limit": 200}
        payload = self._get(f"{BASE_URL}/race/search", params)
        try:
            return [r for r in payload["races"]
                    if r.get("election_type") == "General" and r.get("district") is None
                    and "US Senate" in r.get("election_name", "")]
        except (KeyError, TypeError) as e:
            raise ProviderError(f"civicAPI search returned an unexpected shape: {e!r}") from e

    def _race_with_test_data(self, race_id: int) -> dict:
        return self._get(f"{BASE_URL}/race/{race_id}?testdata")

    def get_early_vote(self) -> Optional[EarlyVote]:
        """Early ballots returned by mail and cast in person, by state and party registration."""
        by_category, snapshot = {}, ""
        for key, label in EARLY_VOTE_CATEGORIES.items():
            payload = self._get(f"{BASE_URL}/early-vote/US/{key}")
            try:
                snapshot = snapshot or payload.get("snapshot_date", "")
                by_category[label] = {state: {party: int(v.get("votes") or 0) for party, v in parties.items()}
                                      for state, parties in payload["regions"].items()}
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                raise ProviderError(f"civicAPI early-vote data has an unexpected shape: {e!r}") from e
        return EarlyVote(snapshot_date=snapshot, by_category=by_category)

    def _session(self) -> requests.Session:
        """The injected session, or this thread's own one."""
        if self.session is not None:
            return self.session
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _get(self, url: str, params: Optional[dict] = None) -> dict:
        """GET a civicAPI URL and decode its JSON, raising ProviderError on any failure.

        A dropped connection (civicAPI closes idle keep-alive connections) is retried once at
        once; timeouts are not, since a retry would double an already long wait.
        """
        for attempt in (1, 2):
            try:
                response = self._session().get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except requests.ConnectionError as e:
                if attempt == 2 or isinstance(e, requests.Timeout):
                    raise ProviderError(f"civicAPI request failed: {e}") from e
            except (requests.RequestException, ValueError) as e:
                raise ProviderError(f"civicAPI request failed: {e}") from e
        raise AssertionError("unreachable")  # pragma: no cover

    def _to_race(self, race: dict) -> RaceData:
        race_id = f"{race['province']}-SEN"
        dem, rep = self._pinned_sides(race["candidates"], race_id) or self._pick_sides(race["candidates"])
        counted = (dem.get("votes") or 0) + (rep.get("votes") or 0)
        return RaceData(
            race_id=race_id,
            state=self._state_name(race),
            dem_candidate=Candidate(name=_clean(dem["name"]), party=dem.get("party", ""), votes=dem.get("votes") or 0),
            rep_candidate=Candidate(name=_clean(rep["name"]), party=rep.get("party", ""), votes=rep.get("votes") or 0),
            expected_total_turnout=self._expected_turnout(counted, race.get("percent_reporting") or 0),
            prior_uncounted_dem_share=self.prior_dem_share,
            uncertainty_sd=self.uncertainty_sd
        )

    @staticmethod
    def _state_name(race: dict) -> str:
        state = US_STATES.get(race["province"], race["province"])
        return f"{state} (special)" if "special" in race["election_name"].lower() else state

    def _pinned_sides(self, candidates: List[dict], race_id: str) -> Optional[Tuple[dict, dict]]:
        names = self.matchups.get(race_id)
        if not names:
            return None
        by_name = {_clean(c["name"]): c for c in candidates}
        if not all(n in by_name for n in names):
            return None  # a pinned name isn't in the data any more; fall back to the automatic pick
        return by_name[names[0]], by_name[names[1]]

    @staticmethod
    def _pick_sides(candidates: List[dict]) -> Tuple[dict, dict]:
        # Each side is its party's leading candidate. A side with no candidate from that
        # party (e.g. an independent challenger) takes the leading candidate not yet chosen.
        ranked = sorted(candidates, key=lambda c: c.get("votes") or 0, reverse=True)
        leader = lambda party: next((c for c in ranked if c.get("party") == party), None)
        dem, rep = leader("Democratic"), leader("Republican")
        spare = iter(c for c in ranked if c is not dem and c is not rep)
        return dem or next(spare), rep or next(spare)

    def _expected_turnout(self, counted: int, percent_reporting: float) -> int:
        """Estimate the race's final two-side vote total.

        civicAPI gives no expected vote, so counted votes are scaled by percent reporting.
        Until reporting is above zero the fallback is used instead: New Hampshire's
        midnight-voting towns post a handful of votes at 0% reporting, and scaling 7 votes
        to a 700-vote state would turn them into confident-looking odds.
        """
        if counted == 0 or percent_reporting <= 0:
            return self.fallback_turnout
        return max(counted, round(counted * 100 / percent_reporting))
