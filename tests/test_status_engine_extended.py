# projectclone/tests/test_status_engine_extended.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch, mock_open
from projectclone import status_engine

class TestStatusEngineExtended:

    def test_get_cloud_status_b2_error(self, tmp_path):
        vault = tmp_path / "vault"
        with patch("src.common.b2.B2Manager", side_effect=Exception("B2 Fail")):
            status = status_engine.get_cloud_status(str(vault), "bucket", None, "id", "key")
            assert status["error"] == "B2 Fail"
            assert status["connected"] is False

    def test_get_cloud_status_s3_error(self, tmp_path):
        vault = tmp_path / "vault"
        with patch("src.common.s3.S3Manager", side_effect=Exception("S3 Fail")):
            status = status_engine.get_cloud_status(str(vault), "bucket", "endpoint", "id", "key")
            assert status["error"] == "S3 Fail"

    def test_show_status_cloud_error_display(self, tmp_path, capsys):
        src = tmp_path / "src"
        vault = tmp_path / "vault"
        vault.mkdir()

        # Must provide key_id to trigger cloud check
        with patch("projectclone.status_engine.get_cloud_status", return_value={"connected": False, "error": "Network down"}):
            status_engine.show_status(str(src), str(vault), cloud_config={"bucket": "b", "key_id": "k", "app_key": "s"})

        captured = capsys.readouterr()
        assert "Error connecting to cloud" in captured.out
        assert "Network down" in captured.out

    def test_get_local_status_missing_manifest(self, tmp_path):
        src = tmp_path / "src"
        vault = tmp_path / "vault"

        with patch("projectclone.status_engine._get_latest_snapshot", return_value=str(vault / "missing.json")):
             status = status_engine.get_local_status(str(src), str(vault))
             assert status["snapshot_exists"] is False

    def test_cloud_status_diff(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()

        # Local: s1, s2, s3
        snap_dir = vault / "snapshots" / "proj"
        snap_dir.mkdir(parents=True)
        (snap_dir / "s1.json").write_text("{}")
        (snap_dir / "s2.json").write_text("{}")
        (snap_dir / "s3.json").write_text("{}")

        with patch("src.common.b2.B2Manager") as mock_b2:
            inst = mock_b2.return_value
            inst.list_file_names.return_value = [
                "snapshots/proj/s1.json",
                "snapshots/proj/s2.json",
                "snapshots/proj/s4.json"
            ]

            status = status_engine.get_cloud_status(str(vault), "bucket", None, "id", "key")

            assert status["local_count"] == 3
            assert status["cloud_count"] == 3
            assert status["to_push"] == 1 # s3
            assert status["to_pull"] == 1 # s4
            assert status["synced"] is False

    def test_show_status_no_snapshots(self, tmp_path, capsys):
        src = tmp_path / "src"
        src.mkdir()
        vault = tmp_path / "vault"
        vault.mkdir()

        with patch("projectclone.status_engine._get_latest_snapshot", return_value=None):
            status_engine.show_status(str(src), str(vault))

        captured = capsys.readouterr()
        assert "No snapshots found" in captured.out

    def test_show_status_clean(self, tmp_path, capsys):
        src = tmp_path / "src"
        vault = tmp_path / "vault"
        vault.mkdir()

        clean_status = {
            "project": "src",
            "snapshot_exists": True,
            "snapshot_time": "2023-01-01",
            "new_files": [],
            "modified_files": [],
            "deleted_files": [],
            "total_scanned": 10
        }

        with patch("projectclone.status_engine.get_local_status", return_value=clean_status):
            status_engine.show_status(str(src), str(vault))

        captured = capsys.readouterr()
        assert "Workspace is clean" in captured.out

    def test_show_status_dirty(self, tmp_path, capsys):
        src = tmp_path / "src"
        vault = tmp_path / "vault"
        vault.mkdir()

        dirty_status = {
            "project": "src",
            "snapshot_exists": True,
            "snapshot_time": "2023-01-01",
            "new_files": ["new.txt"],
            "modified_files": ["mod.txt"],
            "deleted_files": ["del.txt"],
            "total_scanned": 10
        }

        with patch("projectclone.status_engine.get_local_status", return_value=dirty_status):
            status_engine.show_status(str(src), str(vault))

        captured = capsys.readouterr()
        assert "pending changes" in captured.out
        assert "new.txt" in captured.out
        assert "mod.txt" in captured.out
        assert "del.txt" in captured.out

    def test_show_status_flood_protection(self, tmp_path, capsys):
        src = tmp_path / "src"
        vault = tmp_path / "vault"
        vault.mkdir()

        modified = [f"file{i}.txt" for i in range(20)]
        dirty_status = {
            "project": "src",
            "snapshot_exists": True,
            "snapshot_time": "now",
            "new_files": [],
            "modified_files": modified,
            "deleted_files": [],
            "total_scanned": 100
        }

        with patch("projectclone.status_engine.get_local_status", return_value=dirty_status):
            status_engine.show_status(str(src), str(vault))

        captured = capsys.readouterr()
        assert "more" in captured.out

    def test_show_status_cloud_synced(self, tmp_path, capsys):
        src = tmp_path / "src"
        vault = tmp_path / "vault"
        vault.mkdir()
        cloud_config = {"bucket": "bkt", "key_id": "k", "app_key": "s"}

        with patch("projectclone.status_engine.get_local_status", return_value={"snapshot_exists": False, "total_scanned":0}):
            with patch("projectclone.status_engine.get_cloud_status") as mock_cloud:
                mock_cloud.return_value = {
                    "connected": True, "error": None,
                    "synced": True, "to_push": 0, "to_pull": 0
                }
                status_engine.show_status(str(src), str(vault), cloud_config)

        captured = capsys.readouterr()
        assert "Synced with Cloud" in captured.out

    def test_show_status_cloud_ahead(self, tmp_path, capsys):
        src = tmp_path / "src"
        vault = tmp_path / "vault"
        vault.mkdir()
        cloud_config = {"bucket": "bkt", "key_id": "k", "app_key": "s"}

        with patch("projectclone.status_engine.get_local_status", return_value={"snapshot_exists": False, "total_scanned":0}):
            with patch("projectclone.status_engine.get_cloud_status") as mock_cloud:
                mock_cloud.return_value = {
                    "connected": True, "error": None,
                    "synced": False, "to_push": 0, "to_pull": 5
                }
                status_engine.show_status(str(src), str(vault), cloud_config)

        captured = capsys.readouterr()
        assert "Remote is ahead by 5 snapshots" in captured.out

    def test_show_status_local_ahead(self, tmp_path, capsys):
        src = tmp_path / "src"
        vault = tmp_path / "vault"
        vault.mkdir()
        cloud_config = {"bucket": "bkt", "key_id": "k", "app_key": "s"}

        with patch("projectclone.status_engine.get_local_status", return_value={"snapshot_exists": False, "total_scanned":0}):
            with patch("projectclone.status_engine.get_cloud_status") as mock_cloud:
                mock_cloud.return_value = {
                    "connected": True, "error": None,
                    "synced": False, "to_push": 3, "to_pull": 0
                }
                status_engine.show_status(str(src), str(vault), cloud_config)

        captured = capsys.readouterr()
        assert "Local is ahead by 3 snapshots" in captured.out
