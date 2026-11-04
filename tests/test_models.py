"""Derived properties and serialisation of the domain types."""
from src.models import Candidate, EarlyVote, ForecastResult, RaceData


def result(dem_votes, rep_votes, race_id="TX-SEN"):
    return ForecastResult(race_id, "Texas", "Jane Doe", "Democratic", dem_votes, "John Roe", "Republican",
                          rep_votes, 10.0, 0.6, 0.4, None)


def test_leader_is_by_votes_and_none_when_level():
    assert result(0, 0).leader is None and result(5, 5).leader is None
    assert result(6, 4).leader.label == "DEM" and result(4, 6).leader.name == "John Roe"


def test_margin_and_counts():
    r = result(600, 400)
    assert r.margin == 0.2 and r.total_votes == 1000 and r.has_votes
    assert result(0, 0).margin == 0.0 and not result(0, 0).has_votes


def test_state_code_from_race_id():
    assert result(0, 0, "oh-sen").state_code == "OH"


def test_race_data_round_trips():
    race = RaceData("TX-SEN", "Texas", Candidate("A", "Democratic", 1), Candidate("B", "Republican", 2), 10, 0.5, 0.03)
    assert RaceData.from_dict(race.to_dict()) == race


def test_early_vote_round_trips():
    ev = EarlyVote("2026-11-02", {"In person": {"TX": {"Democratic": 5}}})
    assert EarlyVote.from_dict(ev.to_dict()) == ev
