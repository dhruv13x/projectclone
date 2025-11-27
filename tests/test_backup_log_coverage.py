# projectclone/tests/test_backup_log_coverage.py


import os
import sys
import pytest
import io
import stat
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path

from projectclone import backup
from projectclone import cli as projectclone_cli

# Helper for failing writes
class FailingBuffer(io.StringIO):
    def write(self, s):
        raise OSError("Write failed")

class TestBackupLogCoverage:
    """Tests designed to hit exception paths in backup.py using faulty log/file objects."""

    def test_backup_log_exceptions_real_object(self, tmp_path):
        # Using a custom object that looks like a file but raises on write
        # This ensures we hit the 'except Exception: pass' blocks
        src = tmp_path / "src"
        src.mkdir()
        (src / "file1").touch()
        dest = tmp_path / "dest"
        dest.mkdir()

        failing_log = FailingBuffer()

        # Test copy_tree_atomic logging failures
        backup.copy_tree_atomic(src, dest, "backup1", log_fp=failing_log)

        # Test create_archive logging failures
        archive_dest = dest / "backup.tar.gz"
        backup.create_archive(src, archive_dest, log_fp=failing_log)

        # Test symlink failure logging
        (src / "link").symlink_to("file1")
        backup._safe_symlink_create(src / "link", dest / "link", log_fp=failing_log)

    def test_backup_symlink_read_error(self, tmp_path):
        # Mock os.readlink to fail
        src = tmp_path / "src"
        src.mkdir()
        link = src / "link"
        link.touch() # Not a symlink, but we pretend

        dest = tmp_path / "dest"
        dest.mkdir()

        with patch("os.readlink", side_effect=OSError("Readlink fail")):
            log_fp = MagicMock()
            backup._safe_symlink_create(link, dest / "link_dest", log_fp=log_fp)
            log_fp.write.assert_called()

    def test_backup_log_branches_mock(self, tmp_path):
        """Additional coverage for specific functions using standard Mock"""
        src = tmp_path / "src"
        src.mkdir()
        (src / "f1").touch()
        dest = tmp_path / "dest"
        dest.mkdir()

        log_fp = MagicMock()
        log_fp.write.side_effect = Exception("Log fail")

        # copy_tree_atomic log fail
        backup.copy_tree_atomic(src, dest, "backup", log_fp=log_fp)

        # create_archive log fail
        backup.create_archive(src, dest / "a.tar.gz", log_fp=log_fp)

    def test_rsync_log_branches(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        log_fp = MagicMock()
        log_fp.write.side_effect = Exception("Log fail")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            backup.rsync_incremental(src, dest, "backup", None, log_fp=log_fp)
