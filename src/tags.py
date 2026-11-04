"""Race tags (e.g. "toss-up") and the control tally, read from ``race_tags.toml``."""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


class TagConfigError(Exception):
    """``race_tags.toml`` could not be read or has the wrong shape."""

@dataclass(frozen=True)
class ControlTally:
    """Which tag the top pane tallies, and how many of those races each party needs."""

    tag: str
    dem_needed: int
    rep_needed: int

@dataclass(frozen=True)
class RaceTags:
    """Race ID -> tags, plus the optional control tally."""

    by_race: Dict[str, List[str]] = field(default_factory=dict)
    control: Optional[ControlTally] = None

    @property
    def all_tags(self) -> List[str]:
        """Every tag in use, sorted."""
        return sorted({t for tags in self.by_race.values() for t in tags})

    def for_race(self, race_id: str) -> List[str]:
        """Tags of one race (empty if untagged)."""
        return self.by_race.get(race_id, [])

def load_race_tags(path: Path) -> RaceTags:
    """Read a race_tags.toml file. A missing file means no tags."""
    if not path.exists():
        return RaceTags()
    try:
        data = tomllib.loads(path.read_text())
        by_race: Dict[str, List[str]] = {}
        for tag, race_ids in data.get("tags", {}).items():
            if not isinstance(race_ids, list):
                raise TagConfigError(f"tag '{tag}' must list race IDs, e.g. [\"GA-SEN\"]")
            for race_id in race_ids:
                by_race.setdefault(str(race_id).strip().upper(), []).append(tag)
        control = None
        if "control" in data:
            c = data["control"]
            control = ControlTally(tag=c["tag"], dem_needed=int(c["dem_needed"]), rep_needed=int(c["rep_needed"]))
        return RaceTags(by_race=by_race, control=control)
    except (tomllib.TOMLDecodeError, KeyError, TypeError, ValueError) as e:
        raise TagConfigError(f"{path.name}: {e}") from e
