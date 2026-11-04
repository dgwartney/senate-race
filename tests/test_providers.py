import pytest
import requests

from src.engine import ProjectionEngine
from src.providers import PROVIDERS, ElectionDataProvider, ProviderError, create_provider
from src.providers.civicapi import CivicApiProvider
from src.providers.json_feed import JsonFeedProvider
from src.providers.mock import MockProvider


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self.payload

class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls, self.params = routes, [], []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        self.params.append(params)
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                if isinstance(response, Exception):
                    raise response
                return response
        return FakeResponse({"error": "not found"}, status=404)

def candidate(name, party, votes):
    return {"name": name, "party": party, "votes": votes}

def civic_race(race_id, name, province, candidates, percent_reporting=0, **extra):
    return {"id": race_id, "election_name": name, "election_type": "General", "district": None,
            "province": province, "percent_reporting": percent_reporting, "candidates": candidates, **extra}

SEARCH = "https://civicapi.org/api/v2/race/search"

# --- factory -----------------------------------------------------------------

@pytest.mark.parametrize("env, expected", [
    ({}, MockProvider),
    ({"API_ENDPOINT": "https://feed.example/races"}, JsonFeedProvider),
    ({"ELECTION_PROVIDER": "civicapi"}, CivicApiProvider),
    ({"ELECTION_PROVIDER": " Mock ", "API_ENDPOINT": "https://feed.example/races"}, MockProvider),
])
def test_factory_selects_provider(env, expected):
    assert isinstance(create_provider(env), expected)

def test_factory_rejects_unknown_provider():
    with pytest.raises(ProviderError, match="Unknown ELECTION_PROVIDER"):
        create_provider({"ELECTION_PROVIDER": "nope"})

def test_factory_requires_endpoint_for_json_feed():
    with pytest.raises(ProviderError, match="API_ENDPOINT"):
        create_provider({"ELECTION_PROVIDER": "json_feed"})

def test_factory_passes_civicapi_settings():
    p = create_provider({"ELECTION_PROVIDER": "civicapi", "CIVICAPI_TEST_DATA": "true",
                         "CIVICAPI_ELECTION_DATE": "2028-11-07", "CIVICAPI_FALLBACK_TURNOUT": "5"})
    assert (p.test_data, p.election_date, p.fallback_turnout) == (True, "2028-11-07", 5)

@pytest.mark.parametrize("name", PROVIDERS)
def test_every_registered_provider_implements_interface(name):
    env = {"ELECTION_PROVIDER": name, "API_ENDPOINT": "https://feed.example/races"}
    assert isinstance(create_provider(env), ElectionDataProvider)

# --- json feed ---------------------------------------------------------------

def test_json_feed_wraps_transport_errors(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(ProviderError, match="down"):
        JsonFeedProvider("https://feed.example/races").get_live_races()

def test_json_feed_wraps_shape_errors(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse({"races": [{"race_id": "X"}]}))
    with pytest.raises(ProviderError, match="unexpected shape"):
        JsonFeedProvider("https://feed.example/races").get_live_races()

def test_json_feed_parses_races(monkeypatch):
    item = {"race_id": "PA-SEN", "state": "Pennsylvania", "dem_name": "D", "dem_votes": 10,
            "rep_name": "R", "rep_votes": 8, "expected_turnout": 40}
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse({"races": [item]}))
    [race] = JsonFeedProvider("https://feed.example/races").get_live_races()
    assert (race.race_id, race.dem_candidate.votes, race.prior_uncounted_dem_share) == ("PA-SEN", 10, 0.50)

# --- civicAPI ----------------------------------------------------------------

