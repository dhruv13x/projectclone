# tests/test_backup_ext.py

import os
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from projectclone.backup import (
    create_archive,
    copy_tree_atomic,
    rsync_incremental,
    _clear_dangerous_bits,
)
from projectclone.utils import sha256_of_file


@pytest.fixture
def temp_dir(tmp_path: Path):
    """Fixture for a populated temp source dir with files, subdirs, symlinks."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "file1.txt").write_text("content1")
    (src / "file2.bin").write_bytes(b"binary")
    sub = src / "subdir"
    sub.mkdir()
    (sub / "file3.txt").write_text("content3")
    return src


@pytest.fixture
def temp_dest(tmp_path: Path):
    """Temp dest base dir."""
    dest = tmp_path / "dest"
    dest.mkdir()
    yield dest


@pytest.fixture
def mock_log_fp():
    import io
    return io.StringIO()


class TestCreateArchiveExt:
    @patch("tarfile.open")
    def test_create_archive_tarfile_error(self, mock_tarfile_open, temp_dir, temp_dest, mock_log_fp):
        mock_tarfile_open.side_effect = tarfile.TarError("Failed to create tar")
        with pytest.raises(tarfile.TarError):
            create_archive(temp_dir, temp_dest / "test", log_fp=mock_log_fp)
        assert not (temp_dest / "test.tar.gz").exists()

    @patch("projectclone.backup.sha256_of_file")
    def test_create_archive_sha_error(self, mock_sha256, temp_dir, temp_dest, mock_log_fp):
        mock_sha256.side_effect = IOError("Failed to read file")
        create_archive(temp_dir, temp_dest / "test", manifest_sha=True, log_fp=mock_log_fp)
        log_content = mock_log_fp.getvalue()
        assert "Error writing archive checksum" in log_content

    def test_create_archive_with_special_file(self, temp_dir, temp_dest):
        # This test is primarily for coverage of the error handling in shutil.copy2
        # and may not be applicable to create_archive directly, but we can simulate a similar scenario
        # by trying to archive a non-file/dir.
        special_file = temp_dir / "special"
        if hasattr(os, "mkfifo"):
            os.mkfifo(special_file)
            with patch("tarfile.open") as mock_tar_open:
                mock_tar_open.side_effect = Exception("Cannot handle special file")
                with pytest.raises(Exception):
                    create_archive(special_file, temp_dest / "special_archive.tar.gz")
        else:
            pytest.skip("os.mkfifo not available on this system")


class TestCopyTreeAtomicExt:
    @patch("shutil.rmtree")
    def test_copy_tree_atomic_tmp_dir_exists_error(self, mock_rmtree, temp_dir, temp_dest):
        # Simulate that the temporary directory exists and cannot be removed
        tmp_dir = temp_dest / f".tmp_backup_{os.getpid()}"
        tmp_dir.mkdir()
        mock_rmtree.side_effect = OSError("Permission denied")

        # The function should still proceed without raising an exception.
        # This tests the non-fatal nature of the initial cleanup.
        copy_tree_atomic(temp_dir, temp_dest, "backup")

    def test_copy_tree_atomic_skips_special_files(self, temp_dir, temp_dest, mock_log_fp):
        if hasattr(os, "mkfifo"):
            special_file = temp_dir / "fifo"
            os.mkfifo(special_file)

            final_dest = copy_tree_atomic(temp_dir, temp_dest, "backup", log_fp=mock_log_fp)

            assert not (final_dest / "fifo").exists()
            log_content = mock_log_fp.getvalue()
            assert "Skipping special file" in log_content
        else:
            pytest.skip("os.mkfifo not available on this system")

    @patch("projectclone.backup.sha256_of_file")
    def test_copy_tree_atomic_sha_manifest_error(self, mock_sha256, temp_dir, temp_dest, mock_log_fp):
        mock_sha256.side_effect = IOError("Read error")
        copy_tree_atomic(temp_dir, temp_dest, "backup", manifest_sha=True, log_fp=mock_log_fp)
        log_content = mock_log_fp.getvalue()
        assert "SHA error for" in log_content

    @patch("projectclone.backup.atomic_move")
    def test_copy_tree_atomic_final_move_error(self, mock_atomic_move, temp_dir, temp_dest, mock_log_fp):
        mock_atomic_move.side_effect = OSError("Move failed")
        with pytest.raises(OSError):
            copy_tree_atomic(temp_dir, temp_dest, "backup", log_fp=mock_log_fp)
        log_content = mock_log_fp.getvalue()
        assert "Failed to move backup into place" in log_content


class TestRsyncIncrementalExt:
    @patch("shutil.rmtree")
    def test_rsync_incremental_tmp_dir_exists_error(self, mock_rmtree, temp_dir, temp_dest):
        tmp_dir = temp_dest / f".tmp_rsync_backup_{os.getpid()}"
        tmp_dir.mkdir()
        mock_rmtree.side_effect = OSError("Permission denied")

        with patch("subprocess.run") as mock_subprocess_run:
            mock_subprocess_run.return_value = MagicMock(returncode=0)
            rsync_incremental(temp_dir, temp_dest, "rsync_backup", link_dest=None)

    @patch("subprocess.run")
    def test_rsync_incremental_failure_cleanup_error(self, mock_subprocess_run, temp_dir, temp_dest):
        mock_subprocess_run.return_value = MagicMock(returncode=1, stdout=b"", stderr=b"")
        with patch("shutil.rmtree") as mock_rmtree:
            mock_rmtree.side_effect = OSError("Cleanup failed")
            with pytest.raises(RuntimeError):
                rsync_incremental(temp_dir, temp_dest, "rsync_backup", link_dest=None)

    @patch("projectclone.backup.atomic_move")
    def test_rsync_incremental_final_move_error(self, mock_atomic_move, temp_dir, temp_dest, mock_log_fp):
        mock_atomic_move.side_effect = OSError("Move failed")
        with patch("subprocess.run") as mock_subprocess_run:
            mock_subprocess_run.return_value = MagicMock(returncode=0)
            with pytest.raises(OSError):
                rsync_incremental(temp_dir, temp_dest, "rsync_backup", link_dest=None, log_fp=mock_log_fp)
            log_content = mock_log_fp.getvalue()
            assert "Failed to move rsync temp dir into place" in log_content


class TestClearDangerousBits:
    def test_clear_dangerous_bits(self, tmp_path):
        f = tmp_path / "test"
        f.touch()
        # Set the setuid and setgid bits
        mode = f.stat().st_mode
        os.chmod(f, mode | stat.S_ISUID | stat.S_ISGID)

        _clear_dangerous_bits(f)

        new_mode = f.stat().st_mode
        assert not (new_mode & stat.S_ISUID)
        assert not (new_mode & stat.S_ISGID)

    def test_clear_dangerous_bits_chmod_error(self, tmp_path):
        f = tmp_path / "test"
        f.touch()

        with patch("os.chmod") as mock_chmod:
            mock_chmod.side_effect = OSError("Test error")
            _clear_dangerous_bits(f)
            # The function should not raise an exception
