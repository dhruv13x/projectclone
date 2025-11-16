# tests/test_cli.py

import os
import sys
from pathlib import Path
from unittest.mock import patch

from projectclone.cli import main, parse_args


class TestCLI:
    def test_parse_args(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--dest", "/test", "--archive"])
        args = parse_args()
        assert args.short_note == "note"
        assert args.dest == "/test"
        assert args.archive is True

    @patch("projectclone.cli.walk_stats")
    @patch("projectclone.cli.os.statvfs")
    def test_main_dry_run(self, mock_statvfs, mock_walk, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--dry-run", "--dest", str(tmp_path)])
        mock_walk.return_value = (1, 100)
        mock_statvfs.return_value.f_frsize = 1024
        mock_statvfs.return_value.f_bavail = 1000
        main()
        captured = capsys.readouterr()
        assert "Dry run: no files will be written." in captured.out

    @patch("projectclone.cli.have_rsync", return_value=True)
    @patch("projectclone.cli.rsync_incremental")
    @patch("projectclone.cli.input", return_value="y")
    def test_main_incremental(self, mock_input, mock_rsync, mock_have, capsys, monkeypatch, tmp_path):
        cwd_mock = tmp_path / "cwd"
        cwd_mock.mkdir()
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--incremental", "--dest", str(tmp_path / "dest"), "--yes"])
        monkeypatch.setattr(Path, "cwd", lambda: cwd_mock)
        main()
        mock_rsync.assert_called_once()
        captured = capsys.readouterr()
        assert "Incremental backup created" in captured.out

    def test_cli_yes_flag_skips_prompt(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", ["run_backup", "--dest", str(tmp_path / "d"), "--dry-run", "--yes", "note"])
        main()  # No prompt, returns normally

    def test_main_dry_run_and_insufficient_space_warn(self, monkeypatch, tmp_path, capsys):
        tiny_src = tmp_path / "tiny"
        tiny_src.mkdir()
        (tiny_src / "only.txt").write_text("x")
        oldcwd = Path.cwd()
        os.chdir(str(tiny_src))
        try:
            monkeypatch.setattr(sys, "argv", ["run_backup", "--dest", str(tmp_path / "dest"), "--dry-run", "--yes", "note"])
            class StatVFS:
                f_frsize = 1024
                f_bavail = 0
            monkeypatch.setattr(os, "statvfs", lambda p: StatVFS())
            main()
            captured = capsys.readouterr()
            assert "WARNING: estimated backup size exceeds free space" in captured.out
            dest = tmp_path / "dest"
            assert dest.exists()
            backups = [p for p in dest.iterdir() if p.is_dir() and "-" in p.name]
            assert not backups  # No backup dirs
        finally:
            os.chdir(str(oldcwd))

    def test_logfile_contains_markers(self, tmp_path, monkeypatch):
        dest = tmp_path / "dest"
        dest.mkdir()
        monkeypatch.setattr(sys, "argv", ["run_backup", "--dest", str(dest), "--dry-run", "--yes", "note"])
        main()
        logs = list(dest.glob("backup_*_*.log"))
        assert logs
        txt = logs[0].read_text()
        assert "Starting backup for" in txt
        assert "Dry run completed" in txt

    @patch('projectclone.cli.create_archive')
    def test_main_archive_path_moves_into_dest_on_replace_failure(self, mock_create_archive, monkeypatch, tmp_path):
        archive_path = tmp_path / "archive.tar.gz"
        archive_path.touch()
        mock_create_archive.return_value = archive_path
        src = tmp_path / "cwd"
        src.mkdir()
        (src / "x.txt").write_text("1")
        oldcwd = os.getcwd()
        os.chdir(str(src))
        try:
            d = tmp_path / "dest"
            d.mkdir()
            monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("no")))
            monkeypatch.setattr(sys, "argv", ["run_backup", "--dest", str(d), "--archive", "--yes", "note"])
            main()
            tars = list(d.glob("*.tar.gz"))
            assert tars
        finally:
            os.chdir(oldcwd)