def test_civicapi_maps_search_results():
    races = [
        civic_race(87087, "Georgia US Senate", "GA",
                   [candidate("Collins", "Republican", 600), candidate("Ossoff", "Democratic", 400),
                    candidate("Minor", "Libertarian", 50)], percent_reporting=50),
        civic_race(1, "Georgia State Senate", "GA", [candidate("a", "Democratic", 1), candidate("b", "Republican", 1)]),
        {**civic_race(2, "Fulton US Senate", "GA", [candidate("a", "Democratic", 1), candidate("b", "Republican", 1)]),
         "election_type": "Local", "district": "Fulton"},
    ]
    session = FakeSession({SEARCH: FakeResponse({"races": races})})
    [race] = CivicApiProvider(session=session).get_live_races()
    assert race.race_id == "GA-SEN" and race.state == "Georgia"
    assert (race.dem_candidate.name, race.dem_candidate.votes) == ("Ossoff", 400)
    assert (race.rep_candidate.name, race.rep_candidate.votes) == ("Collins", 600)
    assert race.expected_total_turnout == 2000  # 1000 major-party votes at 50% reporting

def test_civicapi_searches_by_race_type():
    # civicAPI's free-text `query` stopped matching U.S. Senate races; the `type` filter still does.
    session = FakeSession({SEARCH: FakeResponse({"races": []})})
    CivicApiProvider(session=session).get_live_races()
    assert session.params[0]["type"] == "US Senate" and "query" not in session.params[0]

def test_civicapi_without_votes_gives_even_odds():
    races = [civic_race(3, "Maine US Senate", "ME", [candidate("Jackson", "Democratic", 0),
                                                    candidate("Collins", "Republican", 0)])]
    session = FakeSession({SEARCH: FakeResponse({"races": races})})
    [race] = CivicApiProvider(session=session).get_live_races()
    assert race.expected_total_turnout == 1_000_000
    result = ProjectionEngine.calculate_single_race(race)
    assert result.dem_win_prob == pytest.approx(0.5, abs=0.01)

def test_civicapi_without_democrat_uses_runner_up():
    races = [civic_race(4, "Nebraska US Senate", "NE", [candidate("Ricketts", "Republican", 70),
                                                       candidate("Osborn", "Independent", 60)], 10)]
    session = FakeSession({SEARCH: FakeResponse({"races": races})})
    [race] = CivicApiProvider(session=session).get_live_races()
    assert (race.dem_candidate.name, race.rep_candidate.name) == ("Osborn", "Ricketts")

def test_civicapi_without_republican_keeps_democrat_on_dem_side():
    races = [civic_race(6, "Vermont US Senate", "VT", [candidate("Dem", "Democratic", 100),
                                                      candidate("Ind", "Independent", 80)], 10)]
    session = FakeSession({SEARCH: FakeResponse({"races": races})})
    [race] = CivicApiProvider(session=session).get_live_races()
    assert (race.dem_candidate.name, race.rep_candidate.name) == ("Dem", "Ind")

def test_civicapi_skips_uncontested_races():
    races = [civic_race(5, "Somewhere US Senate", "XX", [candidate("Solo", "Democratic", 5)])]
    session = FakeSession({SEARCH: FakeResponse({"races": races})})
    assert CivicApiProvider(session=session).get_live_races() == []

def test_civicapi_test_mode_fetches_each_race():
    search = [civic_race(87087, "Georgia US Senate", "GA",
                         [candidate("a", "Democratic", 0), candidate("b", "Republican", 0)])]
    detail = civic_race(None, "Georgia US Senate", "GA",
                        [candidate("Ossoff", "Democratic", 300), candidate("Collins", "Republican", 100)], 40)
    session = FakeSession({SEARCH: FakeResponse({"races": search}),
                           "https://civicapi.org/api/v2/race/87087?testdata": FakeResponse(detail)})
    [race] = CivicApiProvider(test_data=True, session=session).get_live_races()
    assert race.dem_candidate.votes == 300 and race.expected_total_turnout == 1000
    assert len(session.calls) == 2

@pytest.mark.parametrize("response", [requests.ConnectionError("down"), FakeResponse({}, status=503),
                                      FakeResponse({"unexpected": True})])
def test_civicapi_wraps_failures(response):
    session = FakeSession({SEARCH: response})
    with pytest.raises(ProviderError):
        CivicApiProvider(session=session).get_live_races()

