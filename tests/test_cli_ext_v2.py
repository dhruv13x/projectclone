# projectclone/tests/test_cli_ext_v2.py


import pytest
import sys
import os
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from projectclone import cli
from projectclone import backup

@pytest.fixture
def mock_credentials_module():
    mock_creds = MagicMock()
    with patch.dict('sys.modules', {'src.common.credentials': mock_creds}):
        yield mock_creds

class TestCliExtendedV2:
    @pytest.fixture
    def mock_args(self):
        """Mock standard arguments."""
        args = MagicMock()
        args.short_note = "test_note"
        args.dest = "/tmp/backups"
        args.archive = False
        args.manifest = False
        args.manifest_sha = False
        args.symlinks = False
        args.keep = 0
        args.yes = True
        args.progress_interval = 50
        args.exclude = []
        args.dry_run = False
        args.incremental = False
        args.verbose = False
        args.cloud = False
        args.bucket = None
        args.endpoint = None
        return args

    def test_get_cloud_credentials_aws_env(self):
        """Test cloud credentials resolution for AWS from env."""
        mock_resolver = MagicMock()
        mock_resolver.resolve_credentials.return_value = ("pv_aws_key", "pv_aws_secret", "Environment")
        mock_resolver.get_cloud_provider_info.return_value = ("AWS S3", None, None)

        provider, key, secret = cli.get_cloud_credentials(resolver=mock_resolver)
        assert provider == "s3"
        assert key == "pv_aws_key"
        assert secret == "pv_aws_secret"

    def test_get_cloud_credentials_b2_env(self):
        """Test cloud credentials resolution for B2 from env."""
        mock_resolver = MagicMock()
        mock_resolver.resolve_credentials.return_value = ("pv_b2_key", "pv_b2_app", "Environment")
        mock_resolver.get_cloud_provider_info.return_value = ("Backblaze B2", None, None)

        provider, key, app = cli.get_cloud_credentials(resolver=mock_resolver)
        assert provider == "b2"
        assert key == "pv_b2_key"
        assert app == "pv_b2_app"

    def test_get_cloud_credentials_none(self):
        """Test cloud credentials resolution when none are present."""
        mock_resolver = MagicMock()
        mock_resolver.resolve_credentials.return_value = (None, None, None)
        provider, key, secret = cli.get_cloud_credentials(resolver=mock_resolver)
        assert provider is None

    @patch("projectclone.cli.get_cloud_credentials")
    def test_upload_to_cloud_missing_creds(self, mock_creds, capsys):
        """Test upload_to_cloud with missing credentials."""
        mock_creds.return_value = (None, None, None)
        log_fp = MagicMock()

        cli.upload_to_cloud(Path("testfile"), "bucket", log_fp=log_fp)

        out, _ = capsys.readouterr()
        assert "Missing cloud credentials" in out
        log_fp.write.assert_called()

    @patch("projectclone.cli.get_cloud_credentials")
    @patch("src.common.s3.S3Manager")
    def test_upload_to_cloud_s3_success(self, mock_s3, mock_creds, capsys):
        """Test upload_to_cloud with S3 provider."""
        mock_creds.return_value = ("s3", "key", "secret")
        log_fp = MagicMock()
        manager = mock_s3.return_value

        with patch.dict('sys.modules', {'src.common.b2': MagicMock(), 'src.common.s3': mock_s3}):
            cli.upload_to_cloud(Path("testfile"), "bucket", log_fp=log_fp)

        manager.upload_file.assert_called_with("testfile", "testfile")
        out, _ = capsys.readouterr()
        assert "Upload successful" in out

    @patch("projectclone.cli.get_cloud_credentials")
    @patch("src.common.b2.B2Manager")
    def test_upload_to_cloud_b2_failure(self, mock_b2, mock_creds, capsys):
        """Test upload_to_cloud with B2 provider failure."""
        mock_creds.return_value = ("b2", "key", "app")
        log_fp = MagicMock()
        manager = mock_b2.return_value
        manager.upload_file.side_effect = Exception("Upload error")

        with patch.dict('sys.modules', {'src.common.b2': mock_b2, 'src.common.s3': MagicMock()}):
            cli.upload_to_cloud(Path("testfile"), "bucket", log_fp=log_fp)

        out, _ = capsys.readouterr()
        assert "Upload failed: Upload error" in out

    @patch("projectclone.cli.cas_engine")
    def test_vault_main(self, mock_cas):
        """Test vault_main execution."""
        test_args = ["pv", "vault", ".", "/tmp/vault"]
        with patch.object(sys, 'argv', test_args):
            cli.main()
            mock_cas.backup_to_vault.assert_called()

    @patch("projectclone.cli.cas_engine")
    def test_vault_main_error(self, mock_cas):
        """Test vault_main error handling."""
        mock_cas.backup_to_vault.side_effect = Exception("Vault error")
        test_args = ["pv", "vault", ".", "/tmp/vault"]
        with patch.object(sys, 'argv', test_args):
            with pytest.raises(SystemExit) as exc:
                cli.main()
            assert exc.value.code == 1

    def test_parse_args_no_args(self, capsys):
        """Test parse_args with no arguments triggers help."""
        test_args = ["pv"]
        with patch.object(sys, 'argv', test_args):
            with pytest.raises(SystemExit) as exc:
                cli.parse_args()
            assert exc.value.code == 0

    def test_parse_args_missing_note(self, capsys):
        """Test parse_args missing short_note."""
        test_args = ["pv", "--dest", "/tmp"]
        with patch.object(sys, 'argv', test_args):
            with pytest.raises(SystemExit) as exc:
                cli.parse_args()
            assert exc.value.code == 1

    @patch("projectclone.cli.parse_args")
    @patch("projectclone.cli.walk_stats")
    @patch("projectclone.cli.copy_tree_atomic")
    @patch("shutil.disk_usage")
    def test_main_disk_full_warning(self, mock_du, mock_copy, mock_walk, mock_parse, capsys):
        """Test main warning when disk is full."""
        args = MagicMock()
        args.short_note = "note"
        args.dest = "/tmp/backup"
        args.yes = True
        args.dry_run = False
        args.incremental = False
        args.archive = False
        args.cloud = False
        args.keep = 0
        mock_parse.return_value = args

        mock_walk.return_value = (10, 1000)
        mock_du.return_value = (2000, 1500, 500) # total, used, free (500 < 1000)

        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.touch"), patch("pathlib.Path.chmod"), patch.object(sys, 'argv', ['pv', 'clone', 'test_note']):
             cli.main()

        out, _ = capsys.readouterr()
        assert "WARNING: estimated backup size exceeds free space at destination" in out

    @patch("projectclone.cli.parse_args")
    @patch("projectclone.cli.walk_stats")
    def test_main_dry_run_exit(self, mock_walk, mock_parse, capsys):
        """Test main dry-run exit."""
        args = MagicMock()
        args.short_note = "note"
        args.dest = "/tmp/backup"
        args.dry_run = True
        args.incremental = False
        args.keep = 0
        mock_parse.return_value = args
        mock_walk.return_value = (10, 100)

        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.touch"), patch("pathlib.Path.chmod"), patch("shutil.disk_usage") as du, patch.object(sys, 'argv', ['pv', 'clone', 'test_note']):
            du.return_value = (1000, 100, 900)
            cli.main()

        out, _ = capsys.readouterr()
        assert "Dry run: no files will be written. Exiting after report." in out

    @patch("projectclone.cli.parse_args")
    @patch("projectclone.cli.walk_stats")
    @patch("builtins.input", side_effect=["n"])
    def test_main_abort_by_user(self, mock_input, mock_walk, mock_parse, capsys):
        """Test main user abort."""
        args = MagicMock()
        args.short_note = "note"
        args.dest = "/tmp/backup"
        args.yes = False
        args.dry_run = False
        args.incremental = False
        args.keep = 0
        mock_parse.return_value = args
        mock_walk.return_value = (10, 100)

        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.touch"), patch("pathlib.Path.chmod"), patch("shutil.disk_usage") as du, patch.object(sys, 'argv', ['pv', 'clone', 'test_note']):
             du.return_value = (1000, 100, 900)
             with pytest.raises(SystemExit) as exc:
                 cli.main()
             assert exc.value.code == 1

    @patch("projectclone.cli.parse_args")
    @patch("projectclone.cli.walk_stats")
    @patch("projectclone.cli.rsync_incremental")
    @patch("projectclone.cli.have_rsync")
    def test_main_incremental_success(self, mock_have_rsync, mock_rsync, mock_walk, mock_parse):
        """Test main incremental backup success."""
        args = MagicMock()
        args.short_note = "note"
        args.dest = "/tmp/backup"
        args.yes = True
        args.incremental = True
        args.cloud = False
        args.dry_run = False  # Ensure not dry run
        args.keep = 0
        mock_parse.return_value = args
        mock_walk.return_value = (10, 100)
        mock_have_rsync.return_value = True
        mock_rsync.return_value = Path("/tmp/backup/final")

        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.touch"), patch("pathlib.Path.chmod"), patch("shutil.disk_usage") as du, \
             patch("pathlib.Path.iterdir", return_value=[]), \
             patch.object(sys, 'argv', ['pv', 'clone', 'test_note']):
             du.return_value = (1000, 100, 900)
             cli.main()

        mock_rsync.assert_called()

    @patch("projectclone.cli.parse_args")
    @patch("projectclone.cli.walk_stats")
    @patch("projectclone.cli.create_archive")
    @patch("projectclone.cli.atomic_move")
    @patch("tempfile.TemporaryDirectory")
    def test_main_archive_success(self, mock_temp, mock_move, mock_archive, mock_walk, mock_parse):
        """Test main archive backup success."""
        args = MagicMock()
        args.short_note = "note"
        args.dest = "/tmp/backup"
        args.yes = True
        args.incremental = False
        args.archive = True
        args.cloud = False
        args.symlinks = False
        args.manifest = False
        args.manifest_sha = False
        args.keep = 0
        args.dry_run = False # Ensure not dry run
        mock_parse.return_value = args
        mock_walk.return_value = (10, 100)

        # Mock TemporaryDirectory context manager
        mock_temp.return_value.__enter__.return_value = "/tmp/tmp_dir"

        mock_archive.return_value = Path("/tmp/tmp_archive.tar.gz")

        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.touch"), patch("pathlib.Path.chmod"), patch("shutil.disk_usage") as du, patch.object(sys, 'argv', ['pv', 'clone', 'test_note']):
             du.return_value = (1000, 100, 900)
             cli.main()

        mock_archive.assert_called()
        mock_move.assert_called()

    @patch("projectclone.cli.parse_args")
    @patch("projectclone.cli.walk_stats")
    @patch("projectclone.cli.copy_tree_atomic")
    @patch("projectclone.cli.upload_to_cloud")
    def test_main_cloud_upload(self, mock_upload, mock_copy, mock_walk, mock_parse):
        """Test main cloud upload."""
        args = MagicMock()
        args.short_note = "note"
        args.dest = "/tmp/backup"
        args.yes = True
        args.incremental = False
        args.archive = False
        args.cloud = True
        args.bucket = "mybucket"
        args.endpoint = None
        args.dry_run = False # Ensure not dry run
        args.keep = 0
        mock_parse.return_value = args
        mock_walk.return_value = (10, 100)
        mock_copy.return_value = Path("/tmp/backup/final")

        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.touch"), patch("pathlib.Path.chmod"), patch("shutil.disk_usage") as du, patch.object(sys, 'argv', ['pv', 'clone', 'test_note']):
             du.return_value = (1000, 100, 900)
             cli.main()

        mock_upload.assert_called()

    @patch("projectclone.cli.parse_args")
    @patch("projectclone.cli.walk_stats")
    @patch("projectclone.cli.copy_tree_atomic")
    def test_main_cloud_upload_no_bucket(self, mock_copy, mock_walk, mock_parse, capsys):
        """Test main cloud upload skipped if no bucket."""
        args = MagicMock()
        args.short_note = "note"
        args.dest = "/tmp/backup"
        args.yes = True
        args.incremental = False
        args.archive = False
        args.cloud = True
        args.dry_run = False # Ensure not dry run
        args.bucket = None # Missing bucket
        args.keep = 0
        mock_parse.return_value = args
        mock_walk.return_value = (10, 100)
        mock_copy.return_value = Path("/tmp/backup/final")

        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.touch"), patch("pathlib.Path.chmod"), patch("shutil.disk_usage") as du, patch.object(sys, 'argv', ['pv', 'clone', 'test_note']):
             du.return_value = (1000, 100, 900)
             cli.main()

        out, _ = capsys.readouterr()
        assert "WARNING: --cloud specified but no --bucket provided. Skipping upload." in out
