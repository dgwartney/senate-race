"""Preferred results source per state.

The main provider (civicAPI) returns every state's race in one response; it is split here
per state, and each state takes its totals from its preferred source. A state whose
preference is ``"official"`` uses its own election office's feed (:mod:`src.officials`)
whenever that feed has votes for both sides of the race, and falls back to the main
provider otherwise. States not listed in the preferences file use the main provider.
"""
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional

from src.geo import race_state_code
from src.models import Candidate, RaceData
from src.officials import OfficialResult, votes_for

OFFICIAL = "official"
UNFINISHED_MARGIN = 1.03
"""Expected turnout is never estimated below counted votes times this.

The state feeds publish no expected vote, so without this margin a count that overtook
the configured estimate would show 100% reporting and project a winner from a guess.
"""


class SourceConfigError(Exception):
    """The source preferences file is missing or malformed."""


@dataclass(frozen=True)
class StatePreference:
    """Where one state's totals come from.

    Attributes:
        source: ``"official"`` for the state's own feed; anything else means the main provider.
        expected_turnout: Two-side votes expected when counting finishes, used for percent
            reporting and the odds when the state's feed supplies the totals.
    """

    source: str
    expected_turnout: int = 0


def load_source_preferences(path: Path) -> Dict[str, StatePreference]:
    """Read ``[ST]`` tables (``source``, ``expected_turnout``) from a TOML file; none if it is absent.

    Raises:
        SourceConfigError: The file exists but can't be parsed.
    """
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text())
        return {state.upper(): StatePreference(str(entry["source"]), int(entry.get("expected_turnout", 0)))
                for state, entry in data.items()}
    except (tomllib.TOMLDecodeError, KeyError, TypeError, ValueError, AttributeError) as e:
        raise SourceConfigError(f"{path.name}: {e}") from e


def apply_preferred_sources(races: List[RaceData], officials: Dict[str, OfficialResult],
                            preferences: Dict[str, StatePreference]) -> List[RaceData]:
    """Each race with its totals from its state's preferred source, in the order given."""
    return [_preferred(race, officials, preferences.get(race_state_code(race.race_id))) for race in races]


def _preferred(race: RaceData, officials: Dict[str, OfficialResult],
               preference: Optional[StatePreference]) -> RaceData:
    if preference is None or preference.source != OFFICIAL:
        return race
    result = officials.get(race_state_code(race.race_id))
    if result is None or not result.ok:
        return race
    dem = votes_for(result.count, race.dem_candidate.name)
    rep = votes_for(result.count, race.rep_candidate.name)
    if dem is None or rep is None or dem + rep == 0:
        return race  # names didn't match, or the feed has nothing yet: keep the main provider's numbers
    counted = dem + rep
    main_estimate = race.expected_total_turnout if race.total_counted_votes else 0
    expected = max(preference.expected_turnout, main_estimate, round(counted * UNFINISHED_MARGIN))
    return replace(race, dem_candidate=Candidate(race.dem_candidate.name, race.dem_candidate.party, dem),
                   rep_candidate=Candidate(race.rep_candidate.name, race.rep_candidate.party, rep),
                   expected_total_turnout=expected, source=result.count.source)
