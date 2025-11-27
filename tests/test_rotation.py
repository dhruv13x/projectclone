# projectclone/tests/test_rotation.py


import os
import shutil
import pytest
from unittest.mock import MagicMock, patch
from projectclone import rotation
from pathlib import Path

class TestRotation:

    def test_rotate_backups(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()

        project = "src"
        # Create 15 backups
        for i in range(15):
             # Format: YYYY-MM-DD_HHMMSS-<project>-
             name = f"2023-01-01_{100000+i}-{project}-backup.tar.gz"
             (vault / name).touch()
             # Set mtime to ensure order (newest last)
             os.utime(vault / name, (i*100, i*100))

        rotation.rotate_backups(vault, 10, project)

        # Should have kept 10, deleted 5.
        # The remaining should be the newest 10 (indices 5 to 14)
        remaining = sorted([p.name for p in vault.glob("*")])
        assert len(remaining) == 10
        assert "100000" not in remaining[0] # Oldest deleted
        assert "100014" in remaining[-1] # Newest kept

    def test_rotate_backups_exception(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()

        project = "proj"
        b1 = vault / "2023-01-01_000000-proj-backup.tar.gz"
        b1.touch()
        os.utime(b1, (100, 100))
        b2 = vault / "2023-01-01_000001-proj-backup.tar.gz"
        b2.touch()
        os.utime(b2, (200, 200))

        # Keep 1, delete b1. Mock unlink exception.
        with patch("pathlib.Path.unlink", side_effect=Exception("Delete fail")):
            rotation.rotate_backups(vault, 1, project)
            # Should not crash

        assert b1.exists()

    def test_rotate_backups_rmtree_exception(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()

        project = "proj"
        d1 = vault / "2023-01-01_000000-proj-backup"
        d1.mkdir()
        os.utime(d1, (100, 100))
        d2 = vault / "2023-01-01_000001-proj-backup"
        d2.mkdir()
        os.utime(d2, (200, 200))

        with patch("shutil.rmtree", side_effect=Exception("Rmtree fail")):
            rotation.rotate_backups(vault, 1, project)

        assert d1.exists()

    def test_rotate_backups_no_keep(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        rotation.rotate_backups(vault, 0, "proj")
        # Should return early
        assert True
