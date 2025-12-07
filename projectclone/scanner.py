# src/projectclone/scanner.py

import fnmatch
import os
from pathlib import Path
from typing import Optional, List, Tuple
from src.common.ignore import PathSpec, parse_ignore_file


def get_project_ignore_spec(root: Path) -> PathSpec:
    """
    Load .pvignore and .vaultignore from root and return a PathSpec.
    """
    patterns = []
    # Support both for compatibility, prefer .pvignore
    for fname in [".vaultignore", ".pvignore"]:
        fpath = root / fname
        if fpath.exists():
            patterns.extend(parse_ignore_file(str(fpath)))

    return PathSpec.from_lines(patterns)


def matches_excludes(
    path: Path,
    excludes: Optional[List[str]] = None,
    root: Optional[Path] = None,
    ignore_spec: Optional[PathSpec] = None
) -> bool:
    """
    Return True if path should be excluded.
    Checks against:
    1. ignore_spec (PathSpec object for .pvignore logic)
    2. excludes (Legacy list of patterns/substrings)
    """
    path = Path(path).resolve()
    root = Path(root or Path.cwd()).resolve()

    try:
        rel = path.relative_to(root)
        rel_str = str(rel).replace("\\", "/")
    except ValueError:
        # path outside root -> use absolute path
        rel_str = str(path).replace("\\", "/")

    # 1. Check PathSpec (Gitignore logic)
    if ignore_spec:
        # Check if directory? matches_excludes doesn't know for sure without stat,
        # but usually we call this on existing files/dirs.
        # However, for performance we might pass is_dir if known.
        # Here we assume file unless we check.
        # PathSpec needs correct is_dir for trailing slash matches.
        # Checking is_dir here might be slow?
        is_dir = path.is_dir()
        if ignore_spec.match_file(rel_str, is_dir=is_dir):
            return True

    # 2. Legacy Excludes Logic
    if excludes:
        basename = path.name
        path_str = str(path)

        for pattern in excludes:
            norm = pattern.strip()
            if norm.startswith("./"):
                norm = norm[2:]
            if (
                fnmatch.fnmatch(rel_str, norm)
                or fnmatch.fnmatch(basename, norm)
                or fnmatch.fnmatch(path_str, norm)
            ):
                return True

    return False


def walk_stats(
    root: Path,
    follow_symlinks: bool = False,
    excludes: Optional[List[str]] = None,
    ignore_spec: Optional[PathSpec] = None
) -> Tuple[int, int]:
    """
    Walk directory tree and return (total_files, total_size) respecting excludes and ignore_spec.
    If ignore_spec is None, it attempts to load from root.
    """
    total_size = 0
    total_files = 0
    excludes = excludes or []

    if ignore_spec is None:
        ignore_spec = get_project_ignore_spec(root)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        # filter directory names in-place
        # Note: We need to check if directory matches ignores.

        # Optimization: We can check excludes and ignore_spec here.

        # We need relative path for ignore_spec
        # dirpath is absolute usually (from os.walk(root))

        d_root = Path(dirpath)

        # Filter directories
        i = 0
        while i < len(dirnames):
            d = dirnames[i]
            full_d = d_root / d
            if matches_excludes(full_d, excludes, root=root, ignore_spec=ignore_spec):
                del dirnames[i]
            else:
                i += 1

        for fname in filenames:
            full = d_root / fname
            if matches_excludes(full, excludes, root=root, ignore_spec=ignore_spec):
                continue
            try:
                if not (full.is_file() or full.is_symlink()):
                    continue
                total_files += 1
                try:
                    total_size += full.stat().st_size
                except OSError:
                    pass
            except Exception:
                pass
    return total_files, total_size
