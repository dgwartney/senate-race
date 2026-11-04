"""Whole-page smoke tests with Streamlit's AppTest, the mock provider and a temporary store."""
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.models import Candidate, RaceData
from src.store import SnapshotStore

APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")
RACES = [RaceData("TX-SEN", "Texas", Candidate("Jane Doe", "Democratic", 600), Candidate("John Roe", "Republican", 400),
                  2000, 0.5, 0.035).to_dict()]


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "snap.db"
    monkeypatch.setenv("SNAPSHOT_DB", str(path))
    monkeypatch.setenv("ELECTION_PROVIDER", "mock")
    monkeypatch.setenv("OFFICIAL_FEEDS", "")
    # Long poll intervals keep the background poller from overwriting the seeded data mid-test.
    for name in ("POLL_RACES_SECONDS", "POLL_OFFICIALS_SECONDS", "POLL_EARLY_VOTE_SECONDS"):
        monkeypatch.setenv(name, "3600")
    st.cache_resource.clear()  # each test gets fresh services pointing at its own database
    yield SnapshotStore(path)
    st.cache_resource.clear()


def run():
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_renders_seeded_results_with_map(db, monkeypatch):
    # The mock provider must not replace the seeded race before we look.
    monkeypatch.setattr("src.providers.mock.MockProvider.get_live_races", lambda self: [RaceData.from_dict(RACES[0])])
    db.save_snapshot("races", RACES)
    db.record_attempt("races", True)
    at = run()
    text = " ".join(m.value for m in at.markdown)
    assert "Senate Live Tracker" in text and "data as of" in text
    assert at.get("plotly_chart"), "map not rendered"
    assert not at.error


def test_failed_update_shows_warning_and_keeps_results(db, monkeypatch):
    monkeypatch.setattr("src.providers.mock.MockProvider.get_live_races",
                        lambda self: (_ for _ in ()).throw(RuntimeError("down")))
    db.save_snapshot("races", RACES)
    db.record_attempt("races", True)
    db.record_attempt("races", False, "ReadTimeout: slow")
    at = run()
    assert any("failed" in w.value for w in at.warning)
    assert any("Texas" in m.value or "TX-SEN" in m.value for m in at.markdown)


def test_details_follow_selected_race(db, monkeypatch):
    monkeypatch.setattr("src.providers.mock.MockProvider.get_live_races", lambda self: [RaceData.from_dict(RACES[0])])
    db.save_snapshot("races", RACES)
    db.record_attempt("races", True)
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["selected_race"] = "TX-SEN"
    at.run()
    assert not at.exception, at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "rd-title'>Texas<" in html and "Projected winner: Jane Doe (DEM)" in html
    assert at.selectbox[0].value == "TX-SEN"


def test_empty_store_waits(db, monkeypatch):
    monkeypatch.setattr("src.providers.mock.MockProvider.get_live_races",
                        lambda self: (_ for _ in ()).throw(RuntimeError("down")))
    at = run()
    assert any("Waiting" in i.value for i in at.info) or any("Could not load" in e.value for e in at.error)
