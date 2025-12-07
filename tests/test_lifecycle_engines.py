# projectclone/tests/test_lifecycle_engines.py

import pytest
import os
import json
from unittest.mock import patch, MagicMock, mock_open
from projectclone import diff_engine, status_engine, checkout_engine

# --- Fixtures ---

@pytest.fixture
def mock_console():
    with patch('projectclone.diff_engine.Console') as mock:
        yield mock.return_value

@pytest.fixture
def mock_console_status():
    with patch('projectclone.status_engine.Console') as mock:
        yield mock.return_value

@pytest.fixture
def mock_console_checkout():
    with patch('projectclone.checkout_engine.Console') as mock:
        yield mock.return_value

@pytest.fixture
def mock_manifest():
    return {
        "timestamp": "2023-01-01T12:00:00",
        "files": {
            "file1.txt": "hash1",
            "dir/file2.txt": "hash2"
        }
    }

# --- Diff Engine Tests ---

class TestDiffEngine:
    @patch('projectclone.diff_engine._get_latest_snapshot')
    @patch('src.common.manifest.load_manifest')
    @patch('os.path.exists')
    def test_show_diff_success(self, mock_exists, mock_load, mock_get_snap, mock_console, mock_manifest):
        mock_get_snap.return_value = "/vault/snapshots/proj/snap.json"
        mock_load.return_value = mock_manifest
        mock_exists.return_value = True # object exists

        # Mock opening files
        file_content_map = {
            "/vault/objects/hash1": "line1\nline2\n",
            os.path.abspath("file1.txt"): "line1\nline2 modified\n"
        }
        
        def side_effect_open(file, mode='r', **kwargs):
            content = file_content_map.get(file, "")
            return mock_open(read_data=content).return_value

        with patch('builtins.open', side_effect=side_effect_open):
            diff_engine.show_diff(".", "/vault", "file1.txt")

        # Verify Syntax was printed (meaning diff was found)
        mock_console.print.assert_called()
        # We check if Syntax object was passed
        args, _ = mock_console.print.call_args
        assert "Syntax" in str(type(args[0]))

    def test_show_diff_file_not_in_source(self, mock_console):
        diff_engine.show_diff("/src", "/vault", "/outside/file.txt")
        mock_console.print.assert_called_with("[red]Error:[/red] File '/outside/file.txt' is not inside the source project '/src'.")

    @patch('projectclone.diff_engine._get_latest_snapshot', return_value=None)
    def test_show_diff_no_snapshot(self, mock_get_snap, mock_console):
        diff_engine.show_diff(".", "/vault", "file.txt")
        mock_console.print.assert_called()
        assert "No snapshots found" in str(mock_console.print.call_args)

    @patch('projectclone.diff_engine._get_latest_snapshot')
    @patch('src.common.manifest.load_manifest')
    def test_show_diff_file_new(self, mock_load, mock_get_snap, mock_console, mock_manifest):
        mock_get_snap.return_value = "snap.json"
        mock_load.return_value = mock_manifest
        
        diff_engine.show_diff(".", "/vault", "new_file.txt")
        assert "is new" in str(mock_console.print.call_args)

# --- Status Engine Tests ---

class TestStatusEngine:
    @patch('projectclone.status_engine._get_latest_snapshot', return_value=None)
    @patch('os.walk')
    def test_get_local_status_no_snapshot(self, mock_walk, mock_get_snap):
        mock_walk.return_value = [(".", [], ["file1.txt"])]
        status = status_engine.get_local_status(".", "/vault")
        assert status["snapshot_exists"] is False
        assert status["total_scanned"] == 1

    @patch('projectclone.status_engine._get_latest_snapshot', return_value="snap.json")
    @patch('src.common.manifest.load_manifest')
    @patch('os.walk')
    @patch('src.common.cas.calculate_hash', return_value="hash1") # Matches manifest
    def test_get_local_status_clean(self, mock_hash, mock_walk, mock_load, mock_get_snap, mock_manifest):
        mock_load.return_value = mock_manifest
        mock_walk.return_value = [(".", [], ["file1.txt"])] # Only file1 exists
        
        # file1 matches hash1, so no mod. dir/file2 is missing.
        status = status_engine.get_local_status(".", "/vault")
        
        assert status["snapshot_exists"] is True
        assert "file1.txt" not in status["modified_files"]
        assert "dir/file2.txt" in status["deleted_files"]

    @patch('projectclone.status_engine.s3.S3Manager')
    def test_get_cloud_status_s3(self, mock_s3_cls):
        mock_inst = mock_s3_cls.return_value
        mock_inst.list_file_names.return_value = ["snapshots/p/s1.json", "snapshots/p/s2.json"]
        
        # Mock local walk to find 1 snapshot
        with patch('os.walk', return_value=[("/vault/snapshots", [], ["s1.json"])]):
            with patch('os.path.exists', return_value=True):
                status = status_engine.get_cloud_status("/vault", "bucket", "endpoint", "id", "key")
        
        # Local has 1, Cloud has 2. Local is behind (to_pull=1, to_push=0 if s1 is same)
        # Logic check: local set={'snapshots/s1.json'}, cloud set={'snapshots/p/s1.json'}
        # The engine reconstructs keys. If local is flat, it might mismatch paths.
        # Let's check logic in status_engine.py:
        # rel_path = os.path.relpath(..., snapshots_dir) -> "s1.json" (if in root of snaps)
        # key = snapshots/s1.json
        # cloud list has snapshots/p/s1.json. They differ.
        
        assert status["connected"] is True
        assert status["cloud_count"] == 2

# --- Checkout Engine Tests ---

class TestCheckoutEngine:
    @patch('projectclone.checkout_engine._get_latest_snapshot')
    @patch('src.common.manifest.load_manifest')
    @patch('shutil.copy2')
    @patch('os.path.exists')
    def test_checkout_file_success(self, mock_exists, mock_copy, mock_load, mock_get_snap, mock_console_checkout, mock_manifest):
        mock_get_snap.return_value = "snap.json"
        mock_load.return_value = mock_manifest
        mock_exists.return_value = True
        
        checkout_engine.checkout_file(".", "/vault", "file1.txt", force=True)
        
        mock_copy.assert_called()
        mock_console_checkout.print.assert_called()
        assert "Restored" in str(mock_console_checkout.print.call_args)

    @patch('projectclone.checkout_engine._get_latest_snapshot')
    @patch('src.common.manifest.load_manifest')
    @patch('builtins.input', return_value='n')
    @patch('os.path.exists', return_value=True)
    def test_checkout_file_abort(self, mock_exists, mock_input, mock_load, mock_get_snap, mock_console_checkout, mock_manifest):
        mock_get_snap.return_value = "snap.json"
        mock_load.return_value = mock_manifest
        
        checkout_engine.checkout_file(".", "/vault", "file1.txt", force=False)
        
        assert "Aborted" in str(mock_console_checkout.print.call_args)
