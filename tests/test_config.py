"""Settings.from_env."""
import pytest

from src.config import PROJECT_ROOT, Settings


def test_defaults():
    s = Settings.from_env({})
    assert (s.refresh_seconds, s.races_poll_seconds, s.officials_poll_seconds) == (30, 30, 60)
    assert s.snapshot_db == PROJECT_ROOT / "data" / "snapshots.db"


def test_overrides_and_absolute_paths(tmp_path):
    s = Settings.from_env({"POLL_RACES_SECONDS": "20", "SNAPSHOT_DB": str(tmp_path / "x.db"),
                           "RACE_TAGS_FILE": "other.toml"})
    assert s.races_poll_seconds == 20 and s.snapshot_db == tmp_path / "x.db"
    assert s.tags_file == PROJECT_ROOT / "other.toml" and s.env["POLL_RACES_SECONDS"] == "20"


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_bad_numbers_name_the_variable(value):
    with pytest.raises(ValueError, match="REFRESH_INTERVAL_SECONDS"):
        Settings.from_env({"REFRESH_INTERVAL_SECONDS": value})
