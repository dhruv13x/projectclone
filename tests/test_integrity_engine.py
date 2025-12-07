# projectclone/tests/test_integrity_engine.py

import pytest
import os
from unittest.mock import patch

# Adjust sys.path to find project modules
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'projectclone')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'src')))

from projectclone import integrity_engine
from src.common import cas

@pytest.fixture
def test_vault(tmp_path):
    vault = tmp_path / "test_vault"
    objects_dir = vault / "objects"
    objects_dir.mkdir(parents=True)
    
    # --- Create objects ---
    # Healthy object
    (objects_dir / "d0b425e00e15a0d36b9b361f02bab63563aed6cb4665083905386c55d5b679fa").write_text("content1")
    # Healthy object 2
    (objects_dir / "a6e2a68230c506e2623a6fa3148de61b5839711c5cb5a1e289d807a93141d245").write_text("log content")
    # Corrupted object
    (objects_dir / "corrupted_hash").write_text("this content does not match the hash")
    
    return vault

class TestVerifyVault:
    def test_healthy_vault(self, test_vault, capsys):
        # Remove the corrupted file for this test
        (test_vault / "objects" / "corrupted_hash").unlink()
        
        result = integrity_engine.verify_vault(str(test_vault))
        assert result is True
        
        captured = capsys.readouterr()
        assert "Vault Integrity Verified: HEALTHY" in captured.out
        assert "Total Corrupted Files: 0" in captured.out

    def test_corrupted_vault(self, test_vault, capsys):
        result = integrity_engine.verify_vault(str(test_vault))
        assert result is False
        
        captured = capsys.readouterr()
        assert "CORRUPTION DETECTED: corrupted_hash" in captured.out
        assert "Vault Integrity Verification FAILED: CORRUPTED" in captured.out
        assert "Total Corrupted Files: 1" in captured.out

    def test_empty_objects_dir(self, tmp_path, capsys):
        vault = tmp_path / "empty_vault"
        (vault / "objects").mkdir(parents=True)
        
        result = integrity_engine.verify_vault(str(vault))
        assert result is True
        
        captured = capsys.readouterr()
        assert "Total Files Checked: 0" in captured.out
        assert "HEALTHY" in captured.out

    def test_missing_objects_dir(self, tmp_path, capsys):
        vault_no_objects = tmp_path / "no_objects_dir"
        vault_no_objects.mkdir()
        
        result = integrity_engine.verify_vault(str(vault_no_objects))
        assert result is False
        
        captured = capsys.readouterr()
        assert "Error: Objects directory not found" in captured.out

    def test_handles_exception_during_hash(self, test_vault, capsys):
        with patch('src.common.cas.calculate_hash', side_effect=IOError("Can't read file")):
            result = integrity_engine.verify_vault(str(test_vault))
            assert result is False # If any error occurs, vault is not healthy
            
            captured = capsys.readouterr()
            # The number of corrupted files depends on iteration order, so we check for at least one error
            assert "ERROR processing" in captured.out
            assert "Total Corrupted Files: 3" in captured.out
            assert "FAILED" in captured.out
