# projectclone/tests/test_backup_coverage_gaps.py


import os
import shutil
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from projectclone import backup

class TestBackupCoverageGaps:

    @pytest.fixture
    def setup_env(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "file1.txt").touch()
        return src, dest

    def test_atomic_move_fallback_precise(self, setup_env):
        src, dest = setup_env
        s = src / "f1"
        s.touch()
        d = dest / "f1"

        # Patch os.replace in projectclone.backup module
        with patch("projectclone.backup.os.replace", side_effect=OSError("Cross-device")):
            with patch("projectclone.backup.shutil.move") as mock_move:
                backup.atomic_move(s, d)
                mock_move.assert_called()

    def test_atomic_move_success(self, setup_env):
        src, dest = setup_env
        s = src / "f1"
        s.touch()
        d = dest / "f1"

        # Patch os.replace to succeed
        with patch("projectclone.backup.os.replace") as mock_replace:
            backup.atomic_move(s, d)
            mock_replace.assert_called()

    def test_create_archive_partial_cleanup_exists(self, setup_env):
        src, dest = setup_env
        dest_file = dest / "fail.tar.gz"

        # Ensure file exists and unlink is called
        dest_file.touch()

        with patch("tarfile.open", side_effect=Exception("Tar fail")):
            # Patch Path.exists to verify it was checked? No, just rely on logic.
            with pytest.raises(Exception):
                backup.create_archive(src, dest_file)

        assert not dest_file.exists()

    def test_copy_tree_atomic_log_nested_fail(self, setup_env):
        src, dest = setup_env
        (src / "f1").touch()
        log_fp = MagicMock()

        # Fail logging inside exception handler
        log_fp.write.side_effect = Exception("Log fail")

        with patch("shutil.copy2", side_effect=Exception("Copy fail")):
            # This should catch Copy fail, try to log, catch Log fail, and continue
            backup.copy_tree_atomic(src, dest, "backup", log_fp=log_fp)

        # Should not raise

    def test_rsync_fail_msg(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = b"out"
            mock_run.return_value.stderr = b"err"

            with pytest.raises(RuntimeError):
                backup.rsync_incremental(src, dest, "backup", None, log_fp=log_fp)

        log_content = str(log_fp.write.call_args_list)
        assert "rsync failed" in log_content

    def test_rsync_move_fail_msg(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

            with patch("projectclone.backup.atomic_move", side_effect=OSError("Move fail")):
                with pytest.raises(OSError):
                    backup.rsync_incremental(src, dest, "backup", None, log_fp=log_fp)

        log_content = str(log_fp.write.call_args_list)
        assert "Failed to move rsync temp dir" in log_content
