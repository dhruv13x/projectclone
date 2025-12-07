# projectclone/tests/test_backup_summary.py

import time
import sys
import pytest
from pathlib import Path
from unittest.mock import patch
from projectclone import cli

def test_backup_summary_printed(tmp_path, capsys):
    """Test that the summary line is printed after a successful backup."""
    # Setup
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("content")
    dest = tmp_path / "dest"
    dest.mkdir()
    
    # Arguments
    # projectclone.cli expects [prog, note, flags...]
    test_args = ["projectclone", "test_summary", "--dest", str(dest), "--yes", "--archive"]
    
    # Patch sys.argv
    with patch.object(sys, 'argv', test_args):
        # Run main
        try:
            cli.main()
        except SystemExit:
            pass
            
    # Capture output
    captured = capsys.readouterr()
    output = captured.out
    
    # Assertions
    assert "Backup finished." in output
    assert "✨ Summary:" in output
    assert "created in" in output
    assert "s" in output # seconds
