# tests/test_backup.py

import os
import shutil
import stat
import subprocess
import tarfile
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Fix import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from projectclone.backup import (
    atomic_move,
    create_archive,
    copy_tree_atomic,
    have_rsync,
    rsync_incremental,
    _safe_symlink_create,
    _clear_dangerous_bits,
)
from projectclone.utils import make_unique_path, sha256_of_file


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
def mock_log_fp():
    import io
    return io.StringIO()


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
    def test_create_archive(self, temp_dir, temp_dest, mock_log_fp):
        tmp_file = temp_dest / "test"
        arc = create_archive(temp_dir, tmp_file, log_fp=mock_log_fp)
        assert arc.exists()
        assert arc.name.endswith('.tar.gz')  # Full extension check
        # Extract and verify contents
        with tarfile.open(arc) as tar:
            names = tar.getnames()
            assert len(names) > 0
            assert any("file1.txt" in n for n in names)
        
        # Manifest/SHA
        arc_sha = create_archive(temp_dir, tmp_file, manifest=True, manifest_sha=True, log_fp=mock_log_fp)
        sha_fp = arc_sha.with_name(arc_sha.name + ".sha256")
        assert sha_fp.exists()
        # Validate SHA
        with open(sha_fp) as sf:
            sha_line = sf.read().strip()
            computed = sha256_of_file(arc_sha)
            assert sha_line.startswith(computed)

    def test_create_archive_file_input(self, tmp_path, temp_dest):
        single_file = tmp_path / "single.txt"
        single_file.write_text("content")
        arc = create_archive(single_file, temp_dest / "single")
        assert arc.name.endswith('.tar.gz')
        with tarfile.open(arc) as tar:
            assert len(tar.getnames()) == 1

    def test_create_archive_preserves_symlink(self, temp_dir, temp_dest):
        if not (temp_dir / "link_to_file1").exists():
            pytest.skip("Symlinks not supported")
        tmp_file = temp_dest / "sym.tar.gz"
        arc = create_archive(temp_dir, tmp_file, preserve_symlinks=True)
        assert arc.name.endswith('.tar.gz')
        with tarfile.open(arc) as tar:
            # Verify link is preserved
            # Note: tarfile stores relative paths.
            # temp_dir name is "source"
            link_name = "source/link_to_file1"
            try:
                info = tar.getmember(link_name)
                assert info.issym()
            except KeyError:
                # Fallback check if name is different
                names = tar.getnames()
                assert any("link_to_file1" in n for n in names)

    def test_archive_and_sha_move_to_final(self, tmp_path):
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

    def test_archive_move_fallback_integration(self, tmp_path, monkeypatch):
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

    def test_create_archive_failure_cleanup(self, temp_dir, temp_dest):
        """Test that partial archive is removed on exception."""
        tmp_file = temp_dest / "partial.tar.gz"
        with patch("tarfile.open", side_effect=RuntimeError("tar fail")):
            with pytest.raises(RuntimeError):
                create_archive(temp_dir, tmp_file)
        assert not tmp_file.exists()

    def test_create_archive_failure_cleanup_fail(self, temp_dir, temp_dest):
        """Test that exception in cleanup doesn't hide original error."""
        tmp_file = temp_dest / "partial.tar.gz"
        # Ensure it exists first so unlink is called
        tmp_file.touch()

        with patch("tarfile.open", side_effect=RuntimeError("tar fail")):
            with patch("pathlib.Path.unlink", side_effect=OSError("unlink fail")):
                with pytest.raises(RuntimeError, match="tar fail"):
                    create_archive(temp_dir, tmp_file)


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

    def test_safe_symlink_readlink_fail(self, temp_dir, mock_log_fp):
        """Test readlink failure handling."""
        src = temp_dir / "link_to_file1"
        if not src.exists():
            pytest.skip("Symlinks not supported")
        dst = temp_dir / "dst_link"

        with patch("os.readlink", side_effect=OSError("readlink fail")):
            _safe_symlink_create(src, dst, log_fp=mock_log_fp)
            assert not dst.exists()

    def test_clear_dangerous_bits(self, tmp_path):
        f = tmp_path / "test"
        f.touch()
        # Mock pathlib.Path.stat specifically
        with patch("pathlib.Path.stat") as mock_stat, patch("os.chmod"):
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
        with capsys.disabled():  # Avoid progress prints causing issues
            final = copy_tree_atomic(temp_dir, temp_dest, "error", show_progress=False)
        assert (final / "file1.txt").exists()
        assert not (final / "file2.bin").exists()

    def test_permission_denied_during_scan(self, temp_dir, temp_dest, monkeypatch):
        """Simulate PermissionError when scanning files."""
        real_walk = os.walk
        def fail_walk(top, followlinks=False):
            raise PermissionError("Scanning denied")
        monkeypatch.setattr(os, "walk", fail_walk)

        # We also need to mock walk_stats if copy_tree_atomic calls it.
        # The code calls walk_stats first.
        with patch("projectclone.backup.walk_stats", return_value=(0, 0)):
            with pytest.raises(PermissionError):
                 copy_tree_atomic(temp_dir, temp_dest, "scan_fail")


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