# --- party labels --------------------------------------------------------------

def test_forecast_keeps_actual_parties():
    races = [civic_race(4, "Nebraska US Senate", "NE", [candidate("Ricketts", "Republican", 990),
                                                       candidate("Osborn", "Independent", 10)], 99)]
    session = FakeSession({SEARCH: FakeResponse({"races": races})})
    [race] = CivicApiProvider(session=session).get_live_races()
    result = ProjectionEngine.calculate_single_race(race)
    assert (result.dem_party, result.rep_party) == ("Independent", "Republican")
    assert result.projected_winner == "Ricketts (REP)"

def test_party_label_abbreviates_known_parties_only():
    from src.models import party_label
    assert [party_label(p) for p in ("Democratic", "Republican", "DEM", "Legal Marijuana Now", "")] == \
        ["DEM", "REP", "DEM", "Legal Marijuana Now", "?"]

def test_even_race_has_no_leader():
    from src.ui.components import TIED
    from src.ui.components import leader_party as _leader_party
    races = [civic_race(3, "Maine US Senate", "ME", [candidate("Jackson", "Democratic", 0),
                                                    candidate("Collins", "Republican", 0)])]
    [race] = CivicApiProvider(session=FakeSession({SEARCH: FakeResponse({"races": races})})).get_live_races()
    assert _leader_party(ProjectionEngine.calculate_single_race(race)) == TIED

# --- pinned matchups and display names ---------------------------------------

ALASKA = [candidate("Gerald L. Heikes", "Republican", 0), candidate("Mary Peltola", "Democratic", 0),
          candidate("Dan Sullivan", "Republican", 0), candidate("Daniel J. Jr. Sullivan", "Republican", 0)]

def provider_for(races, **kwargs):
    return CivicApiProvider(session=FakeSession({SEARCH: FakeResponse({"races": races})}), **kwargs)

def test_pinned_matchup_overrides_listing_order():
    races = [civic_race(86916, "Alaska US Senate", "AK", ALASKA)]
    [race] = provider_for(races, matchups={"ak-sen": ["Mary Peltola", "Dan Sullivan"]}).get_live_races()
    assert (race.dem_candidate.name, race.rep_candidate.name) == ("Mary Peltola", "Dan Sullivan")

def test_pinned_matchup_matches_names_with_doubled_spaces():
    races = [civic_race(87254, "Nebraska US Senate", "NE", [candidate("Pete  Ricketts", "Republican", 0),
             candidate("Mike  Marvin", "Legal Marijuana Now", 0), candidate("Dan  Osborn", "Independent", 0)])]
    [race] = provider_for(races, matchups={"NE-SEN": ["Dan Osborn", "Pete Ricketts"]}).get_live_races()
    assert (race.dem_candidate.name, race.dem_candidate.party) == ("Dan Osborn", "Independent")
    assert race.rep_candidate.name == "Pete Ricketts"  # display name cleaned too

def test_pinned_matchup_with_unknown_name_falls_back():
    races = [civic_race(86916, "Alaska US Senate", "AK", ALASKA)]
    [race] = provider_for(races, matchups={"AK-SEN": ["Mary Peltola", "Nobody"]}).get_live_races()
    assert (race.dem_candidate.name, race.rep_candidate.name) == ("Mary Peltola", "Gerald L. Heikes")

def test_state_names_from_province():
    races = [civic_race(87527, "Ohio US Senate Special General", "OH",
                        [candidate("Sherrod Brown", "Democratic", 0), candidate("Jon Husted", "Republican", 0)])]
    [race] = provider_for(races).get_live_races()
    assert race.state == "Ohio (special)"

def test_shipped_matchups_file_loads():
    p = create_provider({"ELECTION_PROVIDER": "civicapi"})
    assert p.matchups["AK-SEN"] == ("Mary Peltola", "Dan Sullivan")

