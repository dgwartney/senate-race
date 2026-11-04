"""Colours and page CSS: the dashboard's whole visual vocabulary in one place."""
from src.models import party_label

PARTY_COLORS = {"DEM": "#2166ac", "REP": "#b2182b", "IND": "#6a3d9a", "LIB": "#b8860b", "GRN": "#2e7d32"}
"""Party label -> colour; parties not listed use :data:`OTHER_PARTY`."""
OTHER_PARTY = "#444444"
MUTED = "#6b6b6b"
TRACK = "#e3e3e3"
"""Unfilled part of a bar."""

WIN_PROB_SCALE = [[0.0, "#b2182b"], [0.25, "#ef8a62"], [0.5, "#f7f7f7"], [0.75, "#67a9cf"], [1.0, "#2166ac"]]
"""Map colours by dem-side win probability: red (REP certain) through white (even) to blue."""
NO_VOTES_COLOR = "#d8cfa8"
"""Map colour for a race on the ballot with nothing counted yet."""
NO_RACE_COLOR = "#ececec"
"""Map colour for a state without a Senate race this year."""
SELECTED_OUTLINE = "#111111"
"""Outline of the state whose details are open."""

BADGE_COLORS = ["orange", "blue", "violet", "green", "red", "gray"]
"""Streamlit badge colours, assigned to tags in alphabetical order."""


def party_color(party: str) -> str:
    """Colour for a party as the source spells it ("Democratic") or abbreviates it ("DEM")."""
    return PARTY_COLORS.get(party_label(party), PARTY_COLORS.get(party, OTHER_PARTY))


PAGE_CSS = """<style>
.block-container {padding-top: 3.75rem; padding-bottom: 1rem;}
/* Sticky must sit on the pane's wrapper: the pane's own parent is exactly its height. */
[data-testid="stLayoutWrapper"]:has(> .st-key-toppane) {position: sticky; top: 3.75rem; z-index: 990;}
.st-key-toppane {background-color: white; padding: 0.35rem 0 0.4rem; border-bottom: 1px solid #e6e6e6;
    box-shadow: 0 6px 8px -8px rgba(0,0,0,0.25); gap: 0.2rem;}
.st-key-toppane [data-testid="stMetric"] {padding: 0;}
.st-key-toppane [data-testid="stMetricValue"] {font-size: 1.35rem; line-height: 1.3;}
.st-key-toppane [data-testid="stMetricLabel"] p {font-size: 0.78rem;}
.st-key-toppane [data-testid="stAlert"] {padding: 0.35rem 0.75rem;}
.top-title {display: flex; gap: 0.9rem; align-items: baseline; flex-wrap: wrap;}
.top-title b {font-size: 1.35rem;}
.top-title span {font-size: 0.8rem; color: #6b6b6b;}
[data-testid="stMain"] h3 {padding-top: 0.6rem; padding-bottom: 0.1rem;}
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] {gap: 0.6rem;}
.race-detail {border: 1px solid #e6e6e6; border-radius: 8px; padding: 0.7rem 0.9rem; line-height: 1.35;}
.race-detail .rd-title {font-size: 1.25rem; font-weight: 700;}
.race-detail .rd-sub {font-size: 0.8rem; color: #6b6b6b;}
.race-detail .rd-status {font-weight: 700; margin: 0.45rem 0 0.35rem;}
.race-detail .rd-side {margin: 0.35rem 0;}
.race-detail .rd-row {display: flex; justify-content: space-between; gap: 0.5rem; font-size: 0.92rem;}
.race-detail .rd-num {font-variant-numeric: tabular-nums; white-space: nowrap;}
.race-detail .rd-bar {height: 8px; border-radius: 4px; background: #e3e3e3; overflow: hidden; margin-top: 2px;}
.race-detail .rd-bar > div {height: 100%;}
.race-detail .rd-odds {display: flex; height: 18px; border-radius: 4px; overflow: hidden; font-size: 0.72rem;
    color: white; font-weight: 600; margin-top: 0.2rem;}
.race-detail .rd-odds > div {display: flex; align-items: center; padding: 0 0.35rem; white-space: nowrap;}
.race-detail .rd-meta {font-size: 0.82rem; color: #555; margin-top: 0.45rem;}
/* Phones: Streamlit stacks columns below 640px, which would make the pinned pane fill the screen.
   Unpin it, lay the six numbers out three to a row, and drop the "needs N" chips. */
@media (max-width: 640px) {
  [data-testid="stLayoutWrapper"]:has(> .st-key-toppane) {position: static;}
  .st-key-toppane [data-testid="stHorizontalBlock"] {flex-direction: row; flex-wrap: wrap; gap: 0.4rem 0.6rem;}
  .st-key-toppane [data-testid="stColumn"] {flex: 1 1 30% !important; min-width: 30% !important; width: 30% !important;}
  .st-key-toppane [data-testid="stMetricValue"] {font-size: 1.05rem;}
  .st-key-toppane [data-testid="stMetricDelta"] {display: none;}
  .block-container {padding-left: 0.75rem; padding-right: 0.75rem;}
  /* The map figure is 620px tall but, at phone width, the drawn map is only about half the
     screen width tall: pull the blank bands above and below it in, scaled to the width. */
  .st-key-us_map {margin-top: calc(min(0px, (100vw - 24px) * 0.25 - 270px));
                  margin-bottom: calc(min(0px, (100vw - 24px) * 0.25 - 95px));}
}
</style>"""
