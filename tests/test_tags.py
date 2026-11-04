import pytest

from src.tags import TagConfigError, load_race_tags


def write(tmp_path, text):
    path = tmp_path / "race_tags.toml"
    path.write_text(text)
    return path

def test_missing_file_means_no_tags(tmp_path):
    tags = load_race_tags(tmp_path / "absent.toml")
    assert tags.all_tags == [] and tags.control is None and tags.for_race("GA-SEN") == []

def test_races_collect_every_tag(tmp_path):
    tags = load_race_tags(write(tmp_path, '[tags]\n"toss-up" = ["ME-SEN", "mi-sen "]\nwatch = ["ME-SEN"]\n'))
    assert tags.for_race("ME-SEN") == ["toss-up", "watch"]
    assert tags.for_race("MI-SEN") == ["toss-up"]  # IDs are normalised
    assert tags.all_tags == ["toss-up", "watch"]

def test_control_tally_settings(tmp_path):
    text = '[tags]\nx = ["A-SEN"]\n[control]\ntag = "x"\ndem_needed = 4\nrep_needed = 3\n'
    tags = load_race_tags(write(tmp_path, text))
    assert (tags.control.tag, tags.control.dem_needed, tags.control.rep_needed) == ("x", 4, 3)

@pytest.mark.parametrize("text", ['[tags]\nx = "GA-SEN"\n', "not = [toml", '[control]\ntag = "x"\n'])
def test_bad_config_raises(tmp_path, text):
    with pytest.raises(TagConfigError):
        load_race_tags(write(tmp_path, text))

def test_shipped_tags_file_loads():
    tags = load_race_tags(__import__("pathlib").Path(__file__).parent.parent / "race_tags.toml")
    assert len([r for r, t in tags.by_race.items() if "toss-up" in t]) == 7
    assert tags.control.dem_needed == 4 and tags.control.rep_needed == 4
