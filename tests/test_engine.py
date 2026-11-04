"""Edge cases of the win-probability model."""
import pytest

from src.engine import PROJECTION_THRESHOLD, ProjectionEngine
from src.models import Candidate, RaceData


def race(dem, rep, turnout, prior=0.5, sd=0.035):
    return RaceData("TX-SEN", "Texas", Candidate("Dee", "Democratic", dem), Candidate("Ray", "Republican", rep),
                    turnout, prior, sd)


@pytest.mark.parametrize("dem, rep, expected", [(10, 5, 1.0), (5, 10, 0.0), (7, 7, 0.5)])
def test_nothing_left_to_count_decides_by_votes(dem, rep, expected):
    assert ProjectionEngine.dem_win_probability(race(dem, rep, dem + rep)) == expected


def test_majority_already_reached_is_certain():
    assert ProjectionEngine.dem_win_probability(race(600, 100, 1000)) == 1.0


def test_majority_out_of_reach_is_impossible():
    assert ProjectionEngine.dem_win_probability(race(100, 600, 1000)) == 0.0


def test_no_votes_counted_gives_even_odds_with_even_prior():
    assert ProjectionEngine.dem_win_probability(race(0, 0, 1_000_000)) == pytest.approx(0.5, abs=1e-3)


def test_stronger_prior_favours_dem():
    assert ProjectionEngine.dem_win_probability(race(0, 0, 1_000_000, prior=0.53)) > 0.75


def test_projection_only_above_threshold():
    sure = ProjectionEngine.calculate_single_race(race(600, 100, 1000))
    close = ProjectionEngine.calculate_single_race(race(450, 450, 1000))
    assert sure.projected_winner == "Dee (DEM)" and sure.dem_win_prob >= PROJECTION_THRESHOLD
    assert close.projected_winner is None
    assert sure.dem_win_prob + sure.rep_win_prob == pytest.approx(1.0)
