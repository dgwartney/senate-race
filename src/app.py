"""Streamlit entry point: ``streamlit run src/app.py``.

Pages never fetch from the network. A background :class:`~src.poller.Poller` (one per
server process) writes results to a SQLite :class:`~src.store.SnapshotStore`; each page
reads the latest snapshot on a timer and renders it.
"""
import logging
import os
import sys
from dataclasses import dataclass
from typing import Dict

# `streamlit run src/app.py` puts src/ on sys.path, not the project root that `src.*` imports need.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st  # noqa: E402
import truststore  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from src.config import Settings  # noqa: E402
from src.engine import ProjectionEngine  # noqa: E402
from src.live import LiveDataReader, MarginHistory  # noqa: E402
from src.poller import Poller, default_jobs  # noqa: E402
from src.providers import ProviderError, create_provider  # noqa: E402
from src.schedule import PollClosing, load_poll_closings  # noqa: E402
from src.sources import load_source_preferences  # noqa: E402
from src.store import SnapshotStore  # noqa: E402
from src.tags import RaceTags, TagConfigError, load_race_tags  # noqa: E402
from src.ui.components import DashboardContext, DashboardView, apply_page_style  # noqa: E402

log = logging.getLogger(__name__)
_bootstrapped = False


def bootstrap() -> None:
    """Process-wide setup, run once per process.

    Trusts the OS certificate store (needed behind TLS-inspecting proxies such as Zscaler),
    loads ``.env`` and configures logging.
    """
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    truststore.inject_into_ssl()
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@dataclass(frozen=True)
class Services:
    """Long-lived objects shared by every viewer of this server process."""

    settings: Settings
    store: SnapshotStore
    poller: Poller
    reader: LiveDataReader
    history: MarginHistory
    attribution: str


@st.cache_resource
def get_services() -> Services:
    """Create the store and start the poller once per server process.

    Raises:
        ProviderError, SourceConfigError, ValueError: The configuration is invalid.
    """
    settings = Settings.from_env()
    store = SnapshotStore(settings.snapshot_db)
    provider = create_provider(settings.env)
    poller = Poller(store, default_jobs(settings.env, settings.races_poll_seconds,
                                        settings.officials_poll_seconds, settings.early_vote_poll_seconds))
    poller.ensure_running()
    reader = LiveDataReader(store, settings.races_poll_seconds, provider.name,
                            load_source_preferences(settings.sources_file))
    return Services(settings, store, poller, reader, MarginHistory(store), provider.attribution or "")


class ElectionApp:
    """One page view: static controls, then a fragment that re-reads the store on a timer.

    Args:
        services: Shared store, poller and settings.
        tags: Race tags and the control tally definition.
        closings: State code -> poll-closing times.
    """

    def __init__(self, services: Services, tags: RaceTags, closings: Dict[str, PollClosing]):
        self.services = services
        self.tags = tags
        self.closings = closings
        self.engine = ProjectionEngine()

    def run(self) -> None:
        """Render the page; the results section then refreshes itself on a timer."""
        apply_page_style()
        # A timed fragment, unlike sleep-then-rerun, keeps clicks responsive between refreshes.
        st.fragment(run_every=self.services.settings.refresh_seconds)(self._render_results)()

    def _render_results(self) -> None:
        self.services.poller.ensure_running()
        try:
            data = self.services.reader.read()
            ctx = DashboardContext(self.engine.process_all_races(data.races), self.tags, self.closings,
                                   data.officials, data.early_vote, data.notices, data.races_checked_at,
                                   self.services.attribution, self.services.history.series)
            DashboardView(ctx).render()
        except Exception:  # noqa: BLE001 - one bad render must not take the page down
            log.exception("render failed")
            st.error("Something went wrong drawing the results. The page will try again on the next refresh.")


def _load_tags(settings: Settings) -> RaceTags:
    try:
        return load_race_tags(settings.tags_file)
    except TagConfigError as e:
        st.warning(f"Ignoring race tags: {e}")
        return RaceTags()


def _load_closings(settings: Settings) -> Dict[str, PollClosing]:
    try:
        return load_poll_closings(settings.closings_file)
    except ValueError as e:
        st.warning(f"Ignoring poll-closing times: {e}")
        return {}


def main() -> None:
    """Streamlit runs this on every page load."""
    st.set_page_config(page_title="Senate Dashboard", layout="wide")
    bootstrap()
    try:
        services = get_services()
    except (ProviderError, ValueError) as e:
        st.error(f"Configuration error: {e}")
        return
    settings = services.settings
    ElectionApp(services, _load_tags(settings), _load_closings(settings)).run()


if __name__ == "__main__":
    main()
