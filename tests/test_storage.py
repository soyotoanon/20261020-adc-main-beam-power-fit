import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"host"))
from storage import write_snapshot


def test_locked_destination_preserves_old_and_new(tmp_path, monkeypatch):
    target = tmp_path/"points.csv"
    target.write_text("old", encoding="utf-8")
    def locked(*args, **kwargs):
        raise PermissionError("destination held by reader")
    monkeypatch.setattr(Path, "replace", locked)
    saved = write_snapshot(target, "power,code\n0.01,8000\n")
    assert saved != target
    assert target.read_text() == "old"
    assert saved.read_text(encoding="utf-8-sig") == "power,code\n0.01,8000\n"


def test_normal_snapshot_replaces(tmp_path):
    target = tmp_path/"fit.json"
    assert write_snapshot(target, '{"n": 3}') == target
    assert write_snapshot(target, '{"n": 4}') == target
    assert target.read_text() == '{"n": 4}'
