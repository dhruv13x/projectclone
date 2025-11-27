# projectclone/tests/test_gc_engine.py

import pytest
import os
import json
from unittest.mock import patch

# Adjust sys.path to find project modules
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'projectclone')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'src')))

from projectclone import gc_engine
from src.common import manifest

@pytest.fixture
def test_vault(tmp_path):
    vault = tmp_path / "test_vault"
    snapshots_dir = vault / "snapshots"
    objects_dir = vault / "objects"
    
    snapshots_dir.mkdir(parents=True)
    objects_dir.mkdir()
    
    # --- Create objects ---
    (objects_dir / "hash1").write_text("obj1") # Referenced by snap1
    (objects_dir / "hash2").write_text("obj2") # Referenced by snap1 and snap2
    (objects_dir / "hash3").write_text("obj3") # Orphaned
    (objects_dir / "hash4").write_text("obj4") # Referenced by snap2
    (objects_dir / "not_a_file").mkdir() # Should be skipped
    
    # --- Create snapshots ---
    snap1 = {
        "timestamp": "2023-01-01T10:00:00+00:00", "source_path": "/proj",
        "files": {"a.txt": "hash1", "b.txt": "hash2"}
    }
    snap2 = {
        "timestamp": "2023-01-02T10:00:00+00:00", "source_path": "/proj",
        "files": {"b.txt": "hash2", "c.txt": "hash4"}
    }
    
    (snapshots_dir / "snap1.json").write_text(json.dumps(snap1))
    (snapshots_dir / "snap2.json").write_text(json.dumps(snap2))
    (snapshots_dir / "not_a_json.txt").write_text("ignore me")
    
    return vault

class TestRunGarbageCollection:
    def test_deletes_orphaned_objects(self, test_vault, capsys):
        objects_dir = test_vault / "objects"
        
        gc_engine.run_garbage_collection(str(test_vault), dry_run=False)
        
        assert (objects_dir / "hash1").exists()
        assert (objects_dir / "hash2").exists()
        assert not (objects_dir / "hash3").exists() # Orphaned, should be deleted
        assert (objects_dir / "hash4").exists()
        assert (objects_dir / "not_a_file").exists() # Should be skipped
        
        captured = capsys.readouterr()
        assert "Deleted: hash3" in captured.out
        assert "Reclaimed: 1 files" in captured.out

    def test_dry_run_does_not_delete(self, test_vault, capsys):
        objects_dir = test_vault / "objects"
        
        gc_engine.run_garbage_collection(str(test_vault), dry_run=True)
        
        # All objects should still exist
        assert (objects_dir / "hash1").exists()
        assert (objects_dir / "hash2").exists()
        assert (objects_dir / "hash3").exists()
        assert (objects_dir / "hash4").exists()
        
        captured = capsys.readouterr()
        assert "Would delete: hash3" in captured.out
        assert "Would reclaim: 1 files" in captured.out

    def test_aborts_on_unreadable_snapshot(self, test_vault, capsys):
        (test_vault / "snapshots" / "corrupted.json").write_text("{ not json }")

        with pytest.raises(SystemExit) as excinfo:
            gc_engine.run_garbage_collection(str(test_vault))
        
        assert excinfo.value.code == 1

        captured = capsys.readouterr()
        assert "CRITICAL SAFETY ERROR" in captured.out
        assert "Failed to parse snapshot 'corrupted.json'" in captured.out

    def test_graceful_exit_if_vault_dirs_missing(self, tmp_path, capsys):
        non_existent_vault = tmp_path / "no_vault"
        gc_engine.run_garbage_collection(str(non_existent_vault))
        
        captured = capsys.readouterr()
        assert "Vault directories missing. Nothing to clean." in captured.out

    def test_handles_os_error_on_delete(self, test_vault, capsys):
        with patch('os.remove', side_effect=OSError("Permission denied")):
            gc_engine.run_garbage_collection(str(test_vault), dry_run=False)
            
            captured = capsys.readouterr()
            assert "Error processing hash3: Permission denied" in captured.out

    def test_no_orphaned_objects(self, test_vault, capsys):
        # Remove the orphaned object
        (test_vault / "objects" / "hash3").unlink()
        
        gc_engine.run_garbage_collection(str(test_vault), dry_run=False)
        
        captured = capsys.readouterr()
        assert "Reclaimed: 0 files" in captured.out

    def test_no_snapshots_deletes_all(self, test_vault, capsys):
        # Remove all snapshots
        for f in (test_vault / "snapshots").iterdir():
            f.unlink()
            
        gc_engine.run_garbage_collection(str(test_vault), dry_run=False)
        
        objects_dir = test_vault / "objects"
        assert not (objects_dir / "hash1").exists()
        assert not (objects_dir / "hash2").exists()
        assert not (objects_dir / "hash3").exists()
        assert not (objects_dir / "hash4").exists()
        
        captured = capsys.readouterr()
        assert "Reclaimed: 4 files" in captured.out
