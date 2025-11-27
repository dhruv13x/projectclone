# projectclone/tests/test_list_engine.py

import pytest
import os
import json
from unittest.mock import patch, MagicMock

# Adjust sys.path to find project modules
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'projectclone')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'src')))

from projectclone import list_engine

@pytest.fixture
def test_vault(tmp_path):
    vault = tmp_path / "test_vault"
    snapshots_dir = vault / "snapshots"
    proj1_dir = snapshots_dir / "proj1"
    proj2_dir = snapshots_dir / "proj2"
    
    proj1_dir.mkdir(parents=True)
    proj2_dir.mkdir()
    
    (proj1_dir / "snapshot_2023-01-01T10-00-00.json").touch()
    (proj1_dir / "snapshot_2023-01-02T12-00-00.json").touch()
    (proj2_dir / "snapshot_2023-01-03T14-00-00.json").touch()
    
    return vault

    def test_valid_filename(self):
        filename = "snapshot_2025-11-22T15-12-01.json"
        assert list_engine._parse_snapshot_name(filename) == "2025-11-22 15:12:01"

    def test_invalid_filename(self):
        filename = "invalid_filename.json"
        assert list_engine._parse_snapshot_name(filename) == filename

class TestListLocalSnapshots:
    def test_lists_snapshots_correctly(self, test_vault, capsys):
        list_engine.list_local_snapshots(str(test_vault))
        captured = capsys.readouterr()
        
        assert "Local Vault Snapshots" in captured.out
        assert "proj1" in captured.out
        assert "proj2" in captured.out
        assert "2023-01-01 10:00:00" in captured.out
        assert "2023-01-02 12:00:00" in captured.out
        assert "2023-01-03 14:00:00" in captured.out


    def test_no_snapshots_found(self, tmp_path, capsys):
        vault = tmp_path / "empty_vault"
        (vault / "snapshots").mkdir(parents=True)
        
        list_engine.list_local_snapshots(str(vault))
        captured = capsys.readouterr()
        
        assert "No snapshots found" in captured.out
        
    def test_missing_snapshots_dir(self, tmp_path, capsys):
        vault = tmp_path / "no_snapshots_dir"
        vault.mkdir()
        
        list_engine.list_local_snapshots(str(vault))
        captured = capsys.readouterr()
        
        assert "Snapshot directory not found" in captured.out

class TestListCloudSnapshots:
    @patch('src.common.b2.B2Manager')
    def test_lists_cloud_snapshots(self, MockB2Manager, capsys):
        mock_manager = MockB2Manager.return_value
        # Fix: Return a SET of strings, not a list of dicts
        mock_manager.list_file_names.return_value = {
            'snapshots/proj1/snapshot_2023-01-01T10-00-00.json',
            'snapshots/proj2/snapshot_2023-01-03T14-00-00.json',
            'objects/hash1',
        }
        
        list_engine.list_cloud_snapshots("test-bucket", "key_id", "app_key")
        captured = capsys.readouterr()
        
        assert "Cloud Vault Snapshots in Bucket: 'test-bucket'" in captured.out
        assert "proj1" in captured.out
        assert "proj2" in captured.out

    @patch('src.common.b2.B2Manager')
    def test_no_cloud_snapshots_found(self, MockB2Manager, capsys):
        mock_manager = MockB2Manager.return_value
        mock_manager.list_file_names.return_value = set()
        
        list_engine.list_cloud_snapshots("test-bucket", "key_id", "app_key")
        captured = capsys.readouterr()
        
        assert "No vault snapshots found in bucket 'test-bucket'" in captured.out

    @patch('src.common.b2.B2Manager', side_effect=Exception("B2 Connection Error"))
    def test_cloud_connection_error(self, MockB2Manager, capsys):
        list_engine.list_cloud_snapshots("test-bucket", "key_id", "app_key")
        captured = capsys.readouterr()
        
        assert "Error connecting to cloud backend" in captured.out
        assert "B2 Connection Error" in captured.out

    @patch('src.common.s3.S3Manager')
    def test_uses_s3_with_endpoint(self, MockS3Manager, capsys):
        list_engine.list_cloud_snapshots("test-bucket", "key_id", "app_key", endpoint="http://s3.local")
        MockS3Manager.assert_called_once()
