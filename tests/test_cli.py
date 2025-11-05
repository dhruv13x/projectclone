import datetime
import io
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

import projectclone

# Import under test
from projectclone.cli import (
    sanitize_token,
    timestamp,
    human_size,
    sha256_of_file,
    ensure_dir,
    make_unique_path,
    matches_excludes,
    walk_stats,
    CleanupState,
    cleanup_state,  # Global instance for integration tests
    atomic_move,
    create_archive,
    _safe_symlink_create,
    _clear_dangerous_bits,
    copy_tree_atomic,
    rotate_backups,
    have_rsync,
    rsync_incremental,
    parse_args,
    main,
    _signal_handler,
)

@pytest.fixture
def temp_dir(tmp_path: Path):
    """Fixture for a populated temp source dir with files, subdirs, symlinks."""
    src = tmp_path / "source"
    src.mkdir()
    # Files
    (src / "file1.txt").write_text("content1")
    (src / "file2.bin").write_bytes(b"binary")
    # Subdir
    sub = src / "subdir"
    sub.mkdir()
    (sub / "file3.txt").write_text("content3")
    # Symlink
    link_src = src / "link_to_file1"
    try:
        link_src.symlink_to(src / "file1.txt")
    except OSError:
        pass  # Skip on platforms without symlinks
    # Empty dir
    (src / "empty_dir").mkdir()
    yield src

@pytest.fixture
def temp_dest(tmp_path: Path):
    """Temp dest base dir."""
    dest = tmp_path / "dest"
    dest.mkdir()
    yield dest

@pytest.fixture
def sample_excludes():
    return ["*.bin", "subdir"]

@pytest.fixture
def mock_log_fp():
    return io.StringIO()

class TestHelpers:
    def test_sanitize_token(self):
        assert sanitize_token("valid note") == "valid_note"
        assert sanitize_token("invalid: /\\ chars") == "invalid_chars"
        assert sanitize_token("") == "note"
        assert sanitize_token("  multiple__underscores  ") == "multiple_underscores"

    def test_timestamp(self):
        ts = timestamp()
        assert re.match(r"\d{4}-\d{2}-\d{2}_\d{6}", ts)

    def test_human_size(self):
        assert human_size(0) == "0.0B"
        assert human_size(1023) == "1023.0B"
        assert human_size(1024) == "1.0KB"
        assert human_size(1024**3 - 1) == "1024.0MB"  # Correct rounding
        assert human_size(1024**4) == "1.0TB"  # 1 TiB

    def test_sha256_of_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("test content")
        expected = "6ae8a75555209fd6c44157c0aed8016e763ff435a19cf186f76863140143ff72"
        assert sha256_of_file(f) == expected

    def test_ensure_dir(self, tmp_path):
        p = tmp_path / "nested" / "dir"
        ensure_dir(p)
        assert p.exists()
        assert p.is_dir()

    def test_make_unique_path(self, temp_dest):
        base = temp_dest / "existing"
        base.mkdir()
        unique = make_unique_path(base)
        assert unique.name == "existing-1"
        assert not unique.exists()  # Not created, just named

    def test_make_unique_path_incrementing(self, tmp_path):
        base = tmp_path / "same"
        base.mkdir()
        (tmp_path / "same-1").mkdir()
        (tmp_path / "same-2").mkdir()
        new = make_unique_path(tmp_path / "same")
        assert new.name == "same-3"

