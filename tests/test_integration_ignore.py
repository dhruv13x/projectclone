# projectclone/tests/test_integration_ignore.py

import os
import shutil
import pytest
from pathlib import Path
from projectclone.cas_engine import backup_to_vault
from projectclone.backup import copy_tree_atomic
from projectclone.scanner import walk_stats

@pytest.fixture
def temp_project(tmp_path):
    project = tmp_path / "myproject"
    project.mkdir()

    # Create structure
    (project / "file.txt").write_text("keep")
    (project / "ignore_me.txt").write_text("ignore")
    (project / "ignore_dir").mkdir()
    (project / "ignore_dir" / "file.txt").write_text("ignore")
    (project / "keep_dir").mkdir()
    (project / "keep_dir" / "file.txt").write_text("keep")
    (project / "keep_dir" / "ignore_nested.txt").write_text("ignore")

    # .pvignore
    (project / ".pvignore").write_text("""
# Ignore files
ignore_me.txt

# Ignore dir
ignore_dir/

# Ignore nested
ignore_nested.txt
""")
    return project

@pytest.fixture
def temp_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault

def test_scanner_respects_pvignore(temp_project):
    # walk_stats should automatically pick up .pvignore
    total_files, total_size = walk_stats(temp_project)

    # Expected files: file.txt, keep_dir/file.txt, .pvignore
    # Ignored: ignore_me.txt, ignore_dir/*, keep_dir/ignore_nested.txt

    # Files present:
    # 1. file.txt
    # 2. .pvignore
    # 3. keep_dir/file.txt

    assert total_files == 3

def test_legacy_backup_respects_pvignore(temp_project, tmp_path):
    dest = tmp_path / "backup_dest"
    dest.mkdir()

    final_dest = copy_tree_atomic(temp_project, dest, "backup_v1")

    assert (final_dest / "file.txt").exists()
    assert (final_dest / "keep_dir" / "file.txt").exists()
    assert (final_dest / ".pvignore").exists() # .pvignore itself is not ignored

    assert not (final_dest / "ignore_me.txt").exists()
    assert not (final_dest / "ignore_dir").exists()
    assert not (final_dest / "keep_dir" / "ignore_nested.txt").exists()

def test_cas_backup_respects_pvignore(temp_project, temp_vault):
    manifest_path = backup_to_vault(str(temp_project), str(temp_vault))

    # Load manifest to verify
    import json
    with open(manifest_path, "r") as f:
        data = json.load(f)

    files = data["files"].keys()

    assert "file.txt" in files
    assert "keep_dir/file.txt" in files
    assert ".pvignore" in files

    assert "ignore_me.txt" not in files
    assert "ignore_dir/file.txt" not in files
    assert "keep_dir/ignore_nested.txt" not in files
