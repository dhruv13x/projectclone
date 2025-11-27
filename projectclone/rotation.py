# src/projectclone/rotation.py

import re
import shutil
from pathlib import Path


def rotate_backups(dest_base: Path, keep: int, project_name: str) -> None:
    if keep <= 0:
        return
    # match prefix: YYYY-MM-DD_HHMMSS-<project>-
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}-" + re.escape(project_name) + r"-")
    matches = [p for p in dest_base.iterdir() if pattern.match(p.name)]
    matches = sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)
    to_delete = matches[keep:]
    for p in to_delete:
        try:
            if p.is_file():
                p.unlink()
            else:
                shutil.rmtree(p)
        except Exception:
            pass
