import os
import shutil
import stat
import tarfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import subprocess
import pytest

from projectclone.backup import (
    atomic_move,
    create_archive,
    _safe_symlink_create,
    _clear_dangerous_bits,
    copy_tree_atomic,
    rsync_incremental,
    have_rsync,
)
from projectclone.cleanup import cleanup_state
from projectclone.scanner import matches_excludes, walk_stats
from projectclone.utils import ensure_dir, sha256_of_file, make_unique_path, human_size


@pytest.fixture
def setup_test_env(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "file1.txt").write_text("content1")
    (src_dir / "file2.txt").write_text("content2")
    (src_dir / "subdir").mkdir()
    (src_dir / "subdir" / "file3.txt").write_text("content3")
    return src_dir, tmp_path


@pytest.fixture
def mock_log_fp():
    mock_file = MagicMock()
    mock_file.write.return_value = None
    return mock_file


class TestCreateArchiveCoverage:
    def test_create_archive_tarfile_error_removes_partial_archive(self, tmp_path, mock_log_fp):
        src = tmp_path / "non_existent_dir"
        dest_temp_file = tmp_path / "archive.tar.gz"

        with patch("tarfile.open", side_effect=tarfile.ReadError("mock error")):
            with pytest.raises(tarfile.ReadError):
                create_archive(src, dest_temp_file, log_fp=mock_log_fp)

        assert not dest_temp_file.exists()
        mock_log_fp.write.assert_called_once() # Expect the log call before tarfile.open fails

    def test_create_archive_sha_error_handled_gracefully(self, setup_test_env, tmp_path, mock_log_fp):
        src_dir, _ = setup_test_env
        dest_temp_file = tmp_path / "archive.tar.gz"

        with patch("projectclone.backup.sha256_of_file", side_effect=Exception("SHA error")):
            archive_path = create_archive(src_dir, dest_temp_file, manifest_sha=True, log_fp=mock_log_fp)

        assert archive_path.exists()
        assert not (tmp_path / "archive.tar.gz.sha256").exists()
        mock_log_fp.write.assert_any_call("Error writing archive checksum: SHA error\n")

    def test_create_archive_log_fp_write_error_handled(self, setup_test_env, tmp_path):
        src_dir, _ = setup_test_env
        dest_temp_file = tmp_path / "archive.tar.gz"
        mock_log_fp = MagicMock()
        mock_log_fp.write.side_effect = Exception("Log write error")

        archive_path = create_archive(src_dir, dest_temp_file, log_fp=mock_log_fp)
        assert archive_path.exists()
        # The error in log_fp.write should not prevent archive creation
        assert mock_log_fp.write.called


class TestSafeSymlinkCreateCoverage:
    def test_safe_symlink_create_readlink_fails(self, tmp_path, mock_log_fp):
        src_link = tmp_path / "non_existent_symlink"
        dst = tmp_path / "dest_link"

        _safe_symlink_create(src_link, dst, log_fp=mock_log_fp)
        assert not dst.exists()
        mock_log_fp.write.assert_any_call(f"Could not read symlink target for {src_link}: [Errno 2] No such file or directory: '{src_link}'\n")

    def test_safe_symlink_create_dst_unlink_fails(self, tmp_path, mock_log_fp):
        target = tmp_path / "target_file"
        target.write_text("target content")
        src_link = tmp_path / "src_link"
        src_link.symlink_to(target)
        dst = tmp_path / "dest_link"
        dst.write_text("existing content")  # Make it a file, not a symlink

        with patch.object(Path, "unlink", side_effect=OSError("unlink error")):
            _safe_symlink_create(src_link, dst, log_fp=mock_log_fp)
            # The symlink creation should still fail or not happen, but the unlink error should be handled
            assert dst.exists()  # Original file should still exist
            # Check for a substring in the log message, as the full path can vary
            assert any("Symlink create failed for" in call_args[0][0] and "File exists" in call_args[0][0]
                       for call_args in mock_log_fp.write.call_args_list)

    def test_safe_symlink_create_symlink_fails(self, tmp_path, mock_log_fp):
        target = tmp_path / "target_file"
        target.write_text("target content")
        src_link = tmp_path / "src_link"
        src_link.symlink_to(target)
        dst = tmp_path / "dest_link"

        with patch("os.symlink", side_effect=OSError("symlink error")):
            _safe_symlink_create(src_link, dst, log_fp=mock_log_fp)
            assert not dst.exists()
            mock_log_fp.write.assert_any_call(f"Symlink create failed for {src_link} -> {target}: symlink error\n")


