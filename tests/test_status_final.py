# projectclone/tests/test_status_final.py


import os
import pytest
from unittest.mock import patch, MagicMock
from projectclone import status_engine

class TestStatusFinal:

    def test_get_cloud_status_push_pull(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "snapshots").mkdir()
        (vault / "snapshots" / "p").mkdir()
        (vault / "snapshots" / "p" / "s1.json").write_text("{}")

        with patch("src.common.b2.B2Manager") as mock_b2:
            inst = mock_b2.return_value
            # Cloud has s2.json, local has s1.json
            inst.list_file_names.return_value = ["snapshots/p/s2.json"]

            status = status_engine.get_cloud_status(str(vault), "bucket", None, "id", "key")

            assert status["local_count"] == 1
            assert status["cloud_count"] == 1
            assert status["to_push"] == 1
            assert status["to_pull"] == 1
            assert status["synced"] is False

    def test_get_cloud_status_error(self, tmp_path):
        vault = tmp_path / "vault"
        with patch("src.common.b2.B2Manager", side_effect=Exception("Auth failed")):
            status = status_engine.get_cloud_status(str(vault), "bucket", None, "id", "key")
            assert status["error"] == "Auth failed"
            assert status["connected"] is False

    def test_get_local_status_ignored(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        vault = tmp_path / "vault"
        vault.mkdir()

        (src / ".git").mkdir()
        (src / "__pycache__").mkdir()
        (src / "normal.txt").touch()

        status = status_engine.get_local_status(str(src), str(vault))

        # .git and __pycache__ should be ignored
        # normal.txt should be new
        assert "normal.txt" in status["new_files"]
        assert status["total_scanned"] == 1
