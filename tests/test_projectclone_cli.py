# projectclone/tests/test_projectclone_cli.py

import pytest
import sys
import os
from unittest.mock import patch, MagicMock, call, mock_open

# Fix import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from projectclone import cli

@pytest.fixture
def mock_sys_argv():
    with patch.object(sys, 'argv', ['create_backup.py', 'test_note']):
        yield

@pytest.fixture
def mock_sys_exit():
    with patch('sys.exit') as mock_exit:
        yield mock_exit

@pytest.fixture
def mock_cwd(tmp_path):
    with patch('pathlib.Path.cwd', return_value=tmp_path):
        yield tmp_path

@pytest.fixture
def mock_walk_stats():
    with patch('projectclone.cli.walk_stats', return_value=(10, 1000)) as mock:
        yield mock

@pytest.fixture
def capture_stdout(capsys):
    def _capture():
        return capsys.readouterr().out
    return _capture

class TestCLI:
    def test_cli_yes_flag_skips_prompt(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        sys.argv = ['create_backup.py', 'test_note', '--yes', '--dest', str(tmp_path)]

        with patch('projectclone.cli.copy_tree_atomic') as mock_copy, \
             patch('builtins.input') as mock_input, \
             patch('projectclone.cli.print_logo'):

            cli.main()

            mock_input.assert_not_called()
            mock_copy.assert_called_once()

    def test_manifest_and_sha_args(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        """Test with combinations like --manifest --manifest-sha."""
        sys.argv = ['create_backup.py', 'test_note', '--yes', '--dest', str(tmp_path), '--manifest', '--manifest-sha']

        with patch('projectclone.cli.copy_tree_atomic') as mock_copy, \
             patch('projectclone.cli.print_logo'):

            cli.main()

            args, kwargs = mock_copy.call_args
            assert kwargs.get('manifest') is True
            assert kwargs.get('manifest_sha') is True

    def test_complex_exclude_patterns(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        """Test with complex --exclude patterns."""
        excludes = ['*.pyc', '__pycache__', 'node_modules/', '.git']
        cmd = ['create_backup.py', 'test_note', '--yes', '--dest', str(tmp_path)]
        for exc in excludes:
            cmd.extend(['--exclude', exc])

        sys.argv = cmd

        with patch('projectclone.cli.copy_tree_atomic') as mock_copy, \
             patch('projectclone.cli.print_logo'):

            cli.main()

            args, kwargs = mock_copy.call_args
            assert kwargs.get('excludes') == excludes
            # Also verify walk_stats got them
            args_walk, kwargs_walk = mock_walk_stats.call_args
            assert kwargs_walk.get('excludes') == excludes

    def test_progress_interval(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        """Test with non-default --progress-interval."""
        sys.argv = ['create_backup.py', 'test_note', '--yes', '--dest', str(tmp_path), '--progress-interval', '123']

        with patch('projectclone.cli.copy_tree_atomic') as mock_copy, \
             patch('projectclone.cli.print_logo'):

            cli.main()

            args, kwargs = mock_copy.call_args
            assert kwargs.get('progress_interval') == 123

    def test_version_flag(self, mock_sys_exit, capture_stdout):
        """Test --version flag."""
        with patch('sys.argv', ['create_backup.py', '--version']):
            try:
                cli.parse_args()
            except SystemExit as e:
                mock_sys_exit.assert_called_with(0)

            output = capture_stdout()
            assert "1.0.0" in output

    def test_keyboard_interrupt_clean_exit(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path, mock_sys_exit):
        """Mock backup action to raise KeyboardInterrupt and verify handling."""
        sys.argv = ['create_backup.py', 'test_note', '--yes', '--dest', str(tmp_path)]

        with patch('projectclone.cli.copy_tree_atomic', side_effect=KeyboardInterrupt), \
             patch('projectclone.cli.print_logo'), \
             patch('projectclone.cli.cleanup_state.cleanup') as mock_cleanup:

            with pytest.raises(KeyboardInterrupt):
                cli.main()

            # cleanup should not be called for KeyboardInterrupt
            mock_cleanup.assert_not_called()

    def test_logfile_contains_markers(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        dest = tmp_path / "backups"
        dest.mkdir()
        sys.argv = ['create_backup.py', 'test_note', '--yes', '--dest', str(dest)]

        with patch('projectclone.cli.copy_tree_atomic'), \
             patch('projectclone.cli.print_logo'):

            cli.main()

            # Find log file
            log_files = list(dest.glob("*.log"))
            assert len(log_files) == 1
            content = log_files[0].read_text()
            assert "Starting backup" in content
            assert "Backup finished successfully" in content

    def test_vault_subcommand(self, mock_sys_exit):
        sys.argv = ['create_backup.py', 'vault', 'src_dir', 'vault_dir']

        with patch('projectclone.cas_engine.backup_to_vault') as mock_backup, \
             patch('projectclone.cli.print_logo'):

            cli.main()

            mock_backup.assert_called_once()
            args, _ = mock_backup.call_args
            # args are absolute paths
            assert args[0].endswith('src_dir')
            assert args[1].endswith('vault_dir')

    def test_archive_mode(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        sys.argv = ['create_backup.py', 'test_note', '--yes', '--dest', str(tmp_path), '--archive']

        with patch('projectclone.cli.create_archive') as mock_create, \
             patch('projectclone.cli.atomic_move') as mock_move, \
             patch('projectclone.cli.print_logo'):

             # Mock make_unique_path to return the input path (simplified)
             with patch('projectclone.cli.make_unique_path', side_effect=lambda p: p):
                cli.main()

                mock_create.assert_called_once()
                mock_move.assert_called() # Archive moved to final dest

    # New tests for coverage

    def test_dest_dir_creation_failure(self, mock_sys_argv, mock_cwd, mock_sys_exit):
        """Test failure to create destination directory."""
        sys.argv = ['create_backup.py', 'note', '--yes']
        with patch('projectclone.cli.ensure_dir', side_effect=Exception("Perm Error")):
            cli.main()
            mock_sys_exit.assert_called_with(2)

    @patch("shutil.disk_usage")
    def test_main_insufficient_space(self, mock_disk_usage, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path, mock_sys_exit):
        """Test warning when space is insufficient (mock shutil.disk_usage)."""
        
        # mock disk_usage to return (total, used, free)
        # free space = 10 bytes, total_size = 100 bytes
        mock_disk_usage.return_value = (1000, 990, 10)
        
        mock_walk_stats.return_value = (5, 100)  # 100 bytes needed
        
        from projectclone.cli import main
        
        # We expect the warning to be printed
        with patch('builtins.print') as mock_print:
            # We also need to mock input to avoid hanging
            with patch('builtins.input', return_value='y'):
                 main()
                 
            # Check for the warning in print calls
            print_calls = [str(c) for c in mock_print.mock_calls]
            assert any("WARNING: estimated backup size exceeds free space" in s for s in print_calls)

    def test_dry_run_no_incremental(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        """Test --dry-run without --incremental exits without action."""
        sys.argv = ['create_backup.py', 'note', '--yes', '--dest', str(tmp_path), '--dry-run']

        with patch('projectclone.cli.copy_tree_atomic') as mock_copy, \
             patch('projectclone.cli.print_logo'):

             cli.main()

             mock_copy.assert_not_called()

    def test_user_aborts(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path, mock_sys_exit):
        """Test user aborts at prompt."""
        sys.argv = ['create_backup.py', 'note', '--dest', str(tmp_path)] # no --yes

        with patch('builtins.input', return_value='n'), \
             patch('projectclone.cli.print_logo'):

             cli.main()

             mock_sys_exit.assert_called_with(1)

    def test_user_aborts_eof(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path, mock_sys_exit):
        """Test user aborts with EOF (Ctrl+D)."""
        sys.argv = ['create_backup.py', 'note', '--dest', str(tmp_path)]

        with patch('builtins.input', side_effect=EOFError), \
             patch('projectclone.cli.print_logo'):

             cli.main()

             mock_sys_exit.assert_called_with(1)

    def test_incremental_backup_no_rsync(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path, mock_sys_exit):
        """Test incremental backup fails if no rsync."""
        sys.argv = ['create_backup.py', 'note', '--yes', '--dest', str(tmp_path), '--incremental']

        with patch('projectclone.cli.have_rsync', return_value=False), \
             patch('projectclone.cli.print_logo'):

             cli.main()

             mock_sys_exit.assert_called_with(2)

    def test_incremental_backup_success(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        """Test incremental backup success path."""
        sys.argv = ['create_backup.py', 'note', '--yes', '--dest', str(tmp_path), '--incremental']

        with patch('projectclone.cli.have_rsync', return_value=True), \
             patch('projectclone.cli.rsync_incremental') as mock_rsync, \
             patch('projectclone.cli.print_logo'):

             cli.main()

             mock_rsync.assert_called_once()

    def test_cleanup_on_exception(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path, mock_sys_exit):
        """Test that cleanup is called on generic exception."""
        sys.argv = ['create_backup.py', 'note', '--yes', '--dest', str(tmp_path)]

        with patch('projectclone.cli.copy_tree_atomic', side_effect=RuntimeError("Boom")), \
             patch('projectclone.cli.cleanup_state.cleanup') as mock_cleanup, \
             patch('projectclone.cli.print_logo'):

             cli.main()

             mock_cleanup.assert_called_with(verbose=True)
             mock_sys_exit.assert_called_with(2)

    def test_rotate_called(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        """Test that rotation is called if --keep is set."""
        sys.argv = ['create_backup.py', 'note', '--yes', '--dest', str(tmp_path), '--keep', '5']

        with patch('projectclone.cli.copy_tree_atomic'), \
             patch('projectclone.cli.rotate_backups') as mock_rotate, \
             patch('projectclone.cli.print_logo'):

             cli.main()

             mock_rotate.assert_called_once()

    def test_vault_main_exception(self, mock_sys_exit):
        """Test vault subcommand exception handling."""
        sys.argv = ['create_backup.py', 'vault', 'src', 'dst']

        with patch('projectclone.cas_engine.backup_to_vault', side_effect=Exception("Vault error")), \
             patch('projectclone.cli.print_logo'):

             cli.main()

             mock_sys_exit.assert_called_with(1)

    def test_log_file_permission_error_ignored(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        """Test that log file permission errors (chmod) are ignored."""
        sys.argv = ['create_backup.py', 'note', '--yes', '--dest', str(tmp_path)]

        # Mock path.chmod to raise Exception
        with patch('pathlib.Path.chmod', side_effect=OSError("No chmod")), \
             patch('projectclone.cli.copy_tree_atomic'), \
             patch('projectclone.cli.print_logo'):

             cli.main()
             # Should proceed without error

    def test_log_file_open_failure(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        """Test handling when log file cannot be opened."""
        sys.argv = ['create_backup.py', 'note', '--yes', '--dest', str(tmp_path)]

        with patch('pathlib.Path.open', side_effect=PermissionError("Denied")), \
             patch('projectclone.cli.copy_tree_atomic') as mock_copy, \
             patch('projectclone.cli.print_logo'):

             cli.main()

             # Should fallback to stdout logging (check by seeing if backup proceeded)
             mock_copy.assert_called_once()

    def test_log_write_error_ignored(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        """Test that errors writing to log file are ignored."""
        sys.argv = ['create_backup.py', 'note', '--yes', '--dest', str(tmp_path)]

        # Create a mock file object that raises error on write
        mock_file = MagicMock()
        mock_file.write.side_effect = OSError("Disk full")

        with patch('pathlib.Path.open', return_value=mock_file), \
             patch('projectclone.cli.copy_tree_atomic'), \
             patch('projectclone.cli.print_logo'):

             cli.main()
             # Should complete even if logging failed
             # Ensure write was called at least once
             assert mock_file.write.called

    def test_verbose_logging(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        """Test verbose logging execution path."""
        sys.argv = ['create_backup.py', 'note', '--yes', '--dest', str(tmp_path), '--verbose']

        # We just ensure it runs through without error
        with patch('projectclone.cli.copy_tree_atomic'), \
             patch('projectclone.cli.print_logo'):

             cli.main()

    def test_symlinks_flag(self, mock_sys_argv, mock_cwd, mock_walk_stats, tmp_path):
        """Test --symlinks flag is passed."""
        sys.argv = ['create_backup.py', 'note', '--yes', '--dest', str(tmp_path), '--symlinks']

        with patch('projectclone.cli.copy_tree_atomic') as mock_copy, \
             patch('projectclone.cli.print_logo'):

             cli.main()

             args, kwargs = mock_copy.call_args
             assert kwargs.get('preserve_symlinks') is True
