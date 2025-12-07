# projectclone/tests/test_backup_exclude_symlinks.py

import os
import tarfile
import pytest
from pathlib import Path
from projectclone.backup import create_archive

@pytest.fixture
def symlink_setup(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    
    # Regular file
    (source / "file.txt").write_text("content")
    
    # Symlink
    link = source / "link"
    try:
        link.symlink_to("file.txt")
    except OSError:
        pytest.skip("Symlinks not supported")
        
    return source

def test_create_archive_defaults_includes_symlinks(symlink_setup, tmp_path):
    """Default: symlinks are included (dereferenced by default logic of backup.py unless preserve_symlinks is True)."""
    # backup.py: preserve_symlinks=False by default -> dereference=True -> content copied
    # Wait, my new manual walk implementation in create_archive needs to ensure this behavior is preserved.
    
    archive = tmp_path / "archive.tar.gz"
    create_archive(symlink_setup, archive, preserve_symlinks=False)
    
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        # arcname logic: top_level/file.txt
        top = symlink_setup.name
        assert f"{top}/file.txt" in names
        assert f"{top}/link" in names
        
        # Verify 'link' is a file (content copied)
        info = tar.getmember(f"{top}/link")
        assert info.isfile()

def test_create_archive_preserve_symlinks(symlink_setup, tmp_path):
    """Test preserve_symlinks=True."""
    archive = tmp_path / "archive_preserve.tar.gz"
    create_archive(symlink_setup, archive, preserve_symlinks=True)
    
    with tarfile.open(archive, "r:gz") as tar:
        top = symlink_setup.name
        info = tar.getmember(f"{top}/link")
        assert info.issym()

def test_create_archive_exclude_symlinks(symlink_setup, tmp_path):
    """Test exclude_symlinks=True."""
    archive = tmp_path / "archive_exclude.tar.gz"
    create_archive(symlink_setup, archive, exclude_symlinks=True)
    
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        top = symlink_setup.name
        assert f"{top}/file.txt" in names
        assert f"{top}/link" not in names
