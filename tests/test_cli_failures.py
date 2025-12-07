# projectclone/tests/test_cli_failures.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch

from projectclone import cli as projectclone_cli

class TestCliFailures:
    """Tests for projectclone/cli.py targeting error paths and user interaction."""

    def test_cli_log_permission_fail(self, tmp_path):
        # Lines 113-115: chmod fail
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            with patch("sys.argv", ["prog", "note"]):
                with patch("pathlib.Path.chmod", side_effect=OSError("Chmod fail")):
                    # We just want to ensure it doesn't crash
                    with patch("projectclone.cli.walk_stats", return_value=(0, 0)):
                         # mock input to avoid hanging
                        with patch("builtins.input", side_effect=["y"]):
                            try:
                                projectclone_cli.main()
                            except SystemExit:
                                pass

    def test_cli_statvfs_fail(self, tmp_path):
        # Lines 155->170: statvfs fail
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            with patch("sys.argv", ["prog", "note"]):
                with patch("os.statvfs", side_effect=OSError("Stat fail")):
                    with patch("projectclone.cli.walk_stats", return_value=(1, 100)):
                        with patch("builtins.input", side_effect=["y"]):
                             # Mock backup functions to avoid actual work
                            with patch("projectclone.cli.copy_tree_atomic"):
                                try:
                                    projectclone_cli.main()
                                except SystemExit:
                                    pass

    def test_cli_space_check_warning(self, tmp_path):
        # Lines 161->170 (Total size > free)
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            with patch("sys.argv", ["prog", "note"]):
                # Return small free space
                mock_stat = MagicMock()
                mock_stat.f_frsize = 1
                mock_stat.f_bavail = 10 # 10 bytes free
                with patch("os.statvfs", return_value=mock_stat):
                    with patch("projectclone.cli.walk_stats", return_value=(1, 1000)): # 1000 bytes needed
                         with patch("builtins.input", side_effect=["y"]):
                            with patch("projectclone.cli.copy_tree_atomic"):
                                projectclone_cli.main()

    def test_cli_interactive_abort(self, tmp_path):
        # Lines 224->317 Abort
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            with patch("sys.argv", ["prog", "note"]):
                with patch("projectclone.cli.walk_stats", return_value=(0, 0)):
                    with patch("builtins.input", side_effect=["n"]): # User says no
                        with pytest.raises(SystemExit) as exc:
                            projectclone_cli.main()
                        assert exc.value.code == 1

    def test_cli_incremental_rsync_fail(self, tmp_path):
         with patch("pathlib.Path.cwd", return_value=tmp_path):
            with patch("sys.argv", ["prog", "--incremental", "note"]):
                 with patch("projectclone.cli.have_rsync", return_value=True):
                     # Mock iterdir to return nothing so link_dest is None, or something
                     with patch("pathlib.Path.iterdir", return_value=[]):
                         with patch("projectclone.cli.rsync_incremental", side_effect=RuntimeError("Rsync fail")):
                             with patch("projectclone.cli.walk_stats", return_value=(0, 0)):
                                 with patch("builtins.input", return_value="y"):
                                     with pytest.raises(SystemExit):
                                         projectclone_cli.main()
