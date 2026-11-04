from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.schedule import load_poll_closings
from src.ui.format import poll_close_label as _poll_close_label

SHIPPED = Path(__file__).parent.parent / "poll_closing.toml"

def test_shipped_schedule_covers_every_senate_race():
    closings = load_poll_closings(SHIPPED)
    senate_states = {"AK", "AL", "AR", "CO", "DE", "FL", "GA", "IA", "ID", "IL", "KS", "KY", "LA", "MA", "ME", "MI",
                     "MN", "MS", "MT", "NC", "NE", "NH", "NJ", "NM", "OH", "OK", "OR", "RI", "SC", "SD", "TN", "TX",
                     "VA", "WV", "WY"}
    assert set(closings) == senate_states
    assert all(c.first <= c.last for c in closings.values())

@pytest.mark.parametrize("state, label", [
    ("GA", "Tue 7 PM ET"),                        # 00:00 UTC on 4 Nov: standard time, not daylight
    ("NC", "Tue 7:30 PM ET"),
    ("MI", "Tue 8 PM ET (last 9 PM ET)"),
    ("AK", "Wed 12 AM ET (last 1 AM ET)"),
])
def test_labels_in_eastern_standard_time(state, label):
    assert _poll_close_label(load_poll_closings(SHIPPED)[state]) == label

def test_georgia_closes_at_midnight_utc():
    assert load_poll_closings(SHIPPED)["GA"].first == datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)

def test_missing_file_means_no_times(tmp_path):
    assert load_poll_closings(tmp_path / "none.toml") == {}

def test_times_without_offset_are_rejected(tmp_path):
    (tmp_path / "p.toml").write_text("[closing]\nGA = [2026-11-03T19:00:00, 2026-11-03T19:00:00]\n")
    with pytest.raises(ValueError, match="UTC offset"):
        load_poll_closings(tmp_path / "p.toml")
