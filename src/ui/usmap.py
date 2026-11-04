"""Plotly map of the Senate races (Alaska and Hawaii as insets) and its hover cards."""
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional

import plotly.graph_objects as go

from src.geo import US_STATES
from src.models import ForecastResult, Side
from src.tags import RaceTags
from src.ui.format import esc, lead_text, pct, short_name
from src.ui.theme import MUTED, NO_RACE_COLOR, NO_VOTES_COLOR, SELECTED_OUTLINE, TRACK, WIN_PROB_SCALE, party_color

BAR_WIDTH = 14
"""Characters in the vote-share bar of a hover card."""
NAME_WIDTH = 18
"""Characters reserved for "■ Surname (PTY)" in a hover card."""


def _span(text: str, color: str, bold: bool = False) -> str:
    """Wrap already-escaped text in a coloured (optionally bold) span."""
    text = f"<b>{text}</b>" if bold else text
    return f"<span style='color:{color}'>{text}</span>"


def leader_color(res: ForecastResult) -> str:
    """Party colour of whoever leads the count; grey before votes or when level."""
    return party_color(res.leader.party) if res.leader else MUTED


@dataclass(frozen=True)
class HoverCard:
    """The summary shown when hovering a state: a small fixed-width table for one race.

    Plotly hover labels accept a subset of HTML (``<b>``, ``<br>``, ``<span style>``) but not
    tables, so columns are aligned with spaces in a monospace font.
    """

    result: ForecastResult
    closing_label: str = ""
    tags: tuple = ()

    def _side_row(self, side: Side) -> str:
        res = self.result
        color = party_color(side.party)
        leads = res.leader == side
        who = f"{short_name(side.name)} ({side.label})"
        who = who if len(who) <= NAME_WIDTH - 2 else who[:NAME_WIDTH - 3] + "…"
        share = side.votes / res.total_votes if res.has_votes else 0.0
        filled = round(share * BAR_WIDTH)
        bar = _span("█" * filled, color) + _span("░" * (BAR_WIDTH - filled), TRACK)
        share_text = pct(share) if res.has_votes else "-"
        win_text = pct(side.win_prob, 0) if res.has_votes else "-"
        # Pad by visible width before escaping, so names with & or < don't shift the columns.
        return (f"{_span(esc(f'■ {who:<{NAME_WIDTH - 2}}'), color, bold=leads)} {side.votes:>11,} "
                f"{share_text:>6}  {bar} " + _span(f"{win_text:>4}", color, bold=leads))

    def _status(self) -> str:
        res = self.result
        if res.projected_winner:
            return _span(f"✔ Projected: {esc(res.projected_winner)}", leader_color(res), bold=True)
        if res.leader:
            return _span(esc(lead_text(res)), leader_color(res), bold=True)
        return _span("Tied" if res.has_votes else "No votes counted yet", MUTED, bold=True)

    def html(self) -> str:
        """The card as Plotly hover HTML."""
        res = self.result
        title = (f"<span style='font-size:15px'><b>{esc(res.state)}</b></span>  "
                 + _span(esc(" · ".join([res.race_id, *self.tags])), MUTED))
        header = _span(f"{'':<{NAME_WIDTH}} {'Votes':>11} {'Share':>6}  {'':<{BAR_WIDTH}} {'Win':>4}", MUTED)
        footer = f"{res.pct_reporting:.1f}% reporting"
        if self.closing_label:
            footer += f" · polls close {self.closing_label}"
        rows = [title, header, self._side_row(res.dem), self._side_row(res.rep), self._status(),
                _span(esc(footer), MUTED), _span("Click for details", MUTED)]
        return "<br>".join(rows)