def test_bad_matchups_file_is_a_provider_error(tmp_path):
    (tmp_path / "m.toml").write_text('[matchups]\n"AK-SEN" = ["only one"]\n')
    with pytest.raises(ProviderError, match="exactly two"):
        create_provider({"ELECTION_PROVIDER": "civicapi", "CIVICAPI_MATCHUPS_FILE": str(tmp_path / "m.toml")})

# --- early vote ----------------------------------------------------------------

def test_early_vote_by_category_and_party():
    def payload(regions):
        return FakeResponse({"snapshot_date": "2026-10-30", "regions": regions})
    session = FakeSession({
        "https://civicapi.org/api/v2/early-vote/US/returned": payload(
            {"AZ": {"Democratic": {"votes": 10}, "Republican": {"votes": 12}}, "MI": {"Unspecified": {"votes": 7}}}),
        "https://civicapi.org/api/v2/early-vote/US/inperson": payload({"GA": {"Unspecified": {"votes": 5}}}),
    })
    ev = CivicApiProvider(session=session).get_early_vote()
    assert ev.snapshot_date == "2026-10-30"
    assert ev.by_category["Mail returned"]["AZ"] == {"Democratic": 10, "Republican": 12}
    assert ev.by_category["In person"]["GA"] == {"Unspecified": 5}

def test_early_vote_failure_is_a_provider_error():
    with pytest.raises(ProviderError):
        CivicApiProvider(session=FakeSession({})).get_early_vote()

def test_other_providers_have_no_early_vote():
    assert MockProvider().get_early_vote() is None


class FlakySession(FakeSession):
    """Fails the first request with the given error, then behaves like FakeSession."""

    def __init__(self, routes, first_error):
        super().__init__(routes)
        self.first_error = first_error

    def get(self, url, params=None, timeout=None):
        if self.first_error:
            error, self.first_error = self.first_error, None
            self.calls.append(url)
            raise error
        return super().get(url, params, timeout)


def test_civicapi_retries_a_dropped_connection_once():
    races = [civic_race(1, "Texas US Senate", "TX", [candidate("A", "Democratic", 1), candidate("B", "Republican", 2)])]
    session = FlakySession({SEARCH: FakeResponse({"races": races})}, requests.ConnectionError("Remote end closed"))
    assert len(CivicApiProvider(session=session).get_live_races()) == 1 and len(session.calls) == 2


def test_civicapi_does_not_retry_a_timeout():
    session = FlakySession({SEARCH: FakeResponse({"races": []})}, requests.ReadTimeout("slow"))
    with pytest.raises(ProviderError):
        CivicApiProvider(session=session).get_live_races()
    assert len(session.calls) == 1


def test_civicapi_gives_each_thread_its_own_session():
    import threading
    provider = CivicApiProvider()
    sessions = []
    threads = [threading.Thread(target=lambda: sessions.append(provider._session())) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({id(s) for s in sessions}) == 3 and provider._session() is provider._session()


def test_civicapi_early_votes_at_zero_reporting_keep_even_odds():
    # New Hampshire's midnight towns: 7 votes at 0% reporting must not look like 1% of the count.
    races = [civic_race(5, "New Hampshire US Senate", "NH", [candidate("Chris Pappas", "Democratic", 2),
                                                           candidate("John E. Sununu", "Republican", 5)], 0)]
    [race] = CivicApiProvider(session=FakeSession({SEARCH: FakeResponse({"races": races})})).get_live_races()
    result = ProjectionEngine.calculate_single_race(race)
    assert race.expected_total_turnout == 1_000_000 and result.pct_reporting < 0.01
    assert abs(result.dem_win_prob - 0.5) < 0.01 and result.projected_winner is None


def test_civicapi_scales_turnout_by_reporting():
    races = [civic_race(6, "Texas US Senate", "TX", [candidate("A", "Democratic", 300),
                                                   candidate("B", "Republican", 100)], 40)]
    [race] = CivicApiProvider(session=FakeSession({SEARCH: FakeResponse({"races": races})})).get_live_races()
    assert race.expected_total_turnout == 1000 and race.reporting_percentage == 40.0
