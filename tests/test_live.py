"""LiveDataReader: decoding snapshots and freshness notices."""
from datetime import datetime, timedelta, timezone

from src.live import LiveDataReader
from src.models import Candidate, RaceData, Severity
from src.officials import OfficialCount, OfficialResult
from src.store import SnapshotStore

T0 = datetime(2026, 11, 3, 23, 0, tzinfo=timezone.utc)
RACE = RaceData("TX-SEN", "Texas", Candidate("A", "Democratic", 1), Candidate("B", "Republican", 2), 10, 0.5, 0.03)


def reader(store, now=T0):
    return LiveDataReader(store, 30, "civicapi", now=lambda: now)


def test_empty_store_says_waiting(tmp_path):
    data = reader(SnapshotStore(tmp_path / "s.db")).read()
    assert data.races == [] and data.races_checked_at is None
    assert [n.severity for n in data.notices] == [Severity.INFO]


def test_first_fetch_failing_is_an_error(tmp_path):
    store = SnapshotStore(tmp_path / "s.db")
    store.record_attempt("races", False, "ReadTimeout", at=T0)
    notice, = reader(store).read().notices
    assert notice.severity is Severity.ERROR and "ReadTimeout" in notice.text


def test_decodes_all_kinds_and_is_quiet_when_fresh(tmp_path):
    store = SnapshotStore(tmp_path / "s.db")
    store.save_snapshot("races", [RACE.to_dict()], at=T0)
    store.record_attempt("races", True, at=T0)
    ohio = OfficialResult("OH", count=OfficialCount("OH", "s", "u", {}, "r"))
    store.save_snapshot("officials", {"OH": ohio.to_dict()})
    data = reader(store, now=T0 + timedelta(seconds=40)).read()
    assert data.races == [RACE] and data.officials["OH"].ok and data.early_vote is None
    assert data.notices == [] and data.races_checked_at == T0


def test_failed_update_warns_but_keeps_results(tmp_path):
    store = SnapshotStore(tmp_path / "s.db")
    store.save_snapshot("races", [RACE.to_dict()], at=T0)
    store.record_attempt("races", True, at=T0)
    store.record_attempt("races", False, "timeout", at=T0 + timedelta(seconds=30))
    data = reader(store).read()
    assert data.races == [RACE]
    notice, = data.notices
    assert notice.severity is Severity.WARNING and "failed" in notice.text and "6:00:00 PM ET" in notice.text


def test_stale_data_warns(tmp_path):
    store = SnapshotStore(tmp_path / "s.db")
    store.save_snapshot("races", [RACE.to_dict()], at=T0)
    store.record_attempt("races", True, at=T0)
    notice, = reader(store, now=T0 + timedelta(minutes=10)).read().notices
    assert "No new update since" in notice.text


def snapshot_with(dem, rep, turnout=100):
    race = RaceData("TX-SEN", "Texas", Candidate("A", "Democratic", dem), Candidate("B", "Republican", rep),
                    turnout, 0.5, 0.03)
    return [race.to_dict()]


def test_margin_history_reads_only_new_snapshots(tmp_path):
    from src.live import MarginHistory
    store = SnapshotStore(tmp_path / "s.db")
    store.save_snapshot("races", snapshot_with(0, 0), at=T0)  # before votes: no point
    store.save_snapshot("races", snapshot_with(30, 20), at=T0 + timedelta(minutes=1))
    history = MarginHistory(store)
    assert [p.margin for p in history.series("TX-SEN")] == [0.2]
    store.save_snapshot("races", snapshot_with(40, 60), at=T0 + timedelta(minutes=2))
    points = history.series("TX-SEN")
    assert [p.margin for p in points] == [0.2, -0.2] and points[1].pct_reporting == 100.0
    assert history.series("TX-SEN") == points  # nothing new: no duplicates
    assert history.series("AK-SEN") == []


def test_margin_figure_draws_both_sides():
    from src.live import MarginPoint
    from src.ui.charts import margin_figure
    points = [MarginPoint(T0, 0.1, 20), MarginPoint(T0 + timedelta(minutes=5), -0.05, 40)]
    fig = margin_figure(points, "DEM", "REP", "#2166ac", "#b2182b")
    dem_fill, rep_fill, line = fig.data
    assert list(dem_fill.y) == [10.0, 0] and list(rep_fill.y) == [0, -5.0]
    assert "REP +5.0 pts" in line.text[1] and fig.layout.yaxis.range == (-11.5, 11.5)
