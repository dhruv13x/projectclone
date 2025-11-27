# projectclone/tests/test_sync_engine.py

import pytest
import os
from unittest.mock import patch, MagicMock

# Adjust sys.path to find project modules
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'projectclone')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'src')))

from projectclone import sync_engine

@pytest.fixture
def local_vault(tmp_path):
    vault = tmp_path / "local_vault"
    (vault / "objects").mkdir(parents=True)
    (vault / "snapshots" / "proj1").mkdir(parents=True)
    
    (vault / "objects" / "hash1").write_text("obj1") # Exists remotely
    (vault / "objects" / "hash2").write_text("obj2") # New
    
    (vault / "snapshots" / "proj1" / "snap1.json").write_text("{}") # Exists remotely
    (vault / "snapshots" / "proj1" / "snap2.json").write_text("{}") # New
    
    return vault

@patch('src.common.b2.B2Manager')
class TestSyncToCloud:
    def test_syncs_new_files_to_cloud(self, MockB2Manager, local_vault):
        mock_manager = MockB2Manager.return_value
        # Correctly mock returning a SET of strings, as B2Manager.list_file_names returns Set[str]
        mock_manager.list_file_names.return_value = {
            "objects/hash1",
            "snapshots/proj1/snap1.json"
        }
        
        sync_engine.sync_to_cloud(str(local_vault), "bucket", None, "id", "key")
        
        # Assert that upload_file was called for new files
        mock_manager.upload_file.assert_any_call(
            str(local_vault / "objects" / "hash2"),
            "objects/hash2"
        )
        mock_manager.upload_file.assert_any_call(
            str(local_vault / "snapshots" / "proj1" / "snap2.json"),
            "snapshots/proj1/snap2.json"
        )
        
        # Assert that it was called exactly twice (once for each new file)
        assert mock_manager.upload_file.call_count == 2

    def test_handles_missing_objects_dir(self, MockB2Manager, local_vault, capsys):
        import shutil
        shutil.rmtree(local_vault / "objects")
        
        sync_engine.sync_to_cloud(str(local_vault), "bucket", None, "id", "key")
        
        captured = capsys.readouterr()
        assert "No objects directory found" in captured.out
        
    def test_handles_missing_snapshots_dir(self, MockB2Manager, local_vault, capsys):
        # Need to recursively remove the snapshots dir
        import shutil
        shutil.rmtree(local_vault / "snapshots")
        
        sync_engine.sync_to_cloud(str(local_vault), "bucket", None, "id", "key")
        
        captured = capsys.readouterr()
        assert "No snapshots directory found" in captured.out

    @patch('src.common.s3.S3Manager')
    def test_uses_s3_manager_with_endpoint(self, MockS3Manager, local_vault):
        # Test that providing an endpoint triggers S3Manager usage
        sync_engine.sync_to_cloud(str(local_vault), "bucket", "https://s3.example.com", "id", "key")
        MockS3Manager.assert_called_once()

@patch('src.common.b2.B2Manager')
class TestSyncFromCloud:
    def test_downloads_missing_files_from_cloud(self, MockB2Manager, local_vault):
        mock_manager = MockB2Manager.return_value
        mock_manager.list_file_names.return_value = {
            "objects/hash1", # Exists locally
            "objects/hash3", # New remote object
            "snapshots/proj1/snap1.json", # Exists locally
            "snapshots/proj1/snap3.json"  # New remote snapshot
        }
        
        sync_engine.sync_from_cloud(str(local_vault), "bucket", None, "id", "key")
        
        # Assert that download_file was called for missing files
        mock_manager.download_file.assert_any_call(
            "objects/hash3",
            str(local_vault / "objects" / "hash3")
        )
        mock_manager.download_file.assert_any_call(
            "snapshots/proj1/snap3.json",
            str(local_vault / "snapshots" / "proj1" / "snap3.json")
        )
        
        # Assert that it was called exactly twice
        assert mock_manager.download_file.call_count == 2