class TestClearDangerousBitsCoverage:
    def test_clear_dangerous_bits_chmod_fails(self, tmp_path):
        test_file = tmp_path / "test_file"
        test_file.write_text("content")
        test_file.chmod(0o777 | stat.S_ISUID)  # Set some dangerous bits

        with patch("os.chmod", side_effect=OSError("chmod error")):
            _clear_dangerous_bits(test_file)
            # Should not raise an error, just pass
            assert test_file.exists()


class TestCopyTreeAtomicCoverage:
    def test_copy_tree_atomic_shutil_copy2_fails(self, setup_test_env, tmp_path, mock_log_fp):
        src_dir, dest_parent = setup_test_env
        dest_name = "backup"

        with patch("shutil.copy2", side_effect=OSError("copy error")):
            final_dest = copy_tree_atomic(src_dir, dest_parent, dest_name, log_fp=mock_log_fp)

            # The atomic move should still happen, but the log should show the copy error
            assert final_dest.exists()
            mock_log_fp.write.assert_any_call(f"ERROR copying {src_dir / 'file1.txt'}: copy error\n")

    def test_copy_tree_atomic_manifest_write_fails(self, setup_test_env, tmp_path, mock_log_fp):
        src_dir, dest_parent = setup_test_env
        dest_name = "backup"

        with patch.object(Path, "open", side_effect=OSError("manifest write error")):
            final_dest = copy_tree_atomic(src_dir, dest_parent, dest_name, manifest=True, log_fp=mock_log_fp)

            assert final_dest.exists()
            mock_log_fp.write.assert_any_call("Manifest write failed: manifest write error\n")

    def test_copy_tree_atomic_sha_manifest_write_fails(self, setup_test_env, tmp_path, mock_log_fp):
        src_dir, dest_parent = setup_test_env
        dest_name = "backup"

        with patch.object(Path, "open", side_effect=OSError("sha manifest write error")):
            final_dest = copy_tree_atomic(src_dir, dest_parent, dest_name, manifest_sha=True, log_fp=mock_log_fp)

            assert final_dest.exists()
            mock_log_fp.write.assert_any_call("SHA manifest write failed: sha manifest write error\n")

    def test_copy_tree_atomic_final_move_fails(self, setup_test_env, tmp_path, mock_log_fp):
        src_dir, dest_parent = setup_test_env
        dest_name = "backup"

        with patch("projectclone.backup.atomic_move", side_effect=OSError("atomic move error")):
            with pytest.raises(OSError, match="atomic move error"):
                copy_tree_atomic(src_dir, dest_parent, dest_name, log_fp=mock_log_fp)

            # The tmp_dir should still exist for inspection
            tmp_dir = dest_parent / f".tmp_{dest_name}_{os.getpid()}"
            assert tmp_dir.is_dir()
            mock_log_fp.write.assert_any_call("Failed to move backup into place: atomic move error\n")

    def test_copy_tree_atomic_tmp_dir_exists_cleanup(self, setup_test_env, tmp_path, mock_log_fp):
        src_dir, dest_parent = setup_test_env
        dest_name = "backup"
        existing_tmp_dir = dest_parent / f".tmp_{dest_name}_{os.getpid()}"
        existing_tmp_dir.mkdir()
        (existing_tmp_dir / "old_file.txt").write_text("old content")

        copy_tree_atomic(src_dir, dest_parent, dest_name, log_fp=mock_log_fp)

        assert not existing_tmp_dir.exists()  # Should be removed
        final_dest = dest_parent / dest_name
        assert final_dest.exists()
        assert (final_dest / "file1.txt").exists()

    def test_copy_tree_atomic_show_progress(self, setup_test_env, tmp_path, capsys):
        src_dir, dest_parent = setup_test_env
        dest_name = "backup"

        copy_tree_atomic(src_dir, dest_parent, dest_name, show_progress=True, progress_interval=1)
        captured = capsys.readouterr()
        assert "Copied 1/3 files ..." in captured.out
        assert "Copied 2/3 files ..." in captured.out
        assert "Copied 3/3 files ..." in captured.out

    def test_copy_tree_atomic_skips_special_files(self, setup_test_env, tmp_path, mock_log_fp):
        src_dir, dest_parent = setup_test_env
        dest_name = "backup"

        # Create a named pipe (FIFO) - a type of special file
        fifo_path = src_dir / "my_fifo"
        os.mkfifo(fifo_path)

        final_dest = copy_tree_atomic(src_dir, dest_parent, dest_name, log_fp=mock_log_fp)

        assert final_dest.exists()
        assert not (final_dest / "my_fifo").exists()
        mock_log_fp.write.assert_any_call(f"Skipping special file: {fifo_path}\n")

    def test_copy_tree_atomic_log_fp_write_error_handled(self, setup_test_env, tmp_path):
        src_dir, dest_parent = setup_test_env
        dest_name = "backup"
        mock_log_fp = MagicMock()
        mock_log_fp.write.side_effect = Exception("Log write error")

        final_dest = copy_tree_atomic(src_dir, dest_parent, dest_name, log_fp=mock_log_fp)
        assert final_dest.exists()
        # The error in log_fp.write should not prevent copy_tree_atomic from completing
        assert mock_log_fp.write.called


