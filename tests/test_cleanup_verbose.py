# projectclone/tests/test_cleanup_verbose.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from projectclone import cleanup

class TestCleanupVerbose:

    def test_cleanup_verbose_success(self, tmp_path, capsys):
        cs = cleanup.CleanupState()

        # Create file and dir
        tmp_file = tmp_path / "temp_file"
        tmp_file.touch()
        cs.register_tmp_file(tmp_file)

        tmp_dir = tmp_path / "temp_dir"
        tmp_dir.mkdir()
        cs.register_tmp_dir(tmp_dir)

        # Cleanup verbose
        cs.cleanup(verbose=True)

        captured = capsys.readouterr()
        assert "Removed temp file" in captured.out
        assert "Removed temp dir" in captured.out
        assert not tmp_file.exists()
        assert not tmp_dir.exists()