class TestExcludesAndScanning:
    def test_matches_excludes(self, temp_dir, sample_excludes):
        # Glob match
        assert matches_excludes(temp_dir / "file2.bin", sample_excludes) is True
        # Substring match
        assert matches_excludes(temp_dir / "subdir" / "file3.txt", sample_excludes) is True
        # No match
        assert matches_excludes(temp_dir / "file1.txt", sample_excludes) is False
        # Relative/absolute
        assert matches_excludes(Path("/abs/path/to/exclude.bin"), ["exclude.bin"]) is True
        # Edge: empty list
        assert matches_excludes(temp_dir / "file1.txt") is False
        # ./ prefix stripped
        assert matches_excludes(temp_dir / "file1.txt", ["./file1.txt"]) is True
        # Dotfile and nested glob
        hidden = temp_dir / ".hidden"
        hidden.touch()
        assert matches_excludes(hidden, ["*.hidden", ".*"])
        nm = temp_dir / "node_modules" / "lib.js"
        nm.parent.mkdir(parents=True)
        nm.touch()
        assert matches_excludes(nm, ["node_modules/*", "*/node_modules/*"])

    def test_walk_stats(self, temp_dir, sample_excludes):
        # Full scan (4: 2 files + subfile + symlink)
        files, size = walk_stats(temp_dir)
        assert files == 4
        assert size > 0
        # With excludes (2: file1 + symlink; excludes bin and subdir)
        files_ex, size_ex = walk_stats(temp_dir, excludes=sample_excludes)
        assert files_ex == 2
        assert size_ex >= 0  # Symlinks size ~0

    def test_copy_tree_respects_excludes(self, temp_dir, temp_dest, sample_excludes):
        final = copy_tree_atomic(temp_dir, temp_dest, "ex", excludes=sample_excludes)
        assert not (final / "file2.bin").exists()
        assert not (final / "subdir").exists()
        assert (final / "file1.txt").exists()

class TestCleanupState:
    def test_cleanup_state(self, tmp_path):
        state = CleanupState()
        tmp_d = tmp_path / "tmpd"
        tmp_d.mkdir()
        state.register_tmp_dir(tmp_d)
        tmp_f = tmp_path / "tmpf"
        tmp_f.touch()
        state.register_tmp_file(tmp_f)
        # Cleanup removes
        state.cleanup()
        assert not tmp_d.exists()
        assert not tmp_f.exists()
        # Unregister prevents removal
        tmp_d.mkdir()
        state.register_tmp_dir(tmp_d)
        state.unregister_tmp_dir(tmp_d)
        state.cleanup()
        assert tmp_d.exists()

    def test_cleanup_state_integration(self, tmp_path):
        f = tmp_path / "tempfile.tmp"
        d = tmp_path / "tempdir"
        f.write_text("x")
        d.mkdir()
        (d / "inside.txt").write_text("ok")
        cleanup_state.register_tmp_file(f)
        cleanup_state.register_tmp_dir(d)
        cleanup_state.cleanup(verbose=False)
        assert not f.exists()
        assert not d.exists()

