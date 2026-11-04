"""Text formatting shared by every part of the UI.

Anything that came from an external feed (names, parties, source labels) must pass
through :func:`esc` before it is placed in HTML.
"""
import html
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from src.models import ForecastResult, surname
from src.schedule import PollClosing

EASTERN = ZoneInfo("America/New_York")
EARLY_REPORTING = 1.0
"""Percent reporting below which leads are shown as raw counts, not percentages (see :func:`lead_text`)."""
DASH = "—"
"""Shown in place of numbers that don't exist yet (e.g. before any votes are counted)."""


def esc(text: object) -> str:
    """HTML-escape any value for safe inclusion in markup."""
    return html.escape(str(text), quote=True)


def et(t: datetime) -> str:
    """Day and time in Eastern Time, dropping ``:00``: ``"Tue 8 PM ET"``, ``"Tue 8:30 PM ET"``."""
    return t.astimezone(EASTERN).strftime("%a %-I:%M %p ET").replace(":00 ", " ")


def et_clock(t: datetime) -> str:
    """Clock time in Eastern Time to the second: ``"4:11:29 PM ET"``."""
    return t.astimezone(EASTERN).strftime("%-I:%M:%S %p ET")


def poll_close_label(closing: Optional[PollClosing]) -> str:
    """``"Tue 7 PM ET"``, or ``"Tue 7 PM ET (last 8 PM ET)"`` where a state spans two time zones."""
    if not closing:
        return ""
    if closing.last == closing.first:
        return et(closing.first)
    return f"{et(closing.first)} (last {et(closing.last).split(' ', 1)[1]})"


def short_name(name: str) -> str:
    """Surname for compact displays, falling back to the full name, then ``"?"``."""
    return surname(name) or name or "?"


def pct(value: float, digits: int = 1) -> str:
    """A 0..1 fraction as a percentage: ``pct(0.523) == "52.3%"``."""
    return f"{value:.{digits}%}"


def votes(n: int) -> str:
    """Vote count with thousands separators."""
    return f"{n:,}"


def lead_text(res: ForecastResult) -> str:
    """Who leads, worded for how much has been counted. Assumes ``res.leader`` is set.

    Below :data:`EARLY_REPORTING` the raw count is shown
    ("Sununu leads by 5 votes to 2 · early votes, under 1% reporting"):
    New Hampshire's midnight towns report a handful of votes long before anyone else, and
    "leads by 42.9%" would overstate seven ballots.
    """
    leader = res.leader
    name = short_name(leader.name)
    if res.pct_reporting < EARLY_REPORTING:
        trailing = res.rep_votes if leader.votes == res.dem_votes else res.dem_votes
        return (f"{name} leads by {votes(leader.votes)} votes to {votes(trailing)}"
                f" · early votes, under {EARLY_REPORTING:.0f}% reporting")
    return f"{name} leads by {pct(abs(res.margin))}"
