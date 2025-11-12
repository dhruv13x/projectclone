import os
import time
from pathlib import Path

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
        ts1 = f"{time.strftime('%Y-%m-%d_%H%M%S', time.gmtime(time.time() - 60))}-testproj-note1"
        ts2 = f"{time.strftime('%Y-%m-%d_%H%M%S')}-testproj-note2"
        dir1 = temp_dest / ts1
        dir1.mkdir()
        file2 = temp_dest / f"{ts2}.tar.gz"
        file2.touch()
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
