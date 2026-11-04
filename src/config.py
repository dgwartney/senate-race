"""Application settings, read once from the environment.

Every environment variable the app understands is listed here so configuration is not
scattered across modules. Provider-specific variables (``CIVICAPI_*``, ``API_ENDPOINT``)
are still interpreted by :mod:`src.providers.factory`, which receives the same mapping.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    """Read a positive integer variable, raising ValueError with the variable's name when invalid."""
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from e
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the dashboard and its background poller.

    Attributes:
        refresh_seconds: How often each open page re-reads the snapshot store.
        races_poll_seconds: How often the poller fetches live race results.
        officials_poll_seconds: How often the poller fetches official state feeds.
        early_vote_poll_seconds: How often the poller fetches early-vote turnout.
        snapshot_db: SQLite file the poller writes and the pages read.
        tags_file: TOML file of race tags (see README "Tagging races").
        closings_file: TOML file of poll-closing times.
        sources_file: TOML file of each state's preferred results source.
        env: The raw environment mapping, passed on to the provider factory and feeds.
    """

    refresh_seconds: int = 30
    races_poll_seconds: int = 30
    officials_poll_seconds: int = 60
    early_vote_poll_seconds: int = 3600
    snapshot_db: Path = PROJECT_ROOT / "data" / "snapshots.db"
    tags_file: Path = PROJECT_ROOT / "race_tags.toml"
    closings_file: Path = PROJECT_ROOT / "poll_closing.toml"
    sources_file: Path = PROJECT_ROOT / "sources.toml"
    env: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        """Build settings from environment variables (``os.environ`` by default).

        Raises:
            ValueError: A numeric variable is not a positive whole number.
        """
        env = dict(os.environ if env is None else env)
        resolve = lambda value: Path(value) if Path(value).is_absolute() else PROJECT_ROOT / value
        return cls(
            refresh_seconds=_int(env, "REFRESH_INTERVAL_SECONDS", 30),
            races_poll_seconds=_int(env, "POLL_RACES_SECONDS", 30),
            officials_poll_seconds=_int(env, "POLL_OFFICIALS_SECONDS", 60),
            early_vote_poll_seconds=_int(env, "POLL_EARLY_VOTE_SECONDS", 3600),
            snapshot_db=resolve(env.get("SNAPSHOT_DB", "data/snapshots.db")),
            tags_file=resolve(env.get("RACE_TAGS_FILE", "race_tags.toml")),
            closings_file=resolve(env.get("POLL_CLOSING_FILE", "poll_closing.toml")),
            sources_file=resolve(env.get("SOURCES_FILE", "sources.toml")),
            env=env,
        )
