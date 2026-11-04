"""Provider for a feed that already uses this app's own JSON shape."""
from typing import List

import requests

from src.models import Candidate, RaceData
from src.providers.base import ElectionDataProvider, ProviderError


class JsonFeedProvider(ElectionDataProvider):
    """Reads a feed that already uses this app's own JSON shape (see README)."""

    name = "json_feed"

    def __init__(self, endpoint_url: str, api_key: str = "", timeout: float = 10):
        self.endpoint_url = endpoint_url
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.timeout = timeout

    def get_live_races(self) -> List[RaceData]:
        """Fetch the feed and map each item to a :class:`RaceData`."""
        try:
            response = requests.get(self.endpoint_url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as e:
            raise ProviderError(f"JSON feed request failed: {e}") from e
        try:
            return [self._to_race(item) for item in payload.get("races", [])]
        except (KeyError, TypeError, AttributeError) as e:
            raise ProviderError(f"JSON feed returned an unexpected shape: {e!r}") from e

    @staticmethod
    def _to_race(item: dict) -> RaceData:
        return RaceData(
            race_id=item["race_id"],
            state=item["state"],
            dem_candidate=Candidate(name=item["dem_name"], party="DEM", votes=item["dem_votes"]),
            rep_candidate=Candidate(name=item["rep_name"], party="REP", votes=item["rep_votes"]),
            expected_total_turnout=item["expected_turnout"],
            prior_uncounted_dem_share=item.get("prior_dem_share", 0.50),
            uncertainty_sd=item.get("uncertainty_sd", 0.035)
        )
