import base64
import json

import pytest
import requests

from src.officials import IowaFeed, OfficialCount, OfficialResult, OhioFeed, TexasFeed, fetch_all, surname, votes_for
from src.providers.base import ProviderError


class FakeResponse:
    def __init__(self, payload=None, text="", status=200):
        self.payload, self.text, self.status_code, self.headers = payload, text, status, {}
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")
    def json(self):
        return self.payload

class FakeSession:
    def __init__(self, routes):
        self.routes, self.headers = routes, {}
    def get(self, url, params=None, timeout=None):
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                return response
        return FakeResponse(status=404)

def test_iowa_reads_current_version_then_summary():
    session = FakeSession({
        "https://electionresults.iowa.gov/IA/127077/current_ver.txt": FakeResponse(text="382865\n"),
        "https://electionresults.iowa.gov/IA/127077/382865/json/en/summary.json": FakeResponse([
            {"C": "Governor", "CH": [], "V": []},
            {"C": "United States Senator", "TP": 99, "PR": 40, "CH": ["Ashley Hinson", "Josh Turek", "Write-in"],
             "V": [5000, 4800, 3]}]),
    })
    count = IowaFeed(session=session).fetch()
    assert count.votes == {"Ashley Hinson": 5000, "Josh Turek": 4800}
    assert count.reporting == "40 of 99 counties"

def test_ohio_reads_candidates_and_precincts():
    payload = {"contestList": [{"candidatesRunning": [
                   # Live shape (3 Nov): totalVotes is the contest total on every row; vCount is the candidate's.
                   {"primaryCandidate": "Sherrod Brown", "totalVotes": 221.0, "vCount": 120.0, "isWriteIn": False},
                   {"primaryCandidate": "Jon Husted", "totalVotes": 221.0, "vCount": 100.0, "isWriteIn": False},
                   {"primaryCandidate": "Someone", "totalVotes": 221.0, "vCount": 1.0, "isWriteIn": True}]}],
               "contestStatistics": {"allStatistics": [
                   {"name": "Election Day Precincts Reporting", "value": "1,200 (14%)"},
                   {"name": "Total Number of Election Day Precincts", "value": "8,834"}]}}
    session = FakeSession({"https://liveresults.ohiosos.gov/Api/v1/Contest/getMyResults": FakeResponse(payload)})
    count = OhioFeed(session=session).fetch()
    assert count.votes == {"Sherrod Brown": 120, "Jon Husted": 100}
    assert count.reporting == "1,200 of 8,834 precincts"

def test_texas_decodes_base64_sections():
    enc = lambda obj: base64.b64encode(json.dumps(obj).encode()).decode()
    federal = {"Races": [{"N": "U. S. SENATOR ", "Candidates": [
        {"N": "KEN PAXTON", "P": "REP", "V": 900}, {"N": "JAMES TALARICO", "P": "DEM", "V": 950},
        {"N": "AVERY AYERS", "P": "W", "V": 2}]}]}
    home = {"PollingReporting": {"PLR": 1200, "PLT": 5302}}
    session = FakeSession({"https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/53815":
                           FakeResponse({"Home": enc(home), "Federal": enc(federal)})})
    count = TexasFeed(session=session).fetch()
    assert count.votes == {"Ken Paxton": 900, "James Talarico": 950}
    assert count.reporting == "1,200 of 5,302 polling places"

@pytest.mark.parametrize("feed_cls", [IowaFeed, OhioFeed, TexasFeed])
def test_feed_failures_are_provider_errors(feed_cls):
    with pytest.raises(ProviderError):
        feed_cls(session=FakeSession({})).fetch()

def test_fetch_all_reports_errors_per_state():
    ok = OfficialCount("OH", "Ohio", "u", {"A": 1}, "x")
    class Good:
        state = "OH"
        def fetch(self): return ok
    class Bad:
        state = "TX"
        def fetch(self): raise ProviderError("down")
    results = fetch_all([Good(), Bad()])
    assert results["OH"].count is ok and results["OH"].ok
    assert not results["TX"].ok and results["TX"].error == "down"

def test_official_result_round_trips_through_dict():
    for result in (OfficialResult("OH", count=OfficialCount("OH", "Ohio", "u", {"A": 1}, "x")),
                   OfficialResult("TX", error="down")):
        assert OfficialResult.from_dict(result.to_dict()) == result

@pytest.mark.parametrize("name, expected", [("KEN PAXTON", "paxton"), ("Daniel J. Jr. Sullivan", "sullivan"),
                                            ('Michael "Dr. Mike" Katz', "katz"), ("Brown, Sherrod", "sherrod")])
def test_surname(name, expected):
    assert surname(name) == expected

def test_votes_for_matches_across_capitalisation():
    count = OfficialCount("TX", "Texas", "u", {"Ken Paxton": 900, "James Talarico": 950}, "x")
    assert votes_for(count, "Ken Paxton") == 900 and votes_for(count, "James Talarico") == 950
    assert votes_for(count, "Nobody Here") is None

def test_feeds_identify_themselves_instead_of_python_requests():
    assert IowaFeed().session.headers["User-Agent"].startswith("senate-race-dashboard/")

def test_bot_challenge_is_reported_clearly():
    challenged = FakeResponse(text="", status=202)
    challenged.headers = {"x-amzn-waf-action": "challenge"}
    session = FakeSession({"https://electionresults.iowa.gov/": challenged})
    with pytest.raises(ProviderError, match="bot protection"):
        IowaFeed(session=session).fetch()

@pytest.mark.parametrize("value, states", [(None, ["IA", "OH", "TX"]), ("OH,TX", ["OH", "TX"]), ("", []),
                                           ("tx, xx", ["TX"])])
def test_configured_feeds(value, states):
    from src.officials import configured_feeds
    env = {} if value is None else {"OFFICIAL_FEEDS": value}
    assert [f.state for f in configured_feeds(env)] == states
