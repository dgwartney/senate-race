"""UsMapBuilder and HoverCard."""
from src.models import ForecastResult
from src.tags import RaceTags
from src.ui.theme import SELECTED_OUTLINE
from src.ui.usmap import HoverCard, UsMapBuilder, clicked_state


def race(race_id, dem_votes=0, rep_votes=0, dem_prob=0.5, dem_name="Jane Doe", state=None):
    return ForecastResult(race_id=race_id, state=state or race_id[:2], dem_name=dem_name, dem_party="Democratic",
                          dem_votes=dem_votes, rep_name="John Roe", rep_party="Republican", rep_votes=rep_votes,
                          pct_reporting=10.0, dem_win_prob=dem_prob, rep_win_prob=1 - dem_prob,
                          projected_winner=None)


def build(results, selected=None):
    return UsMapBuilder(RaceTags(), {}).build(results, selected)


def traces(fig):
    return {t.name: t for t in fig.data}


def test_every_state_is_drawn_once_including_alaska_and_hawaii():
    fig = build([race("AK-SEN"), race("TX-SEN", 600, 400, 0.8)])
    drawn = [s for t in fig.data for s in t.locations]
    assert len(drawn) == len(set(drawn)) == 50 and {"AK", "HI"} <= set(drawn)
    assert fig.layout.geo.projection.type == "albers usa"  # draws Alaska and Hawaii as insets


def test_states_split_by_counting_status():
    t = traces(build([race("AK-SEN"), race("TX-SEN", 600, 400, 0.8)]))
    assert list(t["No votes yet"].locations) == ["AK"]
    assert list(t["Counting"].locations) == ["TX"] and list(t["Counting"].z) == [0.8]
    assert "HI" in t["No race"].locations and "TX" not in t["No race"].locations


def test_selected_state_is_outlined_in_its_own_trace():
    t = traces(build([race("AK-SEN"), race("TX-SEN", 600, 400, 0.8)], selected="TX"))
    counting = t["Counting"]
    assert list(counting.marker.line.color) == [SELECTED_OUTLINE] and list(counting.marker.line.width) == [3]
    assert SELECTED_OUTLINE not in list(t["No votes yet"].marker.line.color)


def test_hover_card_shows_votes_shares_odds_and_leader():
    text = HoverCard(race("TX-SEN", 600, 400, 0.8), "Tue 8 PM ET", ("toss-up",)).html()
    assert "Doe (DEM)" in text and "600" in text and "60.0%" in text and "80%" in text
    assert "polls close Tue 8 PM ET" in text and "toss-up" in text
    assert "Doe leads by 20.0%" in text and "#2166ac" in text and "Click for details" in text


def test_hover_card_before_votes():
    text = HoverCard(race("AK-SEN")).html()
    assert "50%" not in text and "polls close" not in text and "No votes counted yet" in text


def test_hover_escapes_untrusted_names():
    evil = race("TX-SEN", 1, 0, 0.6, dem_name="Eve <script>x</script>", state="<i>Texas</i>")
    text = HoverCard(evil).html()
    assert "<script>" not in text and "<i>Texas" not in text and "&lt;i&gt;Texas" in text


def test_clicked_state_reads_streamlit_event():
    assert clicked_state({"selection": {"points": [{"location": "TX"}, {"location": "AK"}]}}) == "AK"
    assert clicked_state(None) is None and clicked_state({"selection": {"points": []}}) is None
