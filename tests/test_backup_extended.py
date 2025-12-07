# projectclone/tests/test_backup_extended.py


import os
import sys
import shutil
import pytest
import tarfile
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from projectclone import backup, cleanup, rotation

class TestBackupExtended:

    @pytest.fixture
    def setup_env(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()
        (src / "file1.txt").touch()
        return src, dest

    # --- Atomic Move & Copy Tree Tests ---

    def test_copy_tree_atomic_logging_and_exclusions(self, setup_env):
        src, dest = setup_env
        (src / "exclude.txt").touch()
        log_fp = MagicMock()

        backup.copy_tree_atomic(
            src, dest, "backup",
            excludes=["exclude*"],
            log_fp=log_fp,
            manifest=True,
            manifest_sha=True
        )

        logs = str(log_fp.write.call_args_list)
        assert "Excluded" in logs
        assert "Manifest written" in logs
        assert "SHA manifest written" in logs
        assert "Backup moved into place" in logs

    def test_copy_tree_atomic_logging_errors(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()

        # Mock copy failure
        with patch("shutil.copy2", side_effect=Exception("Copy failed")):
            backup.copy_tree_atomic(src, dest, "backup", log_fp=log_fp)

        logs = str(log_fp.write.call_args_list)
        assert "ERROR copying" in logs

    def test_copy_tree_atomic_manifest_sha_fail(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()

        # Mock sha calculation failure
        # We patch the imported name in backup module
        with patch("projectclone.backup.sha256_of_file", side_effect=Exception("SHA Fail")):
             backup.copy_tree_atomic(src, dest, "backup", manifest_sha=True, log_fp=log_fp)

        logs = str(log_fp.write.call_args_list)
        assert "SHA error for" in logs

    def test_copy_tree_atomic_move_fail(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()

        with patch("projectclone.backup.atomic_move", side_effect=Exception("Move fail")):
            with pytest.raises(Exception):
                backup.copy_tree_atomic(src, dest, "backup", log_fp=log_fp)

        logs = str(log_fp.write.call_args_list)
        assert "Failed to move backup into place" in logs

    def test_atomic_move_fallback(self, setup_env):
        src, dest = setup_env
        s = src / "f1"
        s.touch()
        d = dest / "f1"

        with patch("os.replace", side_effect=OSError("Cross-device")):
            with patch("shutil.move") as mock_move:
                backup.atomic_move(s, d)
                mock_move.assert_called_with(str(s), str(d))

    def test_copy_tree_atomic_special_file_skip(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()

        with patch("os.walk", return_value=[(str(src), [], ["special"])]):
            with patch("pathlib.Path.is_file", return_value=False):
                with patch("pathlib.Path.is_symlink", return_value=False):
                    backup.copy_tree_atomic(src, dest, "backup", log_fp=log_fp)

        logs = str(log_fp.write.call_args_list)
        assert "Skipping special file" in logs

    def test_copy_tree_atomic_log_success_nested(self, setup_env):
        # Ensure logging happens inside loops/exception handlers successfully
        src, dest = setup_env
        (src / "f1").touch()
        log_fp = MagicMock()

        # Mock copy failure to trigger logging
        with patch("shutil.copy2", side_effect=Exception("Copy Fail")):
            backup.copy_tree_atomic(src, dest, "backup", log_fp=log_fp)

        # Verify log calls
        assert log_fp.write.called
        assert "Copy Fail" in str(log_fp.write.call_args_list)

    def test_copy_tree_atomic_log_nested_fail(self, setup_env):
        src, dest = setup_env
        (src / "f1").touch()
        log_fp = MagicMock()

        # Fail logging inside exception handler
        log_fp.write.side_effect = Exception("Log fail")

        with patch("shutil.copy2", side_effect=Exception("Copy fail")):
            # This should catch Copy fail, try to log, catch Log fail, and continue
            backup.copy_tree_atomic(src, dest, "backup", log_fp=log_fp)

    # --- Archive Creation Tests ---

    def test_create_archive_logging_and_checksum(self, setup_env):
        src, dest = setup_env
        dest_file = dest / "a.tar.gz"
        log_fp = MagicMock()

        backup.create_archive(src, dest_file, manifest_sha=True, log_fp=log_fp)

        logs = str(log_fp.write.call_args_list)
        assert "Creating archive at temp" in logs
        assert "Archive checksum written" in logs

    def test_create_archive_partial_cleanup(self, setup_env):
        src, dest = setup_env
        dest_file = dest / "fail.tar.gz"

        def broken_tar(*args, **kwargs):
            Path(args[0]).touch()
            raise Exception("Tar fail")

        with patch("tarfile.open", side_effect=broken_tar):
            with pytest.raises(Exception):
                backup.create_archive(src, dest_file)

        assert not dest_file.exists()

    def test_create_archive_log_branches(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()
        log_fp.write.side_effect = Exception("Log fail")
        backup.create_archive(src, dest / "a.tar.gz", log_fp=log_fp)

    # --- Rsync Tests ---

    def test_rsync_incremental_dry_run(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

            backup.rsync_incremental(src, dest, "backup", None, dry_run=True, log_fp=log_fp)

        logs = str(log_fp.write.call_args_list)
        assert "Rsync dry-run completed" in logs

    def test_rsync_incremental_failure(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b"err"

            with pytest.raises(RuntimeError):
                backup.rsync_incremental(src, dest, "backup", None, log_fp=log_fp)

        logs = str(log_fp.write.call_args_list)
        assert "rsync failed" in logs

    def test_rsync_incremental_move_fail(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            with patch("projectclone.backup.atomic_move", side_effect=OSError("Move fail")):
                with pytest.raises(OSError):
                    backup.rsync_incremental(src, dest, "backup", None, log_fp=log_fp)

        logs = str(log_fp.write.call_args_list)
        assert "Failed to move rsync temp dir" in logs

    def test_have_rsync_false(self):
        with patch("subprocess.run", side_effect=Exception("No rsync")):
            assert backup.have_rsync() is False

    def test_rsync_log_fail(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()
        log_fp.write.side_effect = Exception("Log fail")
        with patch("subprocess.run") as mock_run:
             mock_run.return_value.returncode = 0
             backup.rsync_incremental(src, dest, "backup", None, log_fp=log_fp)

    def test_rsync_fail_log_fail(self, setup_env):
        src, dest = setup_env
        log_fp = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b""

            log_fp.write.side_effect = Exception("Log fail")

            with pytest.raises(RuntimeError):
                 backup.rsync_incremental(src, dest, "backup", None, log_fp=log_fp)

    def test_clear_dangerous_bits_fail(self, tmp_path):
        f = tmp_path / "f"
        f.touch()

        with patch("pathlib.Path.stat", side_effect=Exception("Stat fail")):
            backup._clear_dangerous_bits(f)

    # --- Rotation Tests ---

    def test_rotate_backups_exception(self, setup_env):
        src, dest = setup_env
        b1 = dest / "2023-01-01_000000-proj-backup.tar.gz"
        b1.touch()
        os.utime(b1, (100, 100))
        b2 = dest / "2023-01-01_000001-proj-backup.tar.gz"
        b2.touch()
        os.utime(b2, (200, 200))

        with patch("pathlib.Path.unlink", side_effect=Exception("Delete fail")):
            rotation.rotate_backups(dest, 1, "proj")

    def test_rotate_backups_rmtree_exception(self, setup_env):
        src, dest = setup_env
        d1 = dest / "2023-01-01_000000-proj-backup"
        d1.mkdir()
        os.utime(d1, (100, 100))
        d2 = dest / "2023-01-01_000001-proj-backup"
        d2.mkdir()
        os.utime(d2, (200, 200))

        with patch("shutil.rmtree", side_effect=Exception("Rmtree fail")):
            rotation.rotate_backups(dest, 1, "proj")

    def test_create_archive_tarfile_open_error(self, setup_env):
        """
        Test that if tarfile.open fails, an exception is raised and cleanup occurs.
        """
        src, dest = setup_env
        dest_file = dest / "a.tar.gz"
        log_fp = MagicMock()

        with patch("tarfile.open", side_effect=tarfile.TarError("Test tar error")):
            with pytest.raises(tarfile.TarError):
                backup.create_archive(src, dest_file, log_fp=log_fp)

        # Ensure temp file is cleaned up
        assert not any(p.name.startswith("tmp_archive_") for p in dest.iterdir())
