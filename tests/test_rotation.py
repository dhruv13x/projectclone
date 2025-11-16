# tests/test_rotation.py

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from projectclone.rotation import rotate_backups


@pytest.fixture
def temp_dest(tmp_path: Path):
    """Temp dest base dir."""
    dest = tmp_path / "dest"
    dest.mkdir()
    yield dest


class TestRotation:
    def test_rotate_backups(self, temp_dest):
        project = "testproj"
        dir1 = temp_dest / "2025-01-01_000000-testproj-note1"
        dir1.mkdir()
        os.utime(dir1, (1735689600, 1735689600))  # Jan 1, 2025
        file2 = temp_dest / "2025-01-02_000000-testproj-note2.tar.gz"
        file2.touch()
        os.utime(file2, (1735776000, 1735776000)) # Jan 2, 2025
        # Keep 1: delete older
        rotate_backups(temp_dest, 1, project)
        assert not dir1.exists()
        assert file2.exists()
        # Keep 0: no delete
        rotate_backups(temp_dest, 0, project)
        assert file2.exists()

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

    def test_rotate_backups_error_handling(self, temp_dest):
        project = "testproj"
        dir1 = temp_dest / "2025-01-01_000000-testproj-note1"
        dir1.mkdir()
        os.utime(dir1, (1735689600, 1735689600))  # Jan 1, 2025
        file2 = temp_dest / "2025-01-02_000000-testproj-note2.tar.gz"
        file2.touch()
        os.utime(file2, (1735776000, 1735776000))  # Jan 2, 2025

        # Mock shutil.rmtree to raise an exception
        with patch("shutil.rmtree") as mock_rmtree:
            mock_rmtree.side_effect = OSError("Test error")
            rotate_backups(temp_dest, 1, project)
            # The file should still be there, and the error should be caught
            assert dir1.exists()
