# projectclone/tests/test_list_engine_extended.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch, mock_open
from projectclone import list_engine

class TestListEngineExtended:

    def test_list_local_snapshots_empty(self, tmp_path, capsys):
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "snapshots").mkdir()

        list_engine.list_local_snapshots(str(vault))

        captured = capsys.readouterr()
        assert "No snapshots found" in captured.out

    def test_list_local_snapshots_missing_dir(self, tmp_path, capsys):
        vault = tmp_path / "vault"

        list_engine.list_local_snapshots(str(vault))

        captured = capsys.readouterr()
        assert "Snapshot directory not found" in captured.out

    def test_list_local_snapshots_ignore_files_in_root(self, tmp_path, capsys):
        vault = tmp_path / "vault"
        vault.mkdir()
        snapshots = vault / "snapshots"
        snapshots.mkdir()
        (snapshots / "ignore_me.txt").touch()

        list_engine.list_local_snapshots(str(vault))

        captured = capsys.readouterr()
        assert "No snapshots found" in captured.out

    def test_list_cloud_snapshots_success(self, capsys):
        with patch("src.common.b2.B2Manager") as mock_b2:
            inst = mock_b2.return_value
            inst.list_file_names.return_value = ["snapshots/p1/s1.json", "snapshots/p1/s2.json"]

            list_engine.list_cloud_snapshots("bucket", "id", "key")

        captured = capsys.readouterr()
        assert "p1" in captured.out

    def test_list_cloud_ignore_bad_names(self, capsys):
        with patch("src.common.b2.B2Manager") as mock_b2:
            inst = mock_b2.return_value
            inst.list_file_names.return_value = ["snapshots/p1", "snapshots/file.json", "other/file"]

            list_engine.list_cloud_snapshots("bucket", "id", "key")

        captured = capsys.readouterr()
        assert "No vault snapshots found in bucket 'bucket'." in captured.out

    def test_list_cloud_snapshots_error(self, capsys):
        with patch("src.common.b2.B2Manager", side_effect=Exception("Auth fail")):
            list_engine.list_cloud_snapshots("bucket", "id", "key")

        captured = capsys.readouterr()
        assert "Error connecting to cloud backend" in captured.out
