"""Builds the configured :class:`ElectionDataProvider` from environment variables."""
import os
import tomllib
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple

from src.providers.base import ElectionDataProvider, ProviderError
from src.providers.civicapi import CivicApiProvider
from src.providers.json_feed import JsonFeedProvider
from src.providers.mock import MockProvider

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def _load_matchups(path: Path) -> Dict[str, Tuple[str, str]]:
    if not path.exists():
        return {}
    try:
        matchups = tomllib.loads(path.read_text()).get("matchups", {})
        for race_id, names in matchups.items():
            if not (isinstance(names, list) and len(names) == 2):
                raise ValueError(f"{race_id} must list exactly two names: [challenger, Republican]")
        return {race_id: (names[0], names[1]) for race_id, names in matchups.items()}
    except (tomllib.TOMLDecodeError, ValueError) as e:
        raise ProviderError(f"{path.name}: {e}") from e

def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")

def _mock(env: Mapping[str, str]) -> ElectionDataProvider:
    return MockProvider()

def _json_feed(env: Mapping[str, str]) -> ElectionDataProvider:
    url = env.get("API_ENDPOINT", "")
    if not url:
        raise ProviderError("ELECTION_PROVIDER=json_feed requires API_ENDPOINT")
    return JsonFeedProvider(url, env.get("API_KEY", ""))

def _civicapi(env: Mapping[str, str]) -> ElectionDataProvider:
    return CivicApiProvider(
        election_date=env.get("CIVICAPI_ELECTION_DATE", "2026-11-03"),
        race_type=env.get("CIVICAPI_RACE_TYPE", "US Senate"),
        test_data=_truthy(env.get("CIVICAPI_TEST_DATA", "")),
        fallback_turnout=int(env.get("CIVICAPI_FALLBACK_TURNOUT", "1000000")),
        matchups=_load_matchups(PROJECT_ROOT / env.get("CIVICAPI_MATCHUPS_FILE", "candidates.toml"))
    )

# Register new providers (e.g. a state results-page scraper) here.
PROVIDERS: Dict[str, Callable[[Mapping[str, str]], ElectionDataProvider]] = {
    "mock": _mock,
    "json_feed": _json_feed,
    "civicapi": _civicapi,
}

def create_provider(env: Optional[Mapping[str, str]] = None) -> ElectionDataProvider:
    """Build the provider named by ELECTION_PROVIDER.

    Without ELECTION_PROVIDER, keeps the original behaviour: json_feed when
    API_ENDPOINT is set, otherwise mock.
    """
    env = os.environ if env is None else env
    name = env.get("ELECTION_PROVIDER", "").strip().lower()
    if not name:
        name = "json_feed" if env.get("API_ENDPOINT") else "mock"
    if name not in PROVIDERS:
        raise ProviderError(f"Unknown ELECTION_PROVIDER '{name}'. Choose one of: {', '.join(PROVIDERS)}")
    return PROVIDERS[name](env)
