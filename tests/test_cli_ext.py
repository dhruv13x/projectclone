# tests/test_cli_ext.py

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from projectclone.cli import main


@pytest.fixture
def temp_src(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file1.txt").write_text("content1")
    return src


@pytest.fixture
def temp_dest(tmp_path: Path):
    dest = tmp_path / "dest"
    dest.mkdir()
    return dest


class TestCliExt:
    @patch("projectclone.cli.create_archive")
    def test_main_archive_and_manifest(self, mock_create_archive, temp_src, temp_dest, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--archive", "--manifest", "--dest", str(temp_dest), "--yes"])
        monkeypatch.setattr(Path, "cwd", lambda: temp_src)

        # To prevent the function from raising an exception due to a non-existent file,
        # we'll create a dummy archive file.
        dummy_archive = temp_dest / "dummy_archive.tar.gz"
        dummy_archive.touch()
        mock_create_archive.return_value = dummy_archive

        main()

        assert mock_create_archive.call_args is not None
        call_args = mock_create_archive.call_args[0]
        assert len(call_args) >= 2
        assert isinstance(call_args[0], Path)
        assert isinstance(call_args[1], Path)
        captured = capsys.readouterr()
        assert "Archive created" in captured.out

    @patch("projectclone.cli.copy_tree_atomic")
    def test_main_incremental_backup(self, mock_copy_tree_atomic, temp_src, temp_dest, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--dest", str(temp_dest), "--yes"])
        monkeypatch.setattr(Path, "cwd", lambda: temp_src)
        main()
        mock_copy_tree_atomic.assert_called_once()
        captured = capsys.readouterr()
        assert "Folder backup created" in captured.out

    def test_main_dry_run_and_yes_flags(self, temp_src, temp_dest, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--dry-run", "--dest", str(temp_dest), "--yes"])
        monkeypatch.setattr(Path, "cwd", lambda: temp_src)
        with patch("projectclone.cli.input") as mock_input:
            main()
            mock_input.assert_not_called()
        captured = capsys.readouterr()
        assert "Dry run: no files will be written." in captured.out

    @patch("projectclone.cli.input", return_value="n")
    def test_main_user_prompt_no(self, mock_input, temp_src, temp_dest, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--dest", str(temp_dest)])
        monkeypatch.setattr(Path, "cwd", lambda: temp_src)

        with pytest.raises(SystemExit) as excinfo:
            main()

        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "Aborted by user" in captured.out

    @patch("projectclone.cli.have_rsync", return_value=False)
    def test_main_incremental_no_rsync(self, mock_have_rsync, temp_src, temp_dest, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--incremental", "--dest", str(temp_dest), "--yes"])
        monkeypatch.setattr(Path, "cwd", lambda: temp_src)

        with pytest.raises(SystemExit) as excinfo:
            main()

        assert excinfo.value.code == 2
        captured = capsys.readouterr()
        assert "incremental requested but rsync not found" in captured.out

    @patch("pathlib.Path.open")
    def test_main_log_fp_error(self, mock_log_open, temp_src, temp_dest, capsys, monkeypatch):
        mock_log_open.side_effect = IOError("Test error")
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--dest", str(temp_dest), "--yes"])
        monkeypatch.setattr(Path, "cwd", lambda: temp_src)

        with patch("projectclone.cli.copy_tree_atomic") as mock_copy_tree_atomic:
            main()

        captured = capsys.readouterr()
        assert "[INFO] Starting backup for" in captured.out

    @patch("pathlib.Path.mkdir")
    def test_main_ensure_dir_error(self, mock_mkdir, temp_src, temp_dest, capsys, monkeypatch):
        mock_mkdir.side_effect = OSError("Test error")
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--dest", str(temp_dest), "--yes"])
        monkeypatch.setattr(Path, "cwd", lambda: temp_src)

        with pytest.raises(SystemExit) as excinfo:
            main()

        assert excinfo.value.code == 2
        captured = capsys.readouterr()
        assert "ERROR:" in captured.out

    @patch("shutil.disk_usage")
    def test_main_insufficient_space(self, mock_disk_usage, temp_src, temp_dest, capsys, monkeypatch):
        # Mock disk_usage to return little free space (10 bytes)
        # (total, used, free)
        mock_disk_usage.return_value = (1000, 990, 10)
        
        # Mock walk_stats to return large size (100 bytes)
        # Also mock copy_tree_atomic so it doesn't actually try to copy
        with patch("projectclone.cli.walk_stats", return_value=(5, 100)), \
             patch("projectclone.cli.copy_tree_atomic"):
             
             monkeypatch.setattr(sys, "argv", ["projectclone", "note", "--dest", str(temp_dest), "--yes"])
             monkeypatch.setattr(Path, "cwd", lambda: temp_src)
             
             main()

        captured = capsys.readouterr()
        assert "WARNING: estimated backup size exceeds free space" in captured.out

    @patch("shutil.disk_usage")
    def test_main_statvfs_error(self, mock_disk_usage, temp_src, temp_dest, capsys, monkeypatch):
        mock_disk_usage.side_effect = OSError("Stat fail")
        
        with patch("projectclone.cli.walk_stats", return_value=(5, 100)), \
             patch("projectclone.cli.copy_tree_atomic"):
             
             monkeypatch.setattr(sys, "argv", ["projectclone", "note", "--dest", str(temp_dest), "--yes"])
             monkeypatch.setattr(Path, "cwd", lambda: temp_src)
             
             main()

        captured = capsys.readouterr()
        # Should print "Could not determine destination free space"
        assert "Could not determine destination free space" in captured.out

    @patch("projectclone.cli.atomic_move")
    @patch("projectclone.cli.create_archive")
    def test_main_archive_move_fail(self, mock_create, mock_move, temp_src, temp_dest, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--archive", "--dest", str(temp_dest), "--yes"])
        monkeypatch.setattr(Path, "cwd", lambda: temp_src)
        
        dummy_archive = temp_dest / "dummy_archive.tar.gz"
        dummy_archive.touch()
        mock_create.return_value = dummy_archive
        
        mock_move.side_effect = OSError("Move failed")

        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2
        
        captured = capsys.readouterr()
        assert "Move failed" in captured.out

    @patch("projectclone.cli.atomic_move")
    @patch("projectclone.cli.create_archive")
    def test_main_archive_sha_move_fail(self, mock_create, mock_move, temp_src, temp_dest, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--archive", "--dest", str(temp_dest), "--yes"])
        monkeypatch.setattr(Path, "cwd", lambda: temp_src)
        
        dummy_archive = temp_dest / "dummy_archive.tar.gz"
        dummy_archive.touch()
        # Create checksum file
        (temp_dest / "dummy_archive.tar.gz.sha256").touch()
        
        mock_create.return_value = dummy_archive
        
        # First move (archive) succeeds, second move (sha) fails
        mock_move.side_effect = [None, OSError("SHA move failed")]

        main()
        
        captured = capsys.readouterr()
        assert "Archive created" in captured.out

    @patch("projectclone.cleanup.cleanup_state.unregister_tmp_file")
    @patch("projectclone.cli.create_archive")
    def test_main_cleanup_unregister_fail(self, mock_create, mock_unregister, temp_src, temp_dest, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--archive", "--dest", str(temp_dest), "--yes"])
        monkeypatch.setattr(Path, "cwd", lambda: temp_src)
        
        dummy_archive = temp_dest / "dummy_archive.tar.gz"
        dummy_archive.touch()
        mock_create.return_value = dummy_archive
        
        mock_unregister.side_effect = Exception("Unregister fail")
        
        main()
        captured = capsys.readouterr()
        assert "Archive created" in captured.out

    @patch("pathlib.Path.open")
    def test_main_log_write_fail(self, mock_log_open, temp_src, temp_dest, capsys, monkeypatch):
        # Mock file object that fails on write
        mock_file = MagicMock()
        mock_file.write.side_effect = IOError("Write fail")
        mock_log_open.return_value = mock_file
        
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--dest", str(temp_dest), "--yes"])
        monkeypatch.setattr(Path, "cwd", lambda: temp_src)
        
        with patch("projectclone.cli.copy_tree_atomic"):
            main()
            
        # Should run without crashing
        captured = capsys.readouterr()
        assert "Folder backup created" in captured.out
