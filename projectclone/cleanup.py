# src/projectclone/cleanup.py

import signal
import shutil
import sys
from pathlib import Path
from typing import List


class CleanupState:
    def __init__(self) -> None:
        self.tmp_paths: List[Path] = []  # directories to remove
        self.tmp_files: List[Path] = []  # files to remove (kept minimal)

    def register_tmp_dir(self, p: Path) -> None:
        if p not in self.tmp_paths:
            self.tmp_paths.append(p)

    def register_tmp_file(self, p: Path) -> None:
        if p not in self.tmp_files:
            self.tmp_files.append(p)

    def unregister_tmp_dir(self, p: Path) -> None:
        self.tmp_paths = [x for x in self.tmp_paths if x != p]

    def unregister_tmp_file(self, p: Path) -> None:
        self.tmp_files = [x for x in self.tmp_files if x != p]

    def cleanup(self, verbose: bool = False) -> None:
        # remove files first
        for p in list(self.tmp_files):
            try:
                if p.exists():
                    p.unlink()
                    if verbose:
                        print("Removed temp file", p)
                self.unregister_tmp_file(p)
            except Exception:
                pass
        for p in list(self.tmp_paths):
            try:
                if p.exists():
                    shutil.rmtree(p)
                    if verbose:
                        print("Removed temp dir", p)
                self.unregister_tmp_dir(p)
            except Exception:
                pass


cleanup_state = CleanupState()


def _signal_handler(signum, frame):
    print("\nSignal received, cleaning up temporary files...")
    cleanup_state.cleanup(verbose=True)
    sys.exit(2)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
