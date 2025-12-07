# projectclone/tests/test_diff_engine_extended.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch, mock_open
from projectclone import diff_engine

class TestDiffEngineExtended:

    def test_diff_exception_handling(self, tmp_path, capsys):
        src = tmp_path / "src"
        src.mkdir()
        vault = tmp_path / "vault"
        vault.mkdir()

        target = src / "file.txt"
        target.write_text("content")

        with patch("projectclone.diff_engine.os.path.exists", return_value=True):
            with patch("projectclone.diff_engine._get_latest_snapshot", return_value="s.json"):
                with patch("projectclone.diff_engine.manifest.load_manifest", return_value={"files": {"file.txt": "hash"}}):
                    with patch("builtins.open", mock_open(read_data="content")):
                        with patch("difflib.unified_diff", side_effect=Exception("Diff fail")):
                            diff_engine.show_diff(str(src), str(vault), str(target))

        captured = capsys.readouterr()
        assert "Error performing diff: Diff fail" in captured.out

    def test_get_latest_snapshot_no_dir(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        # No snapshots dir
        res = diff_engine._get_latest_snapshot(str(vault), "proj")
        assert res is None

    def test_get_latest_snapshot_empty(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "snapshots").mkdir()
        (vault / "snapshots" / "proj").mkdir()

        res = diff_engine._get_latest_snapshot(str(vault), "proj")
        assert res is None

    def test_get_latest_snapshot_sorting(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        snap_dir = vault / "snapshots" / "proj"
        snap_dir.mkdir(parents=True)

        (snap_dir / "snap1.json").touch()
        (snap_dir / "snap2.json").touch()

        res = diff_engine._get_latest_snapshot(str(vault), "proj")
        # Sorted desc
        assert res == str(snap_dir / "snap2.json")
