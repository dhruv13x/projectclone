# projectclone/tests/test_cas_symlinks.py

import os
import pytest
from pathlib import Path
from projectclone import cas_engine

@pytest.fixture
def symlink_setup(tmp_path):
    """
    Creates a setup with:
    - file1.txt (content: "original")
    - link_to_file (symlink -> file1.txt)
    """
    source = tmp_path / "source"
    vault = tmp_path / "vault"
    source.mkdir()
    vault.mkdir()

    file1 = source / "file1.txt"
    file1.write_text("original")

    link = source / "link_to_file"
    try:
        link.symlink_to("file1.txt")
    except OSError:
        pytest.skip("Symlinks not supported on this platform")

    return source, vault, file1, link

def test_cas_backup_follows_symlinks(symlink_setup):
    """Test that follow_symlinks=True stores the target content (hash)."""
    source, vault, file1, link = symlink_setup

    # Backup with follow_symlinks=True
    manifest_path = cas_engine.backup_to_vault(str(source), str(vault), follow_symlinks=True)

    # Verify manifest
    import json
    with open(manifest_path) as f:
        data = json.load(f)
    
    files = data["files"]
    assert "link_to_file" in files
    # Should be stored as a file (with hash), NOT type="symlink"
    assert "hash" in files["link_to_file"]
    assert files["link_to_file"].get("type") != "symlink"
    
    # The hash should match the original file's hash
    assert files["link_to_file"]["hash"] == files["file1.txt"]["hash"]

def test_cas_backup_preserves_symlinks(symlink_setup):
    """Test that follow_symlinks=False stores the symlink metadata."""
    source, vault, file1, link = symlink_setup

    # Backup with follow_symlinks=False (default behavior usually, but explicit here)
    manifest_path = cas_engine.backup_to_vault(str(source), str(vault), follow_symlinks=False)

    # Verify manifest
    import json
    with open(manifest_path) as f:
        data = json.load(f)
    
    files = data["files"]
    assert "link_to_file" in files
    # Should be stored as type="symlink"
    assert files["link_to_file"].get("type") == "symlink"
    assert files["link_to_file"]["target"] == "file1.txt"
