# projectclone/tests/test_backup_ultra.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from projectclone import backup

class TestBackupUltra:

    def test_clear_dangerous_bits_fail(self, tmp_path):
        f = tmp_path / "f"
        f.touch()

        with patch("pathlib.Path.stat", side_effect=Exception("Stat fail")):
            backup._clear_dangerous_bits(f)

    def test_rsync_log_write_fail(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        log_fp = MagicMock()
        log_fp.write.side_effect = Exception("Log fail")

        # Trigger rsync success, but log write fail
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            with patch("projectclone.backup.atomic_move"):
                # Should swallow exception
                backup.rsync_incremental(src, dest, "backup", None, log_fp=log_fp)

    def test_rsync_fail_log_write_fail(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        log_fp = MagicMock()
        log_fp.write.side_effect = Exception("Log fail")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = b""
            mock_run.return_value.stderr = b""

            # Exception in log writing is swallowed inside rsync_incremental before raising RuntimeError
            with pytest.raises(RuntimeError):
                backup.rsync_incremental(src, dest, "backup", None, log_fp=log_fp)
