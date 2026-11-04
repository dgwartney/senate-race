"""ui.format helpers and the shared surname rule."""
from datetime import datetime, timezone

import pytest

from src.models import surname
from src.schedule import PollClosing
from src.ui.format import esc, et, et_clock, lead_text, pct, poll_close_label, short_name

T = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)  # 7 PM ET


def test_escape():
    assert esc('<b>"x"&') == "&lt;b&gt;&quot;x&quot;&amp;"


def test_eastern_times():
    assert et(T) == "Tue 7 PM ET" and et_clock(T) == "7:00:00 PM ET"
    assert et(T.replace(minute=30)) == "Tue 7:30 PM ET"


def test_poll_close_label():
    assert poll_close_label(None) == ""
    assert poll_close_label(PollClosing(T, T)) == "Tue 7 PM ET"
    assert poll_close_label(PollClosing(T, T.replace(hour=1))) == "Tue 7 PM ET (last 8 PM ET)"


@pytest.mark.parametrize("name, expected", [("KEN PAXTON", "PAXTON"), ("Daniel J. Jr. Sullivan", "Sullivan"),
                                            ('Michael "Dr. Mike" Katz', "Katz"), ("", "")])
def test_surname(name, expected):
    assert surname(name) == expected


def test_short_name_and_pct():
    assert short_name("") == "?" and short_name("Jon Ossoff") == "Ossoff"
    assert pct(0.5234) == "52.3%" and pct(0.5, 0) == "50%"


def test_lead_text_uses_counts_before_real_reporting():
    from src.models import ForecastResult
    early = ForecastResult("NH-SEN", "New Hampshire", "Chris Pappas", "Democratic", 2, "John E. Sununu",
                           "Republican", 5, 0.0007, 0.5, 0.5, None)
    counting = early.__class__(**{**early.__dict__, "dem_votes": 600, "rep_votes": 400, "pct_reporting": 12.0})
    assert lead_text(early) == "Sununu leads by 5 votes to 2 · early votes, under 1% reporting"
    assert lead_text(counting) == "Pappas leads by 20.0%"
