"""Poll-closing times per state, read from ``poll_closing.toml``."""
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Dict, NamedTuple


class PollClosing(NamedTuple):
    """When a state's polls close: most of the state, and the last part of it."""

    first: datetime  # when most polls close
    last: datetime   # when the last polls close (later where a state spans two time zones)

def load_poll_closings(path: Path) -> Dict[str, PollClosing]:
    """Read poll_closing.toml: state code -> PollClosing. A missing file means no times."""
    if not path.exists():
        return {}
    try:
        closings = {}
        for state, times in tomllib.loads(path.read_text()).get("closing", {}).items():
            first, last = times
            if not (isinstance(first, datetime) and isinstance(last, datetime) and first.tzinfo and last.tzinfo):
                raise ValueError(f"{state} needs two datetimes with a UTC offset")
            closings[state.upper()] = PollClosing(first, last)
        return closings
    except (tomllib.TOMLDecodeError, TypeError, ValueError) as e:
        raise ValueError(f"{path.name}: {e}") from e
