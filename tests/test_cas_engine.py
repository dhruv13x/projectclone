# projectclone/tests/test_cas_engine.py

import pytest
import os
import sys
from unittest.mock import patch

# Correctly configure sys.path to find project modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'projectclone')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'src')))

from projectclone import cas_engine
from src.common import manifest, cas

@pytest.fixture
def source_dir(tmp_path):
    d = tmp_path / "my-project"
    d.mkdir()
    (d / "file1.txt").write_text("content1")
    (d / "file2.log").write_text("log content")
    sub = d / "subdir"
    sub.mkdir()
    (sub / "file3.txt").write_text("content3")
    return d

@pytest.fixture
def vault_dir(tmp_path):
    d = tmp_path / "my-vault"
    d.mkdir()
    return d

class TestBackupToVault:
    def test_successful_backup(self, source_dir, vault_dir, capsys):
        manifest_path = cas_engine.backup_to_vault(str(source_dir), str(vault_dir))
        
        assert os.path.exists(manifest_path)
        
        data = manifest.load_manifest(manifest_path)
        
        assert "files" in data
        assert len(data["files"]) == 3
        
        rel_path1 = os.path.relpath(source_dir / "file1.txt", source_dir)
        rel_path3 = os.path.relpath(source_dir / "subdir" / "file3.txt", source_dir)
        
        assert rel_path1 in data["files"]
        assert rel_path3 in data["files"]
        
        entry1 = data["files"][rel_path1]
        entry3 = data["files"][rel_path3]
        
        # Handle V2 Manifest (dict) vs V1 (string)
        if isinstance(entry1, dict):
            hash1 = entry1["hash"]
            hash3 = entry3["hash"]
        else:
            hash1 = entry1
            hash3 = entry3
        
        assert (vault_dir / "objects" / hash1).exists()
        assert (vault_dir / "objects" / hash3).exists()
        
        captured = capsys.readouterr()
        assert "Backup complete." in captured.out

    def test_source_and_vault_identity_error(self, source_dir):
        with pytest.raises(ValueError, match="Source and Vault paths cannot be the same"):
            cas_engine.backup_to_vault(str(source_dir), str(source_dir))

    def test_vault_inside_source_error(self, source_dir):
        nested_vault = source_dir / "nested_vault"
        nested_vault.mkdir()
        
        with pytest.raises(ValueError, match="Vault path is inside Source path but not ignored"):
            cas_engine.backup_to_vault(str(source_dir), str(nested_vault))

    def test_vault_inside_source_is_ignored(self, source_dir, capsys):
        nested_vault = source_dir / ".vault"
        nested_vault.mkdir()
        
        # Explicitly ignore the nested vault
        (source_dir / ".vaultignore").write_text(".vault/")

        # This should succeed without raising an error
        cas_engine.backup_to_vault(str(source_dir), str(nested_vault))
        
        # Now test with another name from .vaultignore
        another_vault = source_dir / "another_vault"
        another_vault.mkdir()
        
        (source_dir / ".vaultignore").write_text(".vault/\nanother_vault/")
        
        cas_engine.backup_to_vault(str(source_dir), str(another_vault))
        captured = capsys.readouterr()
        assert "SAFETY ERROR" not in captured.out

    def test_project_name_derivation_and_sanitization(self, source_dir, vault_dir, capsys):
        # With unsafe characters
        project_dir = source_dir.parent / "My Project (Test)"
        source_dir.rename(project_dir)
        
        cas_engine.backup_to_vault(str(project_dir), str(vault_dir))
        
        assert (vault_dir / "snapshots" / "My_Project__Test_").exists()
        
        captured = capsys.readouterr()
        assert "Using project name: My_Project__Test_" in captured.out
        
    def test_ignores_files_from_vaultignore(self, source_dir, vault_dir):
        (source_dir / ".vaultignore").write_text("*.log\nsubdir/")
        
        manifest_path = cas_engine.backup_to_vault(str(source_dir), str(vault_dir))
        data = manifest.load_manifest(manifest_path)
        
        # We expect file1.txt AND .vaultignore (which is always backed up)
        assert len(data["files"]) == 2
        assert "file1.txt" in data["files"]
        assert ".vaultignore" in data["files"]
        assert "file2.log" not in data["files"]
        assert not any("subdir" in key for key in data["files"])

    def test_error_during_store_object_is_handled(self, source_dir, vault_dir, capsys):
        with patch('src.common.cas.store_object', side_effect=Exception("Disk full")):
            with pytest.raises(Exception, match="Disk full"):
                cas_engine.backup_to_vault(str(source_dir), str(vault_dir))
            
            captured = capsys.readouterr()
            # The order of processing is not guaranteed, check for either file
            assert "Error processing file1.txt: Disk full" in captured.out or \
                   "Error processing file2.log: Disk full" in captured.out or \
                   "Error processing subdir/file3.txt: Disk full" in captured.out
