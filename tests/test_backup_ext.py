
import os
import tarfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from projectclone import backup


@pytest.fixture
def setup_test_environment(tmp_path):
    """Set up a test environment with a source directory and some files."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file1.txt").write_text("file1 content")
    (source_dir / "file2.txt").write_text("file2 content")
    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()
    (sub_dir / "file3.txt").write_text("file3 content")
    return source_dir, tmp_path / "dest"


def test_create_archive_error_handling(setup_test_environment):
    """Test error handling in create_archive."""
    source_dir, dest_dir = setup_test_environment
    dest_dir.mkdir()
    dest_temp_file = dest_dir / "test.tar.gz"

    with patch("tarfile.open", side_effect=Exception("Test error")):
        with pytest.raises(Exception, match="Test error"):
            backup.create_archive(source_dir, dest_temp_file)

    assert not dest_temp_file.exists()


def test_safe_symlink_create_and_clear_dangerous_bits(tmp_path):
    """Test _safe_symlink_create and _clear_dangerous_bits."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()

    # Test _safe_symlink_create
    src_file = src_dir / "file.txt"
    src_file.write_text("test")
    src_link = src_dir / "link"
    os.symlink(src_file, src_link)
    dst_link = dst_dir / "link"
    backup._safe_symlink_create(src_link, dst_link)
    assert dst_link.is_symlink()
    assert os.readlink(dst_link) == str(src_file)

    # Test _clear_dangerous_bits
    test_file = dst_dir / "test_file"
    test_file.write_text("test")
    os.chmod(test_file, 0o4755)  # Set setuid bit
    backup._clear_dangerous_bits(test_file)
    assert test_file.stat().st_mode & 0o4000 == 0


def test_copy_tree_atomic_manifest_creation(setup_test_environment):
    """Test manifest creation in copy_tree_atomic."""
    source_dir, dest_dir = setup_test_environment

    backup.copy_tree_atomic(
        source_dir,
        dest_dir,
        "test_backup",
        manifest=True,
        manifest_sha=True,
    )

    backup_dir = dest_dir / "test_backup"
    manifest_path = backup_dir / "MANIFEST.txt"
    sha_manifest_path = backup_dir / "MANIFEST_SHA256.txt"

    assert manifest_path.exists()
    assert sha_manifest_path.exists()

    with open(manifest_path, "r") as f:
        manifest_content = f.read()
        assert "file1.txt" in manifest_content
        assert "file2.txt" in manifest_content
        assert "subdir/file3.txt" in manifest_content

    with open(sha_manifest_path, "r") as f:
        sha_manifest_content = f.read()
        assert "file1.txt" in sha_manifest_content
        assert "file2.txt" in sha_manifest_content
        assert "subdir/file3.txt" in sha_manifest_content
