
import os
import sys
import tarfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from projectclone import cli


@pytest.fixture
def setup_test_environment(tmp_path):
    """Set up a test environment with a source directory and some files."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file1.txt").write_text("file1 content")
    (source_dir / "file2.txt").write_text("file2 content")
    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()
    (sub_dir / "file3.txt").write_text("file3 content")
    return source_dir, tmp_path / "dest"


def test_main_archive_and_manifest(setup_test_environment):
    """Test the main function with archive and manifest creation."""
    source_dir, dest_dir = setup_test_environment
    dest_dir.mkdir()

    # Change the current working directory to the source directory
    os.chdir(source_dir)

    # Mock the command-line arguments
    test_args = [
        "test_project",
        "test_note",
        "--dest",
        str(dest_dir),
        "--archive",
        "--manifest",
        "--yes",
    ]
    with patch.object(sys, "argv", test_args):
        cli.main()

    # Verify that the archive and manifest were created
    archives = list(dest_dir.glob("*.tar.gz"))
    assert len(archives) == 1
    archive_path = archives[0]
    manifest_path = dest_dir / (archive_path.name + ".sha256")
    assert manifest_path.exists()

    # Verify the contents of the archive
    with tarfile.open(archive_path, "r:gz") as tar:
        names = tar.getnames()
        assert any("file1.txt" in name for name in names)
        assert any("file2.txt" in name for name in names)
        assert any("subdir/file3.txt" in name for name in names)


def test_main_incremental_backup(setup_test_environment):
    """Test the main function with incremental backup."""
    source_dir, dest_dir = setup_test_environment
    dest_dir.mkdir()

    # Change the current working directory to the source directory
    os.chdir(source_dir)

    # Mock the command-line arguments for the initial backup
    test_args_initial = [
        "test_project",
        "initial_backup",
        "--dest",
        str(dest_dir),
        "--yes",
    ]
    with patch.object(sys, "argv", test_args_initial):
        cli.main()

    # Verify that the initial backup was created
    initial_backup_dirs = [p for p in dest_dir.iterdir() if p.is_dir()]
    assert len(initial_backup_dirs) == 1
    initial_backup_path = initial_backup_dirs[0]
    assert (initial_backup_path / "file1.txt").exists()

    # Modify a file and create an incremental backup
    (source_dir / "file1.txt").write_text("modified content")
    test_args_incremental = [
        "test_project",
        "incremental_backup",
        "--dest",
        str(dest_dir),
        "--incremental",
        "--yes",
    ]
    with patch.object(sys, "argv", test_args_incremental):
        with patch("projectclone.cli.have_rsync", return_value=True):
            cli.main()

    # Verify that the incremental backup was created
    incremental_backup_dirs = list(dest_dir.glob("*-incremental_backup"))
    assert len(incremental_backup_dirs) == 1
    incremental_backup_path = incremental_backup_dirs[0]
    assert (incremental_backup_path / "file1.txt").read_text() == "modified content"


def test_main_dry_run_and_yes_flags(setup_test_environment):
    """Test the main function with the --dry-run and --yes flags."""
    source_dir, dest_dir = setup_test_environment
    dest_dir.mkdir()

    # Change the current working directory to the source directory
    os.chdir(source_dir)

    # Test with --dry-run
    test_args_dry_run = [
        "test_project",
        "dry_run_test",
        "--dest",
        str(dest_dir),
        "--dry-run",
    ]
    with patch.object(sys, "argv", test_args_dry_run):
        cli.main()

    # Verify that no backup was created (only the log file)
    assert len(list(dest_dir.iterdir())) == 1
    assert list(dest_dir.iterdir())[0].name.endswith(".log")

    # Test with --yes
    test_args_yes = [
        "test_project",
        "yes_test",
        "--dest",
        str(dest_dir),
        "--yes",
    ]
    with patch.object(sys, "argv", test_args_yes):
        with patch("builtins.input", return_value="n"):  # Should not be called
            cli.main()

    # Verify that the backup was created
    backup_dirs = [p for p in dest_dir.iterdir() if p.is_dir()]
    assert len(backup_dirs) == 1


def test_main_user_prompt_no(setup_test_environment):
    """Test the main function with user prompt 'no'."""
    source_dir, dest_dir = setup_test_environment
    dest_dir.mkdir()

    # Change the current working directory to the source directory
    os.chdir(source_dir)

    test_args = [
        "test_project",
        "prompt_no_test",
        "--dest",
        str(dest_dir),
    ]
    with patch.object(sys, "argv", test_args):
        with patch("builtins.input", return_value="n"):
            with pytest.raises(SystemExit) as e:
                cli.main()
            assert e.type == SystemExit
            assert e.value.code == 1

    # Verify that no backup was created
    assert not any(p.is_dir() for p in dest_dir.iterdir())
