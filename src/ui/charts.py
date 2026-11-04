"""Small charts for the race details panel."""
from typing import List

import plotly.graph_objects as go

from src.live import MarginPoint
from src.ui.format import EASTERN
from src.ui.theme import MUTED, TRACK


def margin_figure(points: List[MarginPoint], dem_label: str, rep_label: str, dem_color: str,
                  rep_color: str, height: int = 150) -> go.Figure:
    """Line chart of a race's lead over the night, in percentage points.

    Above zero the dem side leads; below, the rep side. The area is filled in the leading
    side's colour so the swing is readable at a glance.

    Args:
        points: Margin history, oldest first.
        dem_label: Dem-side party label, e.g. ``"DEM"``.
        rep_label: Rep-side party label.
        dem_color: Dem-side party colour.
        rep_color: Rep-side party colour.
        height: Figure height in pixels.
    """
    times = [p.at.astimezone(EASTERN) for p in points]
    margins = [p.margin * 100 for p in points]
    hover = [f"{t:%-I:%M %p} ET<br>{(dem_label if m >= 0 else rep_label)} +{abs(m):.1f} pts"
             f"<br>{p.pct_reporting:.0f}% reporting" for t, m, p in zip(times, margins, points, strict=True)]
    fig = go.Figure()
    sides = ((dem_label, dem_color, lambda m: max(m, 0)), (rep_label, rep_color, lambda m: min(m, 0)))
    for label, color, keep in sides:
        fig.add_trace(go.Scatter(x=times, y=[keep(m) for m in margins], mode="lines", line=dict(width=0),
                                 fill="tozeroy", fillcolor=color, opacity=0.35, hoverinfo="skip", name=label))
    fig.add_trace(go.Scatter(x=times, y=margins, mode="lines+markers", line=dict(color="#333333", width=1.5),
                             marker=dict(size=3), text=hover, hovertemplate="%{text}<extra></extra>"))
    bound = max(5.0, max(abs(m) for m in margins) * 1.15)
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=4, b=0), showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(showgrid=False, tickformat="%-I:%M", tickfont=dict(size=10, color=MUTED)),
                      yaxis=dict(range=[-bound, bound], zeroline=True, zerolinecolor=TRACK, gridcolor=TRACK,
                                 ticksuffix=" pts", tickfont=dict(size=10, color=MUTED)))
    return fig