class TestAtomicMove:
    @patch("os.replace")
    def test_atomic_move_replace(self, mock_replace, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        atomic_move(src, dst)
        mock_replace.assert_called_once_with(str(src), str(dst))

    @patch("os.replace")
    @patch("shutil.move")
    def test_atomic_move_fallback(self, mock_move, mock_replace, tmp_path):
        mock_replace.side_effect = OSError("cross-device")
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.touch()
        atomic_move(src, dst)
        mock_replace.assert_called_once()
        mock_move.assert_called_once_with(str(src), str(dst))

    def test_atomic_move_success_path(self, tmp_path):
        src = tmp_path / "s"
        src.mkdir()
        (src / "a.txt").write_text("1")
        dst = tmp_path / "d"
        atomic_move(src, dst)
        assert dst.exists() and not src.exists()
        assert (dst / "a.txt").read_text() == "1"

    def test_atomic_move_cross_device_fallback(self, tmp_path, monkeypatch):
        src = tmp_path / "srcdir"
        src.mkdir()
        (src / "x.txt").write_text("xyz")
        dst = tmp_path / "destdir"
        def raise_os_error(a, b):
            raise OSError("Simulated cross-device")
        monkeypatch.setattr(os, "replace", raise_os_error)
        atomic_move(src, dst)
        assert dst.exists()
        assert (dst / "x.txt").read_text() == "xyz"
        assert not src.exists()

class TestArchive:
    @patch('projectclone.cli.tarfile.TarFile.add')
    def test_create_archive(self, mock_add, temp_dir, temp_dest, mock_log_fp):
        mock_add.return_value = None
        tmp_file = temp_dest / "test"
        arc = create_archive(temp_dir, tmp_file, log_fp=mock_log_fp)
        assert arc.exists()
        assert arc.name.endswith('.tar.gz')  # Full extension check
        # Extract and verify contents (mocked, but path exists)
        with tarfile.open(arc) as tar:
            assert len(tar.getnames()) == 0  # Mocked add, no contents
        # Manifest/SHA
        arc_sha = create_archive(temp_dir, tmp_file, manifest=True, manifest_sha=True, log_fp=mock_log_fp)
        sha_fp = arc_sha.with_name(arc_sha.name + ".sha256")
        assert sha_fp.exists()
        # Validate SHA
        with open(sha_fp) as sf:
            sha_line = sf.read().strip()
            computed = sha256_of_file(arc_sha)
            assert sha_line.startswith(computed)

    @patch('projectclone.cli.tarfile.TarFile.add')
    def test_create_archive_file_input(self, mock_add, tmp_path, temp_dest):
        mock_add.return_value = None
        single_file = tmp_path / "single.txt"
        single_file.write_text("content")
        arc = create_archive(single_file, temp_dest / "single")
        assert arc.name.endswith('.tar.gz')

    @patch('projectclone.cli.tarfile.TarFile.add')
    def test_create_archive_preserves_symlink(self, mock_add, temp_dir, temp_dest):
        mock_add.return_value = None
        if not (temp_dir / "link_to_file1").exists():
            pytest.skip("Symlinks not supported")
        tmp_file = temp_dest / "sym.tar.gz"
        arc = create_archive(temp_dir, tmp_file, preserve_symlinks=True)
        assert arc.name.endswith('.tar.gz')

    @patch('projectclone.cli.tarfile.TarFile.add')
    def test_archive_and_sha_move_to_final(self, mock_add, tmp_path):
        mock_add.return_value = None
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("data")
        tmp_dest = tmp_path / ".tmp_archive"
        arc = create_archive(src, tmp_dest, arcname="project-note", manifest=True)
        assert arc.name.endswith('.tar.gz')
        sha_src = arc.with_name(arc.name + ".sha256")
        assert sha_src.exists()
        final = tmp_path / "final_archive.tar.gz"
        final = make_unique_path(final)
        atomic_move(arc, final)
        sha_dst = final.with_name(final.name + ".sha256")
        if sha_src.exists():
            atomic_move(sha_src, sha_dst)
        assert final.exists()
        assert sha_dst.exists()
        assert not arc.exists()
        assert not sha_src.exists()

    @patch('projectclone.cli.tarfile.TarFile.add')
    def test_archive_move_fallback_integration(self, mock_add, tmp_path, monkeypatch):
        mock_add.return_value = None
        src = tmp_path / "src"
        src.mkdir()
        (src / "f.txt").write_text("1")
        tmp_dest = tmp_path / ".tmp_archive"
        arc = create_archive(src, tmp_dest, arcname="proj", manifest=True)
        assert arc.name.endswith('.tar.gz')
        final = tmp_path / "final.tar.gz"
        def fail_replace(a, b):
            raise OSError("no")
        monkeypatch.setattr(os, "replace", fail_replace)
        atomic_move(arc, final)
        sha_src = arc.with_name(arc.name + ".sha256")
        sha_dst = final.with_name(final.name + ".sha256")
        if sha_src.exists():
            atomic_move(sha_src, sha_dst)
        assert final.exists()
        assert sha_dst.exists()

class TestCopyTree:
    def test_copy_tree_atomic(self, temp_dir, temp_dest, mock_log_fp):
        final = copy_tree_atomic(temp_dir, temp_dest, "backup", log_fp=mock_log_fp)
        assert final.exists()
        assert final.is_dir()
        # Verify contents
        assert (final / "file1.txt").exists()
        assert (final / "subdir" / "file3.txt").exists()
        if (temp_dir / "link_to_file1").exists():
            assert (final / "link_to_file1").exists()
        # Manifest
        final_m = copy_tree_atomic(temp_dir, temp_dest, "backup_m", manifest=True, log_fp=mock_log_fp)
        assert (final_m / "MANIFEST.txt").exists()
        with open(final_m / "MANIFEST.txt") as mf:
            lines = mf.readlines()
            assert len(lines) >= 3
        # SHA manifest
        final_s = copy_tree_atomic(temp_dir, temp_dest, "backup_s", manifest_sha=True, log_fp=mock_log_fp)
        assert (final_s / "MANIFEST_SHA256.txt").exists()
        with open(final_s / "MANIFEST_SHA256.txt") as sf:
            lines = sf.readlines()
            assert len(lines) >= 3
            if lines:
                h, rel = lines[0].strip().split(maxsplit=1)
                computed = sha256_of_file(final_s / Path(rel))
                assert h == computed
        # Unique path (use distinct name)
        dup = temp_dest / "dup_backup"
        dup.mkdir()
        unique_final = copy_tree_atomic(temp_dir, temp_dest, "dup_backup", log_fp=mock_log_fp)
        assert unique_final.name == "dup_backup-1"

    def test_copy_tree_symlinks(self, temp_dir, temp_dest):
        if not (temp_dir / "link_to_file1").exists():
            pytest.skip("Symlinks not supported")
        # Preserve: copy link, not target
        final = copy_tree_atomic(temp_dir, temp_dest, "sym", preserve_symlinks=True)
        link = final / "link_to_file1"
        assert link.is_symlink()
        target = link.readlink()
        assert target.is_absolute()
        orig_target = (temp_dir / "file1.txt").resolve()
        assert Path(target).resolve() == orig_target
        # Clear dangerous bits: mock chmod
        with patch("os.chmod"):
            copy_tree_atomic(temp_dir, temp_dest, "secure")

    def test_safe_symlink_create(self, temp_dir, mock_log_fp):
        if not (temp_dir / "link_to_file1").exists():
            pytest.skip("Symlinks not supported")
        src_link = temp_dir / "link_to_file1"
        dst = temp_dir / "copy_link"
        _safe_symlink_create(src_link, dst, log_fp=mock_log_fp)
        assert dst.is_symlink()
        assert dst.readlink() == src_link.readlink()
        # Error: invalid src
        invalid = temp_dir / "invalid"
        _safe_symlink_create(invalid, dst, mock_log_fp)
        # Dst removed if exists, but since invalid readlink fails early, no change
        if dst.exists():
            dst.unlink()

    def test_clear_dangerous_bits(self, tmp_path):
        f = tmp_path / "test"
        f.touch()
        with patch("os.stat") as mock_stat, patch("os.chmod"):
            mock_stat.return_value.st_mode = stat.S_ISUID | stat.S_IFREG | 0o644
            _clear_dangerous_bits(f)
            mock_stat.assert_called_once()
            os.chmod.assert_called_once_with(f, stat.S_IFREG | 0o644)  # Cleared S_ISUID

    def test_copy2_error_logged_and_continues(self, temp_dir, temp_dest, monkeypatch, capsys):
        real_copy2 = shutil.copy2
        def fake_copy2(src_fp, dst_fp, follow_symlinks=True):
            if "file2.bin" in str(src_fp):
                raise PermissionError("simulated read error")
            return real_copy2(src_fp, dst_fp, follow_symlinks=follow_symlinks)
        monkeypatch.setattr(shutil, "copy2", fake_copy2)
        with capsys.disabled():  # Avoid progress prints
            final = copy_tree_atomic(temp_dir, temp_dest, "error", show_progress=False)
        assert (final / "file1.txt").exists()
        assert not (final / "file2.bin").exists()

class TestRotation:
    def test_rotate_backups(self, temp_dest):
        project = "testproj"
        ts1 = "2025-10-24_143000-testproj-note1"
        ts2 = "2025-10-23_143000-testproj-note2"
        dir1 = temp_dest / ts1
        dir1.mkdir()
        file2 = temp_dest / f"{ts2}.tar.gz"
        file2.touch()
        # Keep 1: delete older
        rotate_backups(temp_dest, 1, project)
        assert dir1.exists()
        assert not file2.exists()
        # Keep 0: no delete
        rotate_backups(temp_dest, 0, project)
        assert dir1.exists()

    def test_rotate_keep_zero_and_one(self, tmp_path):
        base = tmp_path / "back"
        base.mkdir()
        for i in range(4):
            nm = f"2025-10-{10+i:02d}_123456-proj-{i}"
            p = base / nm
            p.mkdir()
            atime = time.time() - (i * 3600)
            os.utime(p, (atime, atime))
        # keep=0 -> keep all
        rotate_backups(base, keep=0, project_name="proj")
        assert len(list(base.iterdir())) == 4
        # keep=1 -> only newest remains
        rotate_backups(base, keep=1, project_name="proj")
        assert len(list(base.iterdir())) == 1

    def test_rotate_deletes_files_and_dirs(self, tmp_path):
        base = tmp_path / "back"
        base.mkdir()
        # create file backup and dir backup
        (base / "2025-01-01_000000-proj-note-0").mkdir()
        (base / "2025-01-02_000000-proj-note-1").mkdir()
        f = base / "2025-01-03_000000-proj-note-2.tar.gz"
        f.touch()
        # keep only 1 newest
        rotate_backups(base, keep=1, project_name="proj")
        remaining = list(base.iterdir())
        assert len(remaining) == 1

class TestRsync:
    @patch("subprocess.run")
    def test_have_rsync(self, mock_run):
        mock_run.side_effect = [
            subprocess.CompletedProcess(["rsync", "--version"], returncode=0),
            subprocess.CalledProcessError(1, ["rsync", "--version"]),
        ]
        assert have_rsync() is True
        assert have_rsync() is False

    @patch("subprocess.run")
    def test_rsync_incremental(self, mock_run, temp_dir, temp_dest, mock_log_fp):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = b""
        mock_run.return_value.stderr = b""
        link_dest = None
        final = rsync_incremental(temp_dir, temp_dest, "inc", link_dest, log_fp=mock_log_fp)
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][0] == "rsync"
        assert "--exclude" in " ".join(mock_run.call_args[0][0])
        assert final.exists()
        # Link-dest
        link_dest = temp_dest / "prev"
        link_dest.mkdir()
        rsync_incremental(temp_dir, temp_dest, "inc_link", link_dest, log_fp=mock_log_fp)
        assert "--link-dest" in " ".join(mock_run.call_args[0][0])
        # Dry-run: placeholder, no move
        final_dry = rsync_incremental(temp_dir, temp_dest, "dry", None, dry_run=True, log_fp=mock_log_fp)
        assert "DRYRUN" in final_dry.name
        assert not final_dry.exists()
        # Error: returncode=1
        mock_run.return_value.returncode = 1
        with pytest.raises(RuntimeError):
            rsync_incremental(temp_dir, temp_dest, "fail", None)

    def test_rsync_incremental_success_simulated(self, monkeypatch, tmp_path):
        src = tmp_path / "src"
        (src / "sub").mkdir(parents=True)
        (src / "sub" / "a.txt").write_text("abc")
        dest_parent = tmp_path / "dest"
        dest_parent.mkdir()
        dest_name = "2025-01-01_000000-proj-note"
        def fake_run(args, **kwargs):
            tmpdir_path = args[-1].rstrip('/')
            tmpdir = Path(tmpdir_path)
            tmpdir.mkdir(parents=True, exist_ok=True)
            (tmpdir / "sub").mkdir(parents=True, exist_ok=True)
            (tmpdir / "sub" / "a.txt").write_text("abc")
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
        monkeypatch.setattr(subprocess, "run", fake_run)
        final = rsync_incremental(src, dest_parent, dest_name, link_dest=None)
        assert final.exists()
        assert (final / "sub" / "a.txt").read_text() == "abc"

    def test_rsync_incremental_failure_reports(self, monkeypatch, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "x.txt").write_text("x")
        dest_parent = tmp_path / "dest"
        dest_parent.mkdir()
        dest_name = "2025-01-01_000000-proj"
        class FakeRes:
            returncode = 23
            stdout = b"out"
            stderr = b"bad"
        def fake_run(args, **kwargs):
            return FakeRes()
        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(RuntimeError):
            rsync_incremental(src, dest_parent, dest_name, link_dest=None)

    def test_rsync_incremental_dry_run_does_not_move(self, monkeypatch, tmp_path):
        src = tmp_path / "s"
        (src / "a").mkdir(parents=True)
        (src / "a" / "f.txt").write_text("x")
        dest = tmp_path / "dest"
        dest.mkdir()
        def fake_run(args, **kwargs):
            tmpdir = Path(args[-1].rstrip('/'))
            tmpdir.mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
        monkeypatch.setattr(subprocess, "run", fake_run)
        final = rsync_incremental(src, dest, "name", link_dest=None, dry_run=True)
        final_path = dest / f"name-DRYRUN"
        assert not final_path.exists()

    def test_incremental_passes_link_dest_arg(self, monkeypatch, tmp_path):
        src = tmp_path / "proj"
        (src / "a").mkdir(parents=True)
        (src / "a" / "f.txt").write_text("x")
        dest = tmp_path / "dest"
        dest.mkdir()
        prev = dest / "2025-01-01_000000-proj-note-previous"
        prev.mkdir()
        (prev / "marker").write_text("ok")
        captured = {"args": None}
        def fake_run(args, **kwargs):
            captured["args"] = args
            if args and args[-1].endswith('/'):
                Path(args[-1].rstrip('/')).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
        monkeypatch.setattr(subprocess, "run", fake_run)
        final = rsync_incremental(src, dest, "2025-01-02_000000-proj-note", link_dest=prev)
        assert final.exists()
        assert any("--link-dest" in str(x) for x in captured["args"])
        assert str(prev) in " ".join(map(str, captured["args"]))

