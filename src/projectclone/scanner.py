import fnmatch
import os
from pathlib import Path
from typing import Optional, List, Tuple


def matches_excludes(path: Path, excludes: Optional[List[str]] = None, root: Optional[Path] = None) -> bool:
    """
    Return True if path should be excluded.
    - `excludes` is a list of patterns or substrings.
    - Patterns are compared against the path relative to `root` (default: cwd)
      as well as the basename and absolute path. Substring matches are also applied.
    """
    if not excludes:
        return False

    path = Path(path).resolve()
    root = Path(root or Path.cwd()).resolve()

    try:
        rel = path.relative_to(root)
        rel_str = str(rel).replace("\\", "/")
    except ValueError:
        # path outside root -> use absolute path
        rel_str = str(path).replace("\\", "/")

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
            or (norm in rel_str)
            or (norm in basename)
        ):
            return True
    return False


def walk_stats(root: Path, follow_symlinks: bool = False, excludes: Optional[List[str]] = None) -> Tuple[int, int]:
    """
    Walk directory tree and return (total_files, total_size) respecting excludes.
    follow_symlinks controls os.walk followlinks.
    """
    total_size = 0
    total_files = 0
    excludes = excludes or []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        # filter directory names in-place using excludes
        dirnames[:] = [d for d in dirnames if not matches_excludes(Path(dirpath) / d, excludes, root=root)]
        for fname in filenames:
            full = Path(dirpath) / fname
            if matches_excludes(full, excludes, root=root):
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
