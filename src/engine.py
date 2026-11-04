"""Live win probabilities from partial counts.

Model: the votes still to be counted split between the two sides with a dem-side share
drawn from Normal(prior_uncounted_dem_share, uncertainty_sd). The dem side wins if it
reaches a majority of the expected two-side total. Third-party votes are outside the
model: both the counts and the expected turnout cover only the two sides.

This is a projection from a fixed prior, not a Bayesian update: the expected share of the
uncounted vote does not learn from the votes already counted.
"""
from typing import List

import numpy as np
from scipy.stats import norm

from src.models import ForecastResult, RaceData, party_label

PROJECTION_THRESHOLD = 0.995
"""Win probability at or above which a side is shown as the projected winner."""


class ProjectionEngine:
    """Turns :class:`RaceData` into :class:`ForecastResult` (stateless; safe to share)."""

    @staticmethod
    def dem_win_probability(race: RaceData) -> float:
        """Probability that the dem side finishes ahead, given the votes counted so far.

        With nothing left to count, the leader wins outright and an exact tie is 0.5.
        """
        dem, rep, remaining = race.dem_candidate.votes, race.rep_candidate.votes, race.remaining_votes
        if remaining == 0:
            return 0.5 if dem == rep else float(dem > rep)
        needed = (race.expected_total_turnout / 2.0 + 1) - dem
        required_share = needed / remaining
        if required_share <= 0:
            return 1.0
        if required_share >= 1:
            return 0.0
        tail = 1.0 - norm.cdf(required_share, loc=race.prior_uncounted_dem_share, scale=race.uncertainty_sd)
        return float(np.clip(tail, 0.0, 1.0))

    @classmethod
    def calculate_single_race(cls, race: RaceData) -> ForecastResult:
        """Forecast one race."""
        dem_prob = cls.dem_win_probability(race)
        rep_prob = 1.0 - dem_prob
        dem_c, rep_c = race.dem_candidate, race.rep_candidate
        winner = None
        if dem_prob >= PROJECTION_THRESHOLD:
            winner = f"{dem_c.name} ({party_label(dem_c.party)})"
        elif rep_prob >= PROJECTION_THRESHOLD:
            winner = f"{rep_c.name} ({party_label(rep_c.party)})"
        return ForecastResult(
            race_id=race.race_id, state=race.state,
            dem_name=dem_c.name, dem_party=dem_c.party, dem_votes=dem_c.votes,
            rep_name=rep_c.name, rep_party=rep_c.party, rep_votes=rep_c.votes,
            pct_reporting=race.reporting_percentage, dem_win_prob=dem_prob, rep_win_prob=rep_prob,
            projected_winner=winner, source=race.source,
        )

    def process_all_races(self, races: List[RaceData]) -> List[ForecastResult]:
        """Forecast every race, in the order given."""
        return [self.calculate_single_race(r) for r in races]
