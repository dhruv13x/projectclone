# projectclone/tests/test_cli_coverage.py

import os
import sys
from unittest.mock import patch, MagicMock
import pytest
from projectclone import cli

def test_vault_main_with_source():
    """Test vault_main with a specific source directory."""
    with patch.object(sys, 'argv', ['pv', 'vault', 'some_source', '/tmp/vault']), \
         patch('projectclone.cli.cas_engine.backup_to_vault') as mock_backup:
        cli.vault_main()
        mock_backup.assert_called_once()
        # Get the absolute path of the source to match what the function does
        expected_source_path = os.path.abspath('some_source')
        # Check that the first argument to backup_to_vault is the correct absolute path
        assert mock_backup.call_args[0][0] == expected_source_path
