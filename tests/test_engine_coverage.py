# projectclone/tests/test_engine_coverage.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch

from projectclone import diff_engine, status_engine, list_engine
from src import cli

class TestStatusAndDiffCoverage:
    """Consolidated tests for status_engine, diff_engine, and list_engine edge cases."""

    def test_diff_missing_object_direct(self, tmp_path, capsys):
        # Force execution of diff_engine missing object branch
        src = tmp_path / "src"
        src.mkdir()
        vault = tmp_path / "vault"
        vault.mkdir()

        # Mock everything
        with patch("projectclone.diff_engine.os.path.abspath", side_effect=lambda x: str(x)):
            with patch("projectclone.diff_engine.os.path.relpath", return_value="f.txt"):
                with patch("projectclone.diff_engine._get_latest_snapshot", return_value="s.json"):
                    with patch("projectclone.diff_engine.manifest.load_manifest", return_value={"files": {"f.txt": "h"}}):
                        # Mock object path check to FAIL immediately
                        with patch("projectclone.diff_engine.os.path.exists", return_value=False):
                             diff_engine.show_diff("src", "vault", "src/f.txt")

        captured = capsys.readouterr()
        assert "missing in vault" in captured.out

    def test_status_engine_print_loop_break(self, tmp_path, capsys):
        src = tmp_path / "src"
        vault = tmp_path / "vault"
        vault.mkdir()

        files = [f"f{i}" for i in range(15)]
        stat = {
            "project": "p",
            "snapshot_exists": True,
            "snapshot_time": "t",
            "new_files": [],
            "modified_files": files,
            "deleted_files": [],
            "total_scanned": 100
        }

        with patch("projectclone.status_engine.get_local_status", return_value=stat):
            status_engine.show_status(str(src), str(vault))

        captured = capsys.readouterr()
        assert "...and 5 more" in captured.out

    def test_get_cloud_status_s3_success(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()

        with patch("src.common.s3.S3Manager") as mock_s3:
            inst = mock_s3.return_value
            inst.list_file_names.return_value = []

            status = status_engine.get_cloud_status(str(vault), "bucket", "endpoint", "id", "key")
            assert status["connected"] is True
            assert status["error"] is None

    def test_list_local_snapshots_file_handling(self, tmp_path, capsys):
        vault = tmp_path / "vault"
        vault.mkdir()
        snapshots = vault / "snapshots"
        snapshots.mkdir()
        (snapshots / "file").touch()
        (snapshots / "dir").mkdir()

        list_engine.list_local_snapshots(str(vault))
        captured = capsys.readouterr()
        assert "No snapshots found" in captured.out

    def test_cli_check_integrity_command(self, tmp_path):
        with patch.object(sys, 'argv', ['pv', 'check-integrity', str(tmp_path)]):
            with patch("projectclone.integrity_engine.verify_vault") as mock_verify:
                 cli.main()
                 mock_verify.assert_called()

    def test_cli_gc_command(self, tmp_path):
        with patch.object(sys, 'argv', ['pv', 'gc', str(tmp_path)]):
             with patch("projectclone.gc_engine.run_garbage_collection") as mock_gc:
                 cli.main()
                 mock_gc.assert_called()
