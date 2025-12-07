# projectclone/tests/test_backup_exclude_param.py

import tarfile
import pytest
from pathlib import Path
from projectclone.backup import create_archive

@pytest.fixture
def exclude_setup(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    
    # Root file
    (source / "main.txt").write_text("main")
    
    # Folder to exclude: venv
    venv_dir = source / "venv"
    venv_dir.mkdir()
    (venv_dir / "lib_file.py").write_text("library code")
    
    # File to exclude: venv (file named venv in subdirectory)
    sub = source / "subdir"
    sub.mkdir()
    (sub / "venv").write_text("I am a file named venv")
    
    # File that should NOT be excluded (partial match)
    (source / "venv_allowed.txt").write_text("allowed")
    
    return source

def test_create_archive_exclude_folder_and_file(exclude_setup, tmp_path):
    """
    Test that 'venv' excludes both the folder 'venv/' and the file 'subdir/venv'.
    """
    archive = tmp_path / "output.tar.gz"
    
    # Logic mimics CLI: excludes=['venv']
    create_archive(exclude_setup, archive, excludes=["venv"])
    
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        # Normalized relative paths in tar are usually like "src/main.txt" (depending on arcname)
        # create_archive default arcname is source directory name ("src")
        
        top = exclude_setup.name
        
        # Should include:
        assert f"{top}/main.txt" in names
        assert f"{top}/subdir" in names
        assert f"{top}/venv_allowed.txt" in names
        
        # Should exclude:
        # 1. The venv folder and its contents
        assert f"{top}/venv" not in names
        assert f"{top}/venv/lib_file.py" not in names
        
        # 2. The file named venv in subdir
        # Note: matches_excludes checks basename against pattern. "venv" matches "venv".
        assert f"{top}/subdir/venv" not in names

def test_create_archive_exclude_glob(exclude_setup, tmp_path):
    """Test glob pattern exclusion e.g. '*.py'"""
    archive = tmp_path / "glob.tar.gz"
    
    # Add a python file in root
    (exclude_setup / "script.py").write_text("print('hello')")
    
    create_archive(exclude_setup, archive, excludes=["*.py"])
    
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        top = exclude_setup.name
        
        assert f"{top}/main.txt" in names
        assert f"{top}/script.py" not in names
        # venv folder itself is NOT excluded, but lib_file.py inside it IS excluded
        assert f"{top}/venv" in names
        assert f"{top}/venv/lib_file.py" not in names
