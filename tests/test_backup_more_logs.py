# projectclone/tests/test_backup_more_logs.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from projectclone import backup

class TestBackupMoreLogs:

    def test_copy_tree_atomic_success_logging(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "f1").touch()
        dest = tmp_path / "dest"
        dest.mkdir()

        log_fp = MagicMock()

        # Mock copy2 to succeed
        with patch("shutil.copy2"):
            backup.copy_tree_atomic(src, dest, "backup", log_fp=log_fp)

        # Check logs
        logs = str(log_fp.write.call_args_list)
        assert "Copying" in logs
        assert "Backup moved into place" in logs

    def test_create_archive_success_logging(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "f1").touch()
        dest = tmp_path / "dest"
        dest.mkdir()

        log_fp = MagicMock()

        backup.create_archive(src, dest / "a.tar.gz", log_fp=log_fp)

        logs = str(log_fp.write.call_args_list)
        assert "Creating archive" in logs

    def test_rsync_success_logging(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        log_fp = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            backup.rsync_incremental(src, dest, "backup", None, log_fp=log_fp)

        logs = str(log_fp.write.call_args_list)
        assert "Running rsync" in logs
        assert "Rsync backup moved into place" in logs
