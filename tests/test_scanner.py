# tests/test_scanner.py

from pathlib import Path

import pytest

from projectclone.backup import copy_tree_atomic
from projectclone.scanner import (
    matches_excludes,
    walk_stats,
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


class TestExcludesAndScanning:
    def test_matches_excludes(self, temp_dir, sample_excludes):
        # Glob match
        assert matches_excludes(temp_dir / "file2.bin", sample_excludes) is True
        
        # Directory match (exact name)
        assert matches_excludes(temp_dir / "subdir", sample_excludes) is True
        
        # Child file check: matches_excludes matches the path itself against patterns.
        # "subdir" pattern matches "subdir" path.
        # It does NOT match "subdir/file3.txt" directly via fnmatch.
        # The recursion filtering happens in walk_stats via directory pruning.
        # So this should be False for the file path itself.
        assert matches_excludes(temp_dir / "subdir" / "file3.txt", sample_excludes) is False
        
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