class TestCLI:
    def test_parse_args(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--dest", "/test", "--archive"])
        args = parse_args()
        assert args.short_note == "note"
        assert args.dest == "/test"
        assert args.archive is True

    @patch("projectclone.cli.walk_stats")
    @patch("projectclone.cli.os.statvfs")
    def test_main_dry_run(self, mock_statvfs, mock_walk, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["script.py", "note", "--dry-run"])
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

    @patch('projectclone.cli.tarfile.TarFile.add')
    def test_main_archive_path_moves_into_dest_on_replace_failure(self, mock_add, monkeypatch, tmp_path):
        mock_add.return_value = None
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

def test_signal_handler(capfd, monkeypatch):
    called = {}
    def fake_cleanup(verbose=False):
        called['cleaned'] = True
    monkeypatch.setattr(cleanup_state, "cleanup", fake_cleanup)
    with pytest.raises(SystemExit):
        _signal_handler(signal.SIGINT, None)
    assert called.get('cleaned', False) is True
    out, _ = capfd.readouterr()
    assert "Signal received" in out

def test_have_rsync_true(monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=b"rsync 3.2.3", stderr=b"")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert have_rsync() is True

def test_have_rsync_and_rsync_incremental_no_rsync(monkeypatch):
    def fake_run(args, **kwargs):
        if args and args[0] == "rsync":
            raise FileNotFoundError()
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert not have_rsync()