class UsMapBuilder:
    """Builds the choropleth: every state drawn once, coloured by the state of its race.

    * Counting: red-white-blue by dem-side win probability.
    * Race on the ballot, no votes yet: tan.
    * No Senate race this year: grey.

    Args:
        tags: Race tags, shown in hover cards.
        closing_labels: State code -> formatted poll-closing time.
        height: Figure height in pixels.
    """

    def __init__(self, tags: RaceTags, closing_labels: Dict[str, str], height: int = 620):
        self.tags = tags
        self.closing_labels = closing_labels
        self.height = height

    def _hover(self, races: List[ForecastResult]) -> str:
        return "<br><br>".join(HoverCard(r, self.closing_labels.get(r.state_code, ""),
                                         tuple(self.tags.for_race(r.race_id))).html() for r in races)

    @staticmethod
    def _outline(states: List[str], selected: Optional[str]) -> dict:
        return dict(color=[SELECTED_OUTLINE if s == selected else "white" for s in states],
                    width=[3 if s == selected else 0.8 for s in states])

    def build(self, results: List[ForecastResult], selected_state: Optional[str] = None) -> go.Figure:
        """Return the figure.

        Args:
            results: One entry per race; a state with two races is coloured by the first.
            selected_state: Postal code to outline (the race whose details are open).
        """
        by_state: Dict[str, List[ForecastResult]] = defaultdict(list)
        for res in results:
            by_state[res.state_code].append(res)
        counting = [s for s, rs in by_state.items() if any(r.has_votes for r in rs)]
        waiting = [s for s in by_state if s not in counting]
        no_race = [s for s in US_STATES if s not in by_state]

        def flat(states: List[str], color: str, text: List[str], name: str) -> go.Choropleth:
            return go.Choropleth(locations=states, z=[0] * len(states), locationmode="USA-states",
                                 colorscale=[[0, color], [1, color]], showscale=False, name=name,
                                 text=text, hovertemplate="%{text}<extra></extra>",
                                 hoverlabel=dict(bordercolor=MUTED), marker_line=self._outline(states, selected_state))

        fig = go.Figure()
        fig.add_trace(flat(no_race, NO_RACE_COLOR,
                           [f"<span style='font-size:15px'><b>{esc(US_STATES[s])}</b></span><br>"
                            + _span("No Senate race this year", MUTED) for s in no_race], "No race"))
        fig.add_trace(flat(waiting, NO_VOTES_COLOR, [self._hover(by_state[s]) for s in waiting], "No votes yet"))
        fig.add_trace(go.Choropleth(
            locations=counting, locationmode="USA-states",
            z=[by_state[s][0].dem_win_prob for s in counting], zmin=0, zmax=1, colorscale=WIN_PROB_SCALE,
            text=[self._hover(by_state[s]) for s in counting], hovertemplate="%{text}<extra></extra>",
            name="Counting", hoverlabel=dict(bordercolor=[leader_color(by_state[s][0]) for s in counting]),
            marker_line=self._outline(counting, selected_state),
            # Horizontal legend under the map, so the map gets the column's full width.
            colorbar=dict(title=dict(text="Win probability", side="top"), orientation="h",
                          x=0.5, xanchor="center", y=0.0, yanchor="top", len=0.5, thickness=8,
                          tickvals=[0, 0.25, 0.5, 0.75, 1],
                          ticktext=["REP 100%", "REP 75%", "50 / 50", "DEM 75%", "DEM 100%"])))
        # The geo domain fills the figure; Plotly keeps the projection's aspect within it.
        fig.update_layout(geo=dict(scope="usa", projection_type="albers usa", showlakes=False,
                                   bgcolor="rgba(0,0,0,0)", domain=dict(x=[0, 1], y=[0, 1]),
                                   fitbounds="locations"),  # zoom to the states, not Plotly's padded frame
                          hoverlabel=dict(font_family="Menlo, Consolas, monospace", font_size=12,
                                          font_color="#222222", bgcolor="rgba(255,255,255,0.97)", align="left"),
                          margin=dict(l=0, r=0, t=0, b=40), height=self.height, dragmode=False,
                          paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
        return fig


def clicked_state(event: Optional[dict]) -> Optional[str]:
    """The state code a viewer clicked, from a Streamlit Plotly selection event, if any.

    Clicking a selected state again clears Plotly's selection; that returns None, and the
    caller keeps the current choice.
    """
    try:
        points = event["selection"]["points"]
    except (KeyError, TypeError):
        return None
    codes = [p["location"] for p in points if p.get("location")]
    return codes[-1] if codes else None
