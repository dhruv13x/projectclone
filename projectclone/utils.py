# src/projectclone/utils.py

import datetime
import hashlib
import re
from pathlib import Path


def sanitize_token(s: str) -> str:
    if not s:
        return "note"
    s = s.replace(" ", "_")
    s = re.sub(r"[:\\/]+", "_", s)
    s = re.sub(r"[^A-Za-z0-9_\-\.]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "note"


def timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"


def sha256_of_file(path: Path, block_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(block_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def make_unique_path(base_path: Path) -> Path:
    if not base_path.exists():
        return base_path
    i = 1
    while True:
        p = base_path.with_name(f"{base_path.name}-{i}")
        if not p.exists():
            return p
        i += 1
