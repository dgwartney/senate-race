"""Pure view-model logic of the page sections (no Streamlit rendering)."""
from datetime import datetime, timezone

from src.models import EarlyVote, ForecastResult
from src.officials import OfficialCount, OfficialResult
from src.schedule import PollClosing
from src.tags import ControlTally, RaceTags
from src.ui.components import (
    DashboardContext,
    RaceDetailPanel,
    RaceTable,
    TopPane,
    default_race,
    early_vote_row,
    official_line,
)
from src.ui.format import DASH

SIX_PM = datetime(2026, 11, 3, 23, 0, tzinfo=timezone.utc)
SEVEN_PM = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)


def race(race_id, dem=0, rep=0, p=0.5, state=None):
    return ForecastResult(race_id, state or race_id[:2], "Jane Doe", "Democratic", dem, "John Roe", "Republican",
                          rep, 50.0 if dem + rep else 0.0, p, 1 - p, None)


TAGS = RaceTags({"ME-SEN": ["toss-up"], "TX-SEN": ["toss-up"]}, ControlTally("toss-up", 2, 1))


def test_top_pane_metrics_and_waiting_line():
    ctx = DashboardContext([race("KY-SEN"), race("TX-SEN")], TAGS,
                           {"KY": PollClosing(SIX_PM, SEVEN_PM), "TX": PollClosing(SEVEN_PM, SEVEN_PM)})
    pane = TopPane(ctx, now=datetime(2026, 11, 3, 21, 0, tzinfo=timezone.utc))
    assert pane.waiting_line() == "No votes counted yet; next polls close Tue 6 PM ET (KY)."
    labels = [m.label for m in pane.metrics()]
    assert len(labels) == 6 and pane.metrics()[2].value == "No votes yet"


def test_top_pane_counts_leaders_by_votes():
    results = [race("ME-SEN", 60, 40, 0.9), race("TX-SEN", 40, 60, 0.1), race("GA-SEN", 70, 30, 0.95)]
    ctx = DashboardContext(results, TAGS)
    pane = TopPane(ctx)
    m = {x.label: x for x in pane.metrics()}
    assert m["Races led (D / R / I…)"].value == "2 D · 1 R"
    assert m["toss-up: DEM leading"].value == "1 of 2" and m["toss-up: REP leading"].delta == "needs 1"
    assert pane.waiting_line() is None


def test_default_race_is_closest_counted_tagged_first():
    results = [race("GA-SEN", 501, 499), race("TX-SEN", 60, 40), race("ME-SEN", 52, 48), race("AK-SEN")]
    ctx = DashboardContext(results, TAGS)
    assert default_race(ctx) == "ME-SEN"
    assert default_race(DashboardContext([race("AK-SEN")], TAGS)) is None


def test_detail_model():
    ctx = DashboardContext([race("TX-SEN", 600, 400, 0.8)], TAGS, {"TX": PollClosing(SEVEN_PM, SEVEN_PM)})
    d = RaceDetailPanel(ctx).model(ctx.results[0])
    assert d.status == "Doe leads by 20.0%" and d.subtitle == "TX-SEN · toss-up · polls close Tue 7 PM ET"
    dem, rep = d.sides
    assert dem.leads and not rep.leads and dem.share == 0.6 and rep.win_prob == 0.19999999999999996
    html = RaceDetailPanel.html(d)
    assert "Chance of winning" in html and "width:60.0%" in html


def test_detail_before_votes_has_no_odds_and_escapes():
    evil = ForecastResult("TX-SEN", "<b>Texas</b>", "A <i>", "Democratic", 0, "B", "Republican", 0, 0, .5, .5, None)
    d = RaceDetailPanel(DashboardContext([evil])).model(evil)
    html = RaceDetailPanel.html(d)
    assert d.status == "No votes counted yet" and "Chance of winning" not in html
    assert "<b>Texas" not in html and "&lt;i&gt;" in html


def test_race_table_blank_before_votes_and_selected_first():
    rows = RaceTable(DashboardContext([race("AK-SEN"), race("TX-SEN", 6, 4)])).rows(selected="TX-SEN")
    assert rows[0]["race"] == "TX-SEN" and rows[0]["DEM votes"] == "6" and rows[0]["leader"] == "Doe +20.0%"
    assert rows[1]["DEM votes"] == rows[1]["reporting"] == rows[1]["leader"] == DASH


def test_official_line_flags_disagreement():
    count = OfficialCount("TX", "Texas SOS", "https://x", {"John Roe": 900, "Jane Doe": 100}, "1 of 2")
    line = official_line(race("TX-SEN", 600, 400), OfficialResult("TX", count=count))
    assert "Doe 100 vs Roe 900" in line and "leader differs" in line
    assert official_line(race("TX-SEN"), None) is None
    assert "unavailable" in official_line(race("TX-SEN"), OfficialResult("TX", error="down"))


def test_early_vote_row():
    ev = EarlyVote("2026-11-02", {"Mail": {"TX": {"Democratic": 30, "Republican": 50, "None": 20}},
                                  "In person": {"TX": {"Democratic": 0}}})
    row = early_vote_row(ev, "TX")
    assert row.total == 100 and row.dem_share == 0.3 and row.other_share == 0.2
    assert early_vote_row(ev, "AK") is None and early_vote_row(None, "TX") is None


def test_early_votes_are_worded_as_counts_and_not_charted():
    from src.live import MarginPoint
    nh = ForecastResult("NH-SEN", "New Hampshire", "Chris Pappas", "Democratic", 2, "John E. Sununu", "Republican",
                        5, 0.0007, 0.5, 0.5, None)
    calls = []
    early_points = [MarginPoint(SIX_PM, -0.43, 0.0007), MarginPoint(SEVEN_PM, -0.43, 0.0007)]
    ctx = DashboardContext([nh], margin_history=lambda race_id: calls.append(race_id) or early_points)
    assert RaceDetailPanel(ctx).model(nh).status == "Sununu leads by 5 votes to 2 · early votes, under 1% reporting"
    from src.ui.usmap import HoverCard
    assert "leads by 5 votes to 2" in HoverCard(nh).html()


def test_official_line_names_the_state_feed_when_it_supplied_the_totals():
    from src.models import ForecastResult
    from src.officials import OfficialCount, OfficialResult
    from src.ui.components import official_line
    res = ForecastResult("OH-SEN", "Ohio", "Sherrod Brown", "Democratic", 9, "Jon Husted", "Republican", 8,
                         1.0, 0.5, 0.5, None, source="Ohio Secretary of State")
    result = OfficialResult("OH", count=OfficialCount("OH", "Ohio Secretary of State", "https://x",
                                                      {"Sherrod Brown": 9, "Jon Husted": 8}, "9 of 99 precincts"))
    assert official_line(res, result) == "Counts from [Ohio Secretary of State](https://x) · 9 of 99 precincts"
