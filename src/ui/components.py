"""Page sections of the dashboard.

Each component takes a :class:`DashboardContext` and splits into a pure model method
(data -> display values, unit-tested) and a thin ``render`` (Streamlit calls).

Layout, top to bottom: pinned :class:`TopPane`; :class:`MapPanel` with the
:class:`RaceDetailPanel` beside the map; :class:`RaceTable`; then :class:`RaceCards`,
:class:`EarlyVotePanel` and :class:`RawTotals` in collapsed expanders.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from src.live import MarginPoint
from src.models import EarlyVote, ForecastResult, Notice
from src.officials import OfficialResult, votes_for
from src.schedule import PollClosing
from src.tags import RaceTags
from src.ui.charts import margin_figure
from src.ui.format import DASH, EARLY_REPORTING, esc, et, et_clock, lead_text, pct, poll_close_label, short_name, votes
from src.ui.theme import BADGE_COLORS, MUTED, PAGE_CSS, party_color
from src.ui.usmap import UsMapBuilder, clicked_state

SELECTED_RACE = "selected_race"
"""Session-state key holding the race ID whose details are open."""
MAP_KEY = "us_map"
"""Widget key of the map (its value is Plotly's selection event)."""
TIED = "tied"


@dataclass(frozen=True)
class DashboardContext:
    """Everything the page shows, gathered once per refresh.

    Attributes:
        results: Forecasts, one per race.
        tags: Race tags and the control-tally definition.
        closings: State code -> poll-closing times.
        officials: State code -> official state feed result.
        early_vote: Early-vote turnout, if available.
        notices: Freshness and failure messages.
        data_time: When the results were last confirmed by a fetch.
        attribution: Data source credit line.
        margin_history: Race ID -> margin over the night (for the details chart).
    """

    results: List[ForecastResult]
    tags: RaceTags = field(default_factory=RaceTags)
    closings: Dict[str, PollClosing] = field(default_factory=dict)
    officials: Dict[str, OfficialResult] = field(default_factory=dict)
    early_vote: Optional[EarlyVote] = None
    notices: List[Notice] = field(default_factory=list)
    data_time: Optional[datetime] = None
    attribution: str = ""
    margin_history: Callable[[str], List[MarginPoint]] = lambda race_id: []

    def closing_label(self, state_code: str) -> str:
        """Formatted poll-closing time for a state, or ``""``."""
        return poll_close_label(self.closings.get(state_code))

    def race(self, race_id: Optional[str]) -> Optional[ForecastResult]:
        """The forecast for a race ID, or None."""
        return next((r for r in self.results if r.race_id == race_id), None)

    @property
    def any_votes(self) -> bool:
        """True once any race has counted votes."""
        return any(r.has_votes for r in self.results)

    def next_closing(self, now: datetime) -> Optional[Tuple[datetime, List[str]]]:
        """The next poll-closing time after ``now`` among states with races, and those states."""
        upcoming = sorted((c.first, r.state_code) for r in self.results
                          if (c := self.closings.get(r.state_code)) and c.first > now)
        if not upcoming:
            return None
        first = upcoming[0][0]
        return first, sorted({s for t, s in upcoming if t == first})


# ---- shared view-model helpers -------------------------------------------------------------

def leader_party(res: ForecastResult) -> str:
    """Party label of the side ahead in votes, or ``TIED`` before votes or when level."""
    return res.leader.label if res.leader else TIED


def official_line(res: ForecastResult, result: Optional[OfficialResult]) -> Optional[str]:
    """Markdown comparing a state's own count with the main feed; None when the state has no feed."""
    if result is None:
        return None
    if not result.ok:
        return "Official state count unavailable right now"
    official = result.count
    link = f"[{official.source}]({official.url})"
    if res.source == official.source:
        return f"Counts from {link} · {official.reporting}"
    if not any(official.votes.values()):
        # Pre-election feeds can carry test "reporting" figures; don't show them until votes exist.
        return f"Official, {link}: no votes reported yet"
    dv, rv = votes_for(official, res.dem_name), votes_for(official, res.rep_name)
    fmt = lambda v: votes(v) if v is not None else "n/a"
    line = (f"Official, {link}: {short_name(res.dem_name)} {fmt(dv)} vs "
            f"{short_name(res.rep_name)} {fmt(rv)} · {official.reporting}")
    if None not in (dv, rv) and dv + rv > 0 and res.has_votes and (dv > rv) != (res.dem_votes > res.rep_votes):
        line += " :warning: leader differs from the main feed"
    return line


@dataclass(frozen=True)
class EarlyVoteRow:
    """One state's early ballots: per category, total, and party-registration shares."""

    by_category: Dict[str, int]
    total: int
    dem_share: Optional[float]
    rep_share: Optional[float]
    other_share: Optional[float]


def early_vote_row(early_vote: Optional[EarlyVote], state_code: str) -> Optional[EarlyVoteRow]:
    """Early-vote figures for a state, or None when the source has nothing for it.

    Party shares are given only where every ballot has a known registration.
    """
    if not early_vote:
        return None
    by_cat = {cat: early_vote.by_category.get(cat, {}).get(state_code, {}) for cat in early_vote.by_category}
    parties: Counter = Counter()
    for counts in by_cat.values():
        parties.update(counts)
    total = sum(parties.values())
    if not total:
        return None
    known = not parties.get("Unspecified")
    dem, rep = parties.get("Democratic", 0), parties.get("Republican", 0)
    return EarlyVoteRow({cat: sum(c.values()) for cat, c in by_cat.items() if c}, total,
                        dem / total if known else None, rep / total if known else None,
                        (total - dem - rep) / total if known else None)


def default_race(ctx: DashboardContext) -> Optional[str]:
    """Race to show before the viewer picks one: the closest counted race, tagged races first."""
    counted = [r for r in ctx.results if r.has_votes]
    if not counted:
        return None
    return min(counted, key=lambda r: (not ctx.tags.for_race(r.race_id), abs(r.margin))).race_id


# ---- page ------------------------------------------------------------------------------------

def apply_page_style() -> None:
    """Inject the dashboard's CSS (pinned top pane, compact spacing, details card)."""
    st.markdown(PAGE_CSS, unsafe_allow_html=True)


# ---- top pane --------------------------------------------------------------------------------

@dataclass(frozen=True)
class Metric:
    """One headline number."""

    label: str
    value: str
    delta: Optional[str] = None


class TopPane:
    """Title, data freshness, notices and the headline numbers, pinned to the top of the page."""

    def __init__(self, ctx: DashboardContext, now: Optional[datetime] = None):
        self.ctx = ctx
        self.now = now or datetime.now(timezone.utc)

    def meta_line(self) -> str:
        """Source, data time and method, as plain text."""
        updated = f"data as of {et_clock(self.ctx.data_time)}" if self.ctx.data_time else "no data yet"
        return " · ".join(x for x in (self.ctx.attribution, updated,
                                      "win odds assume the uncounted vote splits about evenly (±3.5 pts)") if x)

    def waiting_line(self) -> Optional[str]:
        """Before any votes: when the first results are due. None once counting starts."""
        if not self.ctx.results or self.ctx.any_votes:
            return None
        nxt = self.ctx.next_closing(self.now)
        when = f"; next polls close {et(nxt[0])} ({', '.join(nxt[1])})" if nxt else ""
        return f"No votes counted yet{when}."

    def metrics(self) -> List[Metric]:
        """Contests, mean reporting, races led, and (if configured) the control tally."""
        results, tags = self.ctx.results, self.ctx.tags
        avg = sum(r.pct_reporting for r in results) / max(1, len(results))
        leaders = Counter(leader_party(r) for r in results)
        # Compact ("21 D · 11 R · 3 I") so it fits a sixth of the page width.
        led = " · ".join(f"{n} {p[0]}" for p, n in leaders.most_common() if p != TIED)
        out = [Metric("Contests", str(len(results))), Metric("Mean reporting", f"{avg:.1f}%"),
               Metric("Races led (D / R / I…)", led or "No votes yet")]
        control = tags.control
        if control:
            tagged = [r for r in results if control.tag in tags.for_race(r.race_id)]
            expected = sum(1 for t in tags.by_race.values() if control.tag in t)
            leads = Counter(leader_party(r) for r in tagged)
            others = sum(n for p, n in leads.items() if p not in ("DEM", "REP", TIED))
            out += [
                Metric(f"{control.tag}: DEM leading", f"{leads['DEM']} of {expected}", f"needs {control.dem_needed}"),
                Metric(f"{control.tag}: REP leading", f"{leads['REP']} of {expected}", f"needs {control.rep_needed}"),
                Metric("Tied / other / missing", f"{leads[TIED]} / {others} / {expected - len(tagged)}"),
            ]
        return out

    def render(self) -> None:
        """Draw the pane (pinned by the ``toppane`` CSS key)."""
        with st.container(key="toppane"):
            st.markdown(f"<div class='top-title'><b>Senate Live Tracker</b><span>{esc(self.meta_line())}</span></div>",
                        unsafe_allow_html=True)
            for notice in self.ctx.notices:
                getattr(st, notice.severity.value)(notice.text)
            if not self.ctx.results:
                return
            waiting = self.waiting_line()
            if waiting:
                st.caption(waiting)
            metrics = self.metrics()
            for col, m in zip(st.columns(len(metrics)), metrics, strict=True):
                col.metric(m.label, m.value, m.delta, delta_color="off")


# ---- map + details ---------------------------------------------------------------------------

def _on_map_click(race_by_state: Dict[str, str]) -> None:
    """Map selection callback: open the clicked state's race."""
    state = clicked_state(st.session_state.get(MAP_KEY))
    if state in race_by_state:
        st.session_state[SELECTED_RACE] = race_by_state[state]


@dataclass(frozen=True)
class SideView:
    """One candidate row of the details panel."""

    name: str
    label: str
    color: str
    votes: int
    share: Optional[float]
    win_prob: Optional[float]
    leads: bool


@dataclass(frozen=True)
class RaceDetail:
    """Everything the details panel shows for one race."""

    title: str
    subtitle: str
    status: str
    status_color: str
    sides: List[SideView]
    reporting: str
    official: Optional[str]
    early: Optional[EarlyVoteRow]


class RaceDetailPanel:
    """Details of one race, shown beside the map: who leads, shares, odds, official count, early vote."""

    def __init__(self, ctx: DashboardContext):
        self.ctx = ctx

    def model(self, res: ForecastResult) -> RaceDetail:
        """Display values for a race."""
        ctx = self.ctx
        sides = []
        for side in (res.dem, res.rep):
            share = side.votes / res.total_votes if res.has_votes else None
            sides.append(SideView(side.name, side.label, party_color(side.party), side.votes, share,
                                  side.win_prob if res.has_votes else None, res.leader == side))
        if res.projected_winner:
            status = f"✔ Projected winner: {res.projected_winner}"
            color = party_color(res.leader.party) if res.leader else MUTED
        elif res.leader:
            status, color = lead_text(res), party_color(res.leader.party)
        else:
            status, color = ("Tied" if res.has_votes else "No votes counted yet"), MUTED
        closing = ctx.closing_label(res.state_code)
        subtitle = " · ".join([res.race_id, *ctx.tags.for_race(res.race_id)]
                              + ([f"polls close {closing}"] if closing else []))
        return RaceDetail(res.state, subtitle, status, color, sides, f"{res.pct_reporting:.1f}% reporting",
                          official_line(res, ctx.officials.get(res.state_code)),
                          early_vote_row(ctx.early_vote, res.state_code))

    @staticmethod
    def html(d: RaceDetail) -> str:
        """The panel's card as HTML (all feed text escaped)."""
        rows = []
        for s in d.sides:
            name = f"■ {esc(s.name)} ({esc(s.label)})"
            name = f"<b>{name}</b>" if s.leads else name
            nums = votes(s.votes) + (f" · {pct(s.share)}" if s.share is not None else "")
            width = f"{(s.share or 0) * 100:.1f}%"
            rows.append(f"<div class='rd-side'><div class='rd-row'><span style='color:{s.color}'>{name}</span>"
                        f"<span class='rd-num'>{nums}</span></div>"
                        f"<div class='rd-bar'><div style='width:{width};background:{s.color}'></div></div></div>")
        odds = ""
        if all(s.win_prob is not None for s in d.sides):
            # Label a slice only when it is wide enough to hold the text.
            parts = "".join(f"<div style='width:{max(s.win_prob, 0.001) * 100:.1f}%;background:{s.color}'>"
                            f"{esc(s.label) + ' ' + pct(s.win_prob, 0) if s.win_prob >= 0.15 else ''}</div>"
                            for s in d.sides)
            odds = (f"<div class='rd-sub' style='margin-top:0.4rem'>Chance of winning</div>"
                    f"<div class='rd-odds'>{parts}</div>")
        return (f"<div class='race-detail'><div class='rd-title'>{esc(d.title)}</div>"
                f"<div class='rd-sub'>{esc(d.subtitle)}</div>"
                f"<div class='rd-status' style='color:{d.status_color}'>{esc(d.status)}</div>"
                + "".join(rows) + odds + f"<div class='rd-meta'>{esc(d.reporting)}</div></div>")

    def render(self, res: Optional[ForecastResult], is_default: bool) -> None:
        """Draw the details for ``res``, or a prompt when nothing is chosen."""
        if res is None:
            st.markdown("<div class='race-detail rd-sub'>Hover a state for a summary; click it for details here.</div>",
                        unsafe_allow_html=True)
            return
        d = self.model(res)
        if is_default:
            st.caption("Closest race so far. Click a state to see another.")
        st.markdown(self.html(d), unsafe_allow_html=True)
        # Chart only real counting: a few early votes at 0% reporting draw a misleading flat block.
        history = [p for p in self.ctx.margin_history(res.race_id) if p.pct_reporting >= EARLY_REPORTING]
        if len(history) >= 2:
            st.caption("Lead over the night (percentage points)")
            st.plotly_chart(margin_figure(history, res.dem.label, res.rep.label, party_color(res.dem_party),
                                          party_color(res.rep_party)),
                            width="stretch", config={"displayModeBar": False}, key=f"margin-{res.race_id}")
        if d.official:
            st.caption(d.official)
        if d.early:
            parts = ", ".join(f"{cat.lower()} {votes(n)}" for cat, n in d.early.by_category.items())
            line = f"Early ballots: {votes(d.early.total)} ({parts})"
            if d.early.dem_share is not None:
                line += (f" · registered DEM {pct(d.early.dem_share, 0)}, REP {pct(d.early.rep_share, 0)}, "
                         f"other {pct(d.early.other_share, 0)}")
            st.caption(line)


class MapPanel:
    """The map (left, 70% of the width) and the selected race's details (right)."""

    def __init__(self, ctx: DashboardContext):
        self.ctx = ctx

    def options(self) -> List[str]:
        """Race IDs for the race picker, in state-name order."""
        return [r.race_id for r in sorted(self.ctx.results, key=lambda r: r.state)]

    def selection(self) -> Tuple[Optional[ForecastResult], bool]:
        """(race to show, whether it is the automatic default rather than the viewer's pick)."""
        chosen = self.ctx.race(st.session_state.get(SELECTED_RACE))
        if chosen:
            return chosen, False
        return self.ctx.race(default_race(self.ctx)), True

    def render(self) -> None:
        """Draw the map and the details panel side by side."""
        ctx = self.ctx
        current = st.session_state.setdefault(SELECTED_RACE, None)
        if current is not None and current not in self.options():
            st.session_state[SELECTED_RACE] = None  # a race that vanished from the feed
        res, is_default = self.selection()
        race_by_state: Dict[str, str] = {}
        for r in ctx.results:
            race_by_state.setdefault(r.state_code, r.race_id)
        labels = {s: poll_close_label(c) for s, c in ctx.closings.items()}
        map_col, detail_col = st.columns([0.7, 0.3], gap="small")
        with map_col:
            fig = UsMapBuilder(ctx.tags, labels).build(ctx.results, res.state_code if res else None)
            st.plotly_chart(fig, width="stretch", on_select=partial(_on_map_click, race_by_state),
                            selection_mode="points", key=MAP_KEY,
                            config={"displayModeBar": False, "scrollZoom": False})
        with detail_col:
            names = {r.race_id: f"{r.state} ({r.race_id})" for r in ctx.results}
            st.selectbox("Race", self.options(), key=SELECTED_RACE, format_func=names.get,
                         placeholder="Click a state, or choose a race", label_visibility="collapsed")
            RaceDetailPanel(ctx).render(res, is_default)


# ---- tables and expanders --------------------------------------------------------------------

class RaceTable:
    """Every race in one sortable table; the open race first. Blank numbers before votes exist."""

    def __init__(self, ctx: DashboardContext):
        self.ctx = ctx

    def rows(self, selected: Optional[str] = None) -> List[dict]:
        """Table rows. Numbers are pre-formatted text so races without votes read "—", not 0 or None."""
        out = []
        ordered = sorted(self.ctx.results, key=lambda r: (r.race_id != selected, r.state))
        for r in ordered:
            show = lambda value, counted=r.has_votes: value if counted else DASH
            leader = r.leader
            out.append({
                "state": r.state, "race": r.race_id,
                "DEM side": f"{r.dem_name} ({r.dem.label})", "DEM votes": show(votes(r.dem_votes)),
                "REP side": f"{r.rep_name} ({r.rep.label})", "REP votes": show(votes(r.rep_votes)),
                "leader": f"{short_name(leader.name)} +{pct(abs(r.margin))}" if leader else show("tied"),
                "reporting": show(f"{r.pct_reporting:.1f}%"),
                "DEM win": show(pct(r.dem_win_prob)), "REP win": show(pct(r.rep_win_prob)),
                "polls close": self.ctx.closing_label(r.state_code),
                "tags": ", ".join(self.ctx.tags.for_race(r.race_id)),
            })
        return out

    def render(self, selected: Optional[str]) -> None:
        """Draw the table."""
        right = lambda: st.column_config.TextColumn(alignment="right")
        st.dataframe(pd.DataFrame(self.rows(selected)), hide_index=True, width="stretch", height=320,
                     column_config={c: right() for c in ("DEM votes", "REP votes", "reporting", "DEM win", "REP win")})


class RaceCards:
    """One compact card per race in poll-closing order, with the official state cross-check."""

    def __init__(self, ctx: DashboardContext):
        self.ctx = ctx

    def ordered(self) -> List[ForecastResult]:
        """Races in poll-closing order, tagged races first at each time."""
        ctx = self.ctx
        far_future = datetime.max.replace(tzinfo=timezone.utc)
        closes = lambda r: ctx.closings[r.state_code].first if r.state_code in ctx.closings else far_future
        return sorted(ctx.results, key=lambda r: (closes(r), not ctx.tags.for_race(r.race_id), r.state))

    def render(self) -> None:
        """Draw the cards inside a collapsed expander."""
        ctx = self.ctx
        colors = {t: BADGE_COLORS[i % len(BADGE_COLORS)] for i, t in enumerate(ctx.tags.all_tags)}
        with st.expander("Race cards, in poll-closing order"):
            for res in self.ordered():
                c1, c2, c3 = st.columns([3, 3, 4])
                badges = " ".join(f":{colors[t]}-badge[{t}]" for t in ctx.tags.for_race(res.race_id))
                c1.markdown(f"**{res.state}** (`{res.race_id}`) {badges}")
                c1.caption(f"{res.dem_name} ({res.dem.label}) {votes(res.dem_votes)} vs "
                           f"{res.rep_name} ({res.rep.label}) {votes(res.rep_votes)}")
                line = official_line(res, ctx.officials.get(res.state_code))
                if line:
                    c1.caption(line)
                c2.write(f"Reporting: **{res.pct_reporting:.1f}%**")
                if res.state_code in ctx.closings:
                    c2.caption(f"Polls close {ctx.closing_label(res.state_code)}")
                if not res.has_votes:
                    c3.caption("No votes counted yet")
                    continue
                c3.progress(res.dem_win_prob, text=f"{res.dem.label}: {pct(res.dem_win_prob)} | "
                                                   f"{res.rep.label}: {pct(res.rep_win_prob)}")


class EarlyVotePanel:
    """Early ballots per race, by voters' party registration, in a collapsed expander."""

    def __init__(self, ctx: DashboardContext):
        self.ctx = ctx

    def rows(self) -> List[dict]:
        """One row per race, tagged races first."""
        ctx, out = self.ctx, []
        for res in sorted(ctx.results, key=lambda r: (not ctx.tags.for_race(r.race_id), r.state)):
            ev = early_vote_row(ctx.early_vote, res.state_code)
            row = {"race": f"{res.state} ({res.race_id})"}
            if ev:
                row.update({cat: votes(n) for cat, n in ev.by_category.items()})
            row["total"] = votes(ev.total) if ev else "no data"
            show = lambda v: pct(v, 0) if v is not None else ""
            row["DEM"] = show(ev.dem_share) if ev else ""
            row["REP"] = show(ev.rep_share) if ev else ""
            row["other / unaffiliated"] = show(ev.other_share) if ev else ""
            row["tags"] = ", ".join(ctx.tags.for_race(res.race_id))
            out.append(row)
        return out

    def render(self) -> None:
        """Draw the table, if there is early-vote data."""
        ev = self.ctx.early_vote
        if not ev:
            return
        with st.expander(f"Early vote: ballots already cast (as of {ev.snapshot_date})"):
            st.caption("Ballots cast before election day, split by voters' party registration where the state "
                       "records it. This is turnout, not votes for candidates. Source: civicAPI.")
            st.dataframe(pd.DataFrame(self.rows()), hide_index=True, width="stretch")


class RawTotals:
    """Every field of every forecast, for checking the numbers."""

    def __init__(self, ctx: DashboardContext):
        self.ctx = ctx

    def rows(self) -> List[dict]:
        """One row per race (win odds blank before votes: the 0.5 prior isn't a forecast)."""
        out = []
        for r in self.ctx.results:
            row = {**r.__dict__, "polls_close": self.ctx.closing_label(r.state_code),
                   "projected_winner": r.projected_winner or "", "tags": ", ".join(self.ctx.tags.for_race(r.race_id))}
            if not r.has_votes:
                row.update(dem_win_prob="", rep_win_prob="")
            out.append(row)
        return out

    def render(self) -> None:
        """Draw the table in a collapsed expander."""
        with st.expander("Raw totals"):
            st.dataframe(pd.DataFrame(self.rows()), width="stretch")


class DashboardView:
    """Composes the sections for one refresh."""

    def __init__(self, ctx: DashboardContext):
        self.ctx = ctx

    def render(self) -> None:
        """Draw every section; only the top pane when there are no results yet."""
        TopPane(self.ctx).render()
        if not self.ctx.results:
            return
        panel = MapPanel(self.ctx)
        panel.render()
        RaceTable(self.ctx).render(st.session_state.get(SELECTED_RACE))
        RaceCards(self.ctx).render()
        EarlyVotePanel(self.ctx).render()
        RawTotals(self.ctx).render()
