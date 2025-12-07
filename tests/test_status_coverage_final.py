# projectclone/tests/test_status_coverage_final.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch, mock_open
from projectclone import status_engine

class TestStatusCoverageFinal:

    def test_get_local_status_with_project_name(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        vault = tmp_path / "vault"
        vault.mkdir()

        # Should use provided project name
        with patch("projectclone.status_engine._get_latest_snapshot") as mock_get:
             status_engine.get_local_status(str(src), str(vault), project_name="custom")
             mock_get.assert_called_with(str(vault), "custom")

    def test_get_local_status_ignore_file(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        vault = tmp_path / "vault"

        (src / ".vaultignore").write_text("ignore.txt")
        (src / "ignore.txt").touch()
        (src / "keep.txt").touch()

        # Mock manifest to be empty
        with patch("projectclone.status_engine._get_latest_snapshot", return_value=None):
             status = status_engine.get_local_status(str(src), str(vault))

        # ignore.txt should not be in new_files
        assert "ignore.txt" not in status["new_files"]
        assert "keep.txt" in status["new_files"]

    def test_status_vanished_file(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        f = src / "vanish.txt"
        f.write_text("content")
        vault = tmp_path / "vault"

        # Use real manifest structure to trigger hash calc
        (vault / "snapshots" / "src").mkdir(parents=True)
        manifest = vault / "snapshots" / "src" / "s.json"
        manifest.write_text('{"files": {"vanish.txt": "hash"}}')

        # Mock calculate_hash to raise OSError
        with patch("src.common.cas.calculate_hash", side_effect=OSError):
             status = status_engine.get_local_status(str(src), str(vault))

        # Should catch OSError and not add to modified/new
        assert "vanish.txt" not in status["modified_files"]
        assert "vanish.txt" not in status["new_files"]
        # It IS in manifest, so if not scanned (because error?), it might be in deleted?
        # Logic:
        # if rel_path not in manifest: ...
        # else: compare hash. Exception -> pass.
        # So it stays in scanned_files (added before check).
        # So it is NOT deleted.
        assert "vanish.txt" not in status["deleted_files"]

    def test_status_manifest_load_error(self, tmp_path, capsys):
        src = tmp_path / "src"
        src.mkdir()
        vault = tmp_path / "vault"

        (vault / "snapshots" / "src").mkdir(parents=True)
        manifest = vault / "snapshots" / "src" / "s.json"
        manifest.write_text("{broken")

        status = status_engine.get_local_status(str(src), str(vault))

        captured = capsys.readouterr()
        assert "Error loading manifest" in captured.out
        assert status["snapshot_exists"] is False