class TestRsyncIncrementalCoverage:
    def test_rsync_incremental_tmp_dir_exists_cleanup(self, setup_test_env, tmp_path, mock_log_fp):
        src_dir, dest_parent = setup_test_env
        dest_name = "rsync_backup"
        existing_tmp_dir = dest_parent / f".tmp_{dest_name}_{os.getpid()}"
        existing_tmp_dir.mkdir()
        (existing_tmp_dir / "old_file.txt").write_text("old content")

        # Mock rsync to succeed
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
            rsync_incremental(src_dir, dest_parent, dest_name, link_dest=None, log_fp=mock_log_fp)

        assert not existing_tmp_dir.exists()  # Should be removed
        final_dest = dest_parent / dest_name
        assert final_dest.exists()

    def test_rsync_incremental_failure_cleanup_error_handled(self, setup_test_env, tmp_path, mock_log_fp):
        src_dir, dest_parent = setup_test_env
        dest_name = "rsync_backup"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout=b"rsync stdout", stderr=b"rsync stderr")
            with patch("shutil.rmtree", side_effect=OSError("rmtree error")):
                with pytest.raises(RuntimeError, match="rsync failed"):
                    rsync_incremental(src_dir, dest_parent, dest_name, link_dest=None, log_fp=mock_log_fp)

            # The rmtree error during cleanup should not prevent the RuntimeError from rsync failure
            mock_log_fp.write.assert_any_call("rsync failed: 1\nstdout:\nrsync stdout\nstderr:\nrsync stderr\n")

    def test_rsync_incremental_final_move_error_handled(self, setup_test_env, tmp_path, mock_log_fp):
        src_dir, dest_parent = setup_test_env
        dest_name = "rsync_backup"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
            with patch("projectclone.backup.atomic_move", side_effect=OSError("atomic move error")):
                with pytest.raises(OSError, match="atomic move error"):
                    rsync_incremental(src_dir, dest_parent, dest_name, link_dest=None, log_fp=mock_log_fp)

                # The tmp_dir should still exist for inspection
                tmp_dir = dest_parent / f".tmp_{dest_name}_{os.getpid()}"
                assert tmp_dir.is_dir()
                mock_log_fp.write.assert_any_call("Failed to move rsync temp dir into place: atomic move error\n")

    def test_rsync_incremental_log_fp_write_error_handled(self, setup_test_env, tmp_path):
        src_dir, dest_parent = setup_test_env
        dest_name = "rsync_backup"
        mock_log_fp = MagicMock()
        mock_log_fp.write.side_effect = Exception("Log write error")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
            rsync_incremental(src_dir, dest_parent, dest_name, link_dest=None, log_fp=mock_log_fp)

        # The error in log_fp.write should not prevent rsync_incremental from completing
        assert mock_log_fp.write.called

    def test_have_rsync_failure(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert not have_rsync()
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "rsync")):
            assert not have_rsync()