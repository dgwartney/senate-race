import pytest

from src.models import Candidate, RaceData
from src.officials import OfficialCount, OfficialResult
from src.sources import SourceConfigError, StatePreference, apply_preferred_sources, load_source_preferences


def race(race_id="OH-SEN", dem=200, rep=100, expected=5_000_000):
    return RaceData(race_id, "Ohio", Candidate("Sherrod Brown", "Democratic", dem),
                    Candidate("Jon Husted", "Republican", rep), expected, 0.5, 0.035)


def official(votes, state="OH"):
    return {state: OfficialResult(state, count=OfficialCount(state, "Ohio Secretary of State", "u", votes, "9 of 99"))}


PREFS = {"OH": StatePreference("official", 4_100_000)}


def test_official_totals_replace_main_provider_for_preferred_state():
    out, = apply_preferred_sources([race()], official({"Sherrod Brown": 948_901, "Jon Husted": 636_442}), PREFS)
    assert (out.dem_candidate.votes, out.rep_candidate.votes) == (948_901, 636_442)
    assert out.source == "Ohio Secretary of State"
    assert out.expected_total_turnout == 5_000_000  # main provider's estimate is the larger


def test_other_states_keep_main_provider_when_one_response_covers_many():
    tx = race("TX-SEN")
    out = apply_preferred_sources([race(), tx], official({"Sherrod Brown": 9, "Jon Husted": 8}), PREFS)
    assert out[1] is tx and out[0].source


@pytest.mark.parametrize("officials", [
    {},                                                                   # feed not running
    {"OH": OfficialResult("OH", error="timeout")},                        # feed failed
    official({"Sherrod Brown": 0, "Jon Husted": 0}),                      # nothing counted yet
    official({"Someone Else": 5, "Jon Husted": 4}),                       # names don't match
])
def test_falls_back_to_main_provider(officials):
    r = race()
    assert apply_preferred_sources([r], officials, PREFS) == [r]


def test_unlisted_or_non_official_preference_is_ignored():
    r = race()
    assert apply_preferred_sources([r], official({"Sherrod Brown": 9, "Jon Husted": 8}), {}) == [r]
    prefs = {"OH": StatePreference("civicapi")}
    assert apply_preferred_sources([r], official({"Sherrod Brown": 9, "Jon Husted": 8}), prefs) == [r]


def test_expected_turnout_never_reaches_the_count():
    counts = official({"Sherrod Brown": 3_000_000, "Jon Husted": 2_000_000})
    out, = apply_preferred_sources([race(dem=0, rep=0)], counts, PREFS)
    assert out.expected_total_turnout == 5_150_000  # counted x 1.03, above the 4.1M configured
    assert out.reporting_percentage < 100


def test_load_preferences(tmp_path):
    path = tmp_path / "s.toml"
    path.write_text('[oh]\nsource = "official"\nexpected_turnout = 4_100_000\n')
    assert load_source_preferences(path) == {"OH": StatePreference("official", 4_100_000)}
    assert load_source_preferences(tmp_path / "missing.toml") == {}
    path.write_text("[oh]\nexpected_turnout = 1\n")
    with pytest.raises(SourceConfigError):
        load_source_preferences(path)


def test_shipped_preferences_parse():
    from src.config import Settings
    prefs = load_source_preferences(Settings().sources_file)
    assert {"OH", "TX", "IA"} <= prefs.keys()
