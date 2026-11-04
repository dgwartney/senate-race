"""Fixed sample data, for running the dashboard without network access."""
from typing import List

from src.models import Candidate, RaceData
from src.providers.base import ElectionDataProvider


class MockProvider(ElectionDataProvider):
    """Two hard-coded races (PA, GA) with votes partly counted."""

    name = "mock"
    attribution = "Mock data"

    def get_live_races(self) -> List[RaceData]:
        """Return the sample races."""
        return [
            RaceData(
                race_id="PA-SEN",
                state="Pennsylvania",
                dem_candidate=Candidate(name="Democrat", party="DEM", votes=1420000),
                rep_candidate=Candidate(name="Republican", party="REP", votes=1390000),
                expected_total_turnout=3200000,
                prior_uncounted_dem_share=0.53,
                uncertainty_sd=0.03
            ),
            RaceData(
                race_id="GA-SEN",
                state="Georgia",
                dem_candidate=Candidate(name="Democrat", party="DEM", votes=910000),
                rep_candidate=Candidate(name="Republican", party="REP", votes=960000),
                expected_total_turnout=2400000,
                prior_uncounted_dem_share=0.55,
                uncertainty_sd=0.04
            )
        ]
