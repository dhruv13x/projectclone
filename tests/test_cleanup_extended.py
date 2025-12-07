# projectclone/tests/test_cleanup_extended.py


import os
import sys
import pytest
import shutil
from unittest.mock import MagicMock, patch
from pathlib import Path
from projectclone import cleanup

class TestCleanupExtended:

    def test_cleanup_exception_handling(self, tmp_path):
        # Test cleanup method handles exceptions during removal
        cs = cleanup.CleanupState()
        tmp_dir = tmp_path / "tmp"
        tmp_dir.mkdir()
        cs.register_tmp_dir(tmp_dir)

        # Mock shutil.rmtree to raise
        with patch("shutil.rmtree", side_effect=Exception("Rm fail")):
            cs.cleanup(verbose=True)

        # Should not crash. Dir should still be registered?
        # The code iterates `list(self.tmp_paths)`.
        # It tries to remove. If exception, it passes.
        # Does it unregister?
        # `self.unregister_tmp_dir(p)` is called AFTER `try...shutil.rmtree`.
        # Wait, `try: ... shutil.rmtree ... unregister ... except: pass`.
        # So if rmtree fails, unregister is SKIPPED.
        assert tmp_dir in cs.tmp_paths

    def test_cleanup_files_exception(self, tmp_path):
        cs = cleanup.CleanupState()
        tmp_file = tmp_path / "tmp.txt"
        tmp_file.touch()
        cs.register_tmp_file(tmp_file)

        # Mock unlink
        with patch("pathlib.Path.unlink", side_effect=Exception("Unlink fail")):
            cs.cleanup(verbose=True)

        assert tmp_file in cs.tmp_files
