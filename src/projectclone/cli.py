#!/usr/bin/env python3
"""
create_backup.py

complete, corrected, production-ready single-file backup tool.

Highlights / fixes applied compared to earlier drafts:
 - Fixed archive naming bug (no double suffixes)
 - Avoid registering final artifacts for automatic cleanup (register tmp dirs only)
 - Ensure tmp dirs removed on rsync/archive errors (avoid orphaned temp dirs)
 - Safe symlink creation and clear setuid/setgid on copied files
 - Consistent excludes behavior relative to project root
 - Better defensive error handling and cleanup bookkeeping
 - Propagate --dry-run to incremental (rsync) mode
 - Set restrictive permissions on per-run log file (where supported)
 - Unregister temp artifacts after moving them into place to avoid accidental cleanup

Usage (examples):
  python create_backup.py 1000_pytests_passed
  python create_backup.py --archive --manifest --keep 5 2025_release_candidate

Note for Android: ensure Python/process has permission to write to --dest (termux/app context).
"""

from pathlib import Path
import argparse
import datetime
import fnmatch
import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Optional, List, Tuple

# ---------------- Helpers ----------------

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


# ---------------- excludes / scanning ----------------

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


# ----------------- Cleanup state & signals -----------------

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


# ----------------- atomic move helper -----------------

def atomic_move(src: Path, dst: Path) -> None:
    """
    Try atomic rename (os.replace). If that fails due to cross-device link,
    fall back to shutil.move (which copies and removes).
    """
    try:
        os.replace(str(src), str(dst))
    except OSError:
        shutil.move(str(src), str(dst))


# ----------------- Archive creation (safe) -----------------

def create_archive(
    src: Path,
    dest_temp_file: Path,
    arcname: Optional[str] = None,
    preserve_symlinks: bool = False,
    manifest: bool = False,
    manifest_sha: bool = False,
    log_fp=None,
) -> Path:
    """
    Create gzip tarball at dest_temp_file (ensure proper .tar.gz suffix) and return its Path.
    - dest_temp_file may already include .tar.gz or not; we normalize.
    - This function will NOT register the final archive for cleanup; callers should register the
      containing tmp directory if they want automatic cleanup.
    """
    # normalize final path to end with .tar.gz
    name = str(dest_temp_file)
    if name.endswith(".tar.gz"):
        final_temp = Path(name)
    else:
        final_temp = dest_temp_file.with_suffix(".tar.gz")

    if log_fp:
        try:
            log_fp.write(f"Creating archive at temp {final_temp}\n")
        except Exception:
            pass
    ensure_dir(final_temp.parent)

    top_level = arcname or src.name

    try:
        # Use PAX format for better compatibility.
        # Pass dereference to tarfile.open (control whether symlinks are followed).
        with tarfile.open(final_temp, "w:gz", format=tarfile.PAX_FORMAT, dereference=not preserve_symlinks) as tar:
            if src.is_file():
                tar.add(str(src), arcname=str(top_level), recursive=False)
            else:
                tar.add(str(src), arcname=str(top_level), recursive=True)
    except Exception:
        # remove partial archive if any
        try:
            if final_temp.exists():
                final_temp.unlink()
        except Exception:
            pass
        raise

    # write SHA for archive if requested
    if manifest or manifest_sha:
        try:
            h = sha256_of_file(final_temp)
            sha_fp = final_temp.with_name(final_temp.name + ".sha256")
            sha_fp.write_text(f"{h}  {final_temp.name}\n")
            if log_fp:
                try:
                    log_fp.write(f"Archive checksum written: {sha_fp}\n")
                except Exception:
                    pass
        except Exception as e:
            if log_fp:
                try:
                    log_fp.write(f"Error writing archive checksum: {e}\n")
                except Exception:
                    pass

    return final_temp


# ----------------- Copy tree atomic (safe) -----------------

def _safe_symlink_create(src_link: Path, dst: Path, log_fp=None) -> None:
    """
    Create a symlink at dst pointing to the same target as src_link.
    If dst exists, remove it first. Non-fatal on failure.
    """
    try:
        linkto = os.readlink(src_link)
    except Exception as e:
        if log_fp:
            try:
                log_fp.write(f"Could not read symlink target for {src_link}: {e}\n")
            except Exception:
                pass
        return

    try:
        if dst.exists() or dst.is_symlink():
            try:
                dst.unlink()
            except Exception:
                pass
        os.symlink(linkto, dst)
    except Exception as e:
        if log_fp:
            try:
                log_fp.write(f"Symlink create failed for {src_link} -> {linkto}: {e}\n")
            except Exception:
                pass


def _clear_dangerous_bits(path: Path) -> None:
    """
    Clear setuid/setgid bits on file (security measure).
    Non-fatal if chmod fails.
    """
    try:
        mode = path.stat().st_mode
        safe_mode = mode & ~(stat.S_ISUID | stat.S_ISGID)
        os.chmod(path, safe_mode)
    except Exception:
        pass


def copy_tree_atomic(
    src: Path,
    dest_parent: Path,
    dest_name: str,
    preserve_symlinks: bool = False,
    manifest: bool = False,
    manifest_sha: bool = False,
    log_fp=None,
    show_progress: bool = True,
    progress_interval: int = 50,
    excludes: Optional[List[str]] = None,
) -> Path:
    """
    Copy a tree into a temporary directory next to dest_parent and move it into place.
    - preserve_symlinks: keep symlinks instead of copying target content
    - excludes: list of exclude patterns (see matches_excludes)
    """
    tmp_dir = dest_parent / f".tmp_{dest_name}_{os.getpid()}"
    if tmp_dir.exists():
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass
    ensure_dir(tmp_dir.parent)
    ensure_dir(tmp_dir)
    cleanup_state.register_tmp_dir(tmp_dir)

    file_count, total_size = walk_stats(src, follow_symlinks=not preserve_symlinks, excludes=excludes)
    if log_fp:
        try:
            log_fp.write(f"Copying {file_count} files, approx {human_size(total_size)}\n")
        except Exception:
            pass
    copied = 0

    for dirpath, dirnames, filenames in os.walk(src, followlinks=not preserve_symlinks):
        dirnames[:] = [d for d in dirnames if not matches_excludes(Path(dirpath) / d, excludes, root=src)]
        rel_dir = os.path.relpath(dirpath, str(src))
        dest_dir = tmp_dir.joinpath(rel_dir) if rel_dir != "." else tmp_dir
        ensure_dir(dest_dir)
        for fn in filenames:
            src_fp = Path(dirpath) / fn
            if matches_excludes(src_fp, excludes, root=src):
                if log_fp:
                    try:
                        log_fp.write(f"Excluded {src_fp}\n")
                    except Exception:
                        pass
                continue
            dest_fp = dest_dir / fn
            try:
                if not (src_fp.is_file() or src_fp.is_symlink()):
                    if log_fp:
                        try:
                            log_fp.write(f"Skipping special file: {src_fp}\n")
                        except Exception:
                            pass
                    continue

                if src_fp.is_symlink() and preserve_symlinks:
                    _safe_symlink_create(src_fp, dest_fp, log_fp=log_fp)
                else:
                    # copy2 preserves metadata like mtime and permission bits
                    shutil.copy2(src_fp, dest_fp, follow_symlinks=not preserve_symlinks)
                    # clear setuid/setgid on copied file for safety
                    _clear_dangerous_bits(dest_fp)

                copied += 1
                if show_progress and (copied % progress_interval == 0 or copied == file_count):
                    print(f"Copied {copied}/{file_count} files ...")
            except Exception as e:
                if log_fp:
                    try:
                        log_fp.write(f"ERROR copying {src_fp}: {e}\n")
                    except Exception:
                        pass

    # write manifest (sizes)
    if manifest:
        man_fp = tmp_dir / "MANIFEST.txt"
        try:
            with man_fp.open("w", encoding="utf-8") as mf:
                for p in tmp_dir.rglob("*"):
                    if p.is_file():
                        try:
                            rel = p.relative_to(tmp_dir)
                            sz = p.stat().st_size
                            mf.write(f"{rel}\t{sz}\n")
                        except Exception:
                            pass
            if log_fp:
                try:
                    log_fp.write(f"Manifest written at {man_fp}\n")
                except Exception:
                    pass
        except Exception as e:
            if log_fp:
                try:
                    log_fp.write(f"Manifest write failed: {e}\n")
                except Exception:
                    pass

    # write per-file SHA manifest optionally
    if manifest_sha:
        sha_fp = tmp_dir / "MANIFEST_SHA256.txt"
        try:
            with sha_fp.open("w", encoding="utf-8") as sf:
                for p in tmp_dir.rglob("*"):
                    if p.is_file():
                        try:
                            rel = p.relative_to(tmp_dir)
                            h = sha256_of_file(p)
                            sf.write(f"{h}  {rel}\n")
                        except Exception as e:
                            if log_fp:
                                try:
                                    log_fp.write(f"SHA error for {p}: {e}\n")
                                except Exception:
                                    pass
            if log_fp:
                try:
                    log_fp.write(f"SHA manifest written at {sha_fp}\n")
                except Exception:
                    pass
        except Exception as e:
            if log_fp:
                try:
                    log_fp.write(f"SHA manifest write failed: {e}\n")
                except Exception:
                    pass

    final_dest = dest_parent / dest_name
    final_dest = make_unique_path(final_dest)

    # atomic move with cross-device fallback
    try:
        atomic_move(tmp_dir, final_dest)
        cleanup_state.unregister_tmp_dir(tmp_dir)
        if log_fp:
            try:
                log_fp.write(f"Backup moved into place: {final_dest}\n")
            except Exception:
                pass
    except Exception as e:
        if log_fp:
            try:
                log_fp.write(f"Failed to move backup into place: {e}\n")
            except Exception:
                pass
        # leave tmp_dir for inspection/cleanup if move failed
        raise

    return final_dest


# ----------------- Rotation -----------------

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


# ----------------- Rsync incremental helper -----------------

def have_rsync() -> bool:
    try:
        subprocess.run(["rsync", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception:
        return False


def rsync_incremental(
    src: Path,
    dest_parent: Path,
    dest_name: str,
    link_dest: Optional[Path],
    excludes: Optional[List[str]] = None,
    log_fp=None,
    dry_run: bool = False,
) -> Path:
    """
    Use rsync to create an incremental backup (hardlinks to link_dest). Copies into tmp dir and then moves.
    dry_run: if True, rsync will be invoked with --dry-run and the tmpdir will be removed after.
    """
    args = ["rsync", "-aH", "--delete"]
    # default exclude .git folder inside repo (conservative)
    args += ["--exclude", "*/.git/*"]
    for ex in (excludes or []):
        args += ["--exclude", ex]
    if link_dest:
        args += ["--link-dest", str(link_dest)]
    if dry_run:
        args += ["--dry-run"]

    tmp_dir = dest_parent / f".tmp_{dest_name}_{os.getpid()}"
    if tmp_dir.exists():
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass
    ensure_dir(tmp_dir)
    cleanup_state.register_tmp_dir(tmp_dir)

    args += [str(src) + "/", str(tmp_dir) + "/"]
    if log_fp:
        try:
            log_fp.write(f"Running rsync: {' '.join(args)}\n")
        except Exception:
            pass

    res = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        if log_fp:
            try:
                log_fp.write(f"rsync failed: {res.returncode}\nstdout:\n{res.stdout.decode(errors='replace')}\nstderr:\n{res.stderr.decode(errors='replace')}\n")
            except Exception:
                pass
        # cleanup tmp_dir on error to avoid orphaned tmps
        try:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
                cleanup_state.unregister_tmp_dir(tmp_dir)
        except Exception:
            pass
        raise RuntimeError("rsync failed")

    # If it was a dry-run, remove the tmp_dir and return a placeholder
    if dry_run:
        # cleanup temp copy created by --dry-run rsync run
        try:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
                cleanup_state.unregister_tmp_dir(tmp_dir)
        except Exception:
            pass
        if log_fp:
            try:
                log_fp.write("Rsync dry-run completed (no files moved into place)\n")
            except Exception:
                pass
        # return an indicative path (not created)
        return dest_parent / f"{dest_name}-DRYRUN"

    final_dest = dest_parent / dest_name
    final_dest = make_unique_path(final_dest)
    try:
        atomic_move(tmp_dir, final_dest)
        cleanup_state.unregister_tmp_dir(tmp_dir)
        if log_fp:
            try:
                log_fp.write(f"Rsync backup moved into place: {final_dest}\n")
            except Exception:
                pass
    except Exception as e:
        # leave tmp_dir for inspection if move fails
        if log_fp:
            try:
                log_fp.write(f"Failed to move rsync temp dir into place: {e}\n")
            except Exception:
                pass
        raise
    return final_dest


# ----------------- CLI & main -----------------

def parse_args():
    p = argparse.ArgumentParser(description="Backup current directory into /sdcard/project_backups or custom dest")
    p.add_argument("short_note", help="short note to append to backup folder (e.g. 1000_pytests_passed)")
    p.add_argument("--dest", default="/sdcard/project_backups", help="base destination folder (default: /sdcard/project_backups)")
    p.add_argument("-a", "--archive", action="store_true", help="create compressed tar.gz archive instead of folder")
    p.add_argument("--manifest", action="store_true", help="write MANIFEST.txt (sizes only)")
    p.add_argument("--manifest-sha", action="store_true", help="compute per-file SHA256 (can be slow)")
    p.add_argument("--symlinks", action="store_true", help="preserve symlinks instead of copying targets")
    p.add_argument("--keep", type=int, default=0, help="keep N newest backups for this project (0 = keep all)")
    p.add_argument("--yes", action="store_true", help="skip confirmation after space estimate")
    p.add_argument("--progress-interval", type=int, default=50, help="print progress every N files")
    p.add_argument("--exclude", action="append", default=[], help="exclude files/dirs (substring or glob) - can be used multiple times")
    p.add_argument("--dry-run", action="store_true", help="only estimate and show actions, do not write (for incremental allow rsync dry-run)")
    p.add_argument("--incremental", action="store_true", help="use rsync incremental (requires rsync)")
    p.add_argument("--verbose", action="store_true", help="verbose logging")
    return p.parse_args()


def main():
    args = parse_args()
    cwd = Path.cwd()
    raw_foldername = cwd.name or "root"
    foldername = sanitize_token(raw_foldername)
    short_note = sanitize_token(args.short_note)
    ts = timestamp()
    dest_name = f"{ts}-{foldername}-{short_note}"
    dest_base = Path(args.dest).expanduser()
    ensure_dir(dest_base)

    # create per-run log file and set restrictive permissions where possible
    per_log = dest_base / f"backup_{ts}_{foldername}.log"
    try:
        per_log.touch(exist_ok=True)
        try:
            per_log.chmod(0o600)
        except Exception:
            # on some filesystems (e.g. FAT) chmod may fail; ignore
            pass
    except Exception:
        # fallback: ignore log creation errors but proceed (we'll guard writes)
        pass

    # open log file for append and pass the file object around as log_fp
    try:
        log_fp = per_log.open("a", encoding="utf-8")
    except Exception:
        log_fp = None

    if log_fp:
        try:
            log_fp.write(f"\n[{datetime.datetime.now().isoformat()}] Starting backup for {cwd} -> base {dest_base}\n")
            log_fp.flush()
        except Exception:
            pass
    else:
        # fallback simple logging to stdout/stderr
        print(f"[INFO] Starting backup for {cwd} -> base {dest_base}")

    try:
        print("Scanning files to estimate size... (this may take a few seconds)")
        files, total_size = walk_stats(cwd, follow_symlinks=not args.symlinks, excludes=args.exclude)
        print(f"Will back up ~{files} files, total ≈ {human_size(total_size)}")
        if log_fp:
            try:
                log_fp.write(f"Will back up {files} files, approx {total_size} bytes\n")
                log_fp.flush()
            except Exception:
                pass

        try:
            statvfs = os.statvfs(str(dest_base))
            free = statvfs.f_frsize * statvfs.f_bavail
            print(f"Free space at destination: {human_size(free)}")
            if log_fp:
                try:
                    log_fp.write(f"Free space: {free} bytes\n")
                except Exception:
                    pass
            if total_size > free:
                print("WARNING: estimated backup size exceeds free space at destination.")
                if log_fp:
                    try:
                        log_fp.write("WARNING: insufficient free space\n")
                    except Exception:
                        pass
        except Exception:
            if log_fp:
                try:
                    log_fp.write("Could not determine destination free space\n")
                except Exception:
                    pass

        # Dry-run behavior:
        # - If --dry-run and --incremental: allow incremental to run with rsync --dry-run
        # - If --dry-run and not --incremental: report and exit (no writes)
        if args.dry_run and not args.incremental:
            print("Dry run: no files will be written. Exiting after report.")
            if log_fp:
                try:
                    log_fp.write("Dry run completed\n")
                except Exception:
                    pass
            # close log if opened
            if log_fp:
                try:
                    log_fp.close()
                except Exception:
                    pass
            return

        if not args.yes:
            try:
                ans = input("Proceed with backup? [y/N] ").strip().lower()
            except EOFError:
                ans = "n"
            if ans not in ("y", "yes"):
                print("Aborted by user.")
                if log_fp:
                    try:
                        log_fp.write("Aborted by user\n")
                    except Exception:
                        pass
                if log_fp:
                    try:
                        log_fp.close()
                    except Exception:
                        pass
                sys.exit(1)

        # Main operation
        if args.incremental:
            if not have_rsync():
                raise RuntimeError("incremental requested but rsync not found")
            prev_candidates = sorted(
                [p for p in dest_base.iterdir() if p.is_dir() and p.name.find(f"-{foldername}-") != -1],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            link_dest = prev_candidates[0] if prev_candidates else None
            final = rsync_incremental(
                cwd,
                dest_base,
                dest_name,
                link_dest,
                excludes=args.exclude,
                log_fp=log_fp,
                dry_run=args.dry_run,
            )
            print(f"Incremental backup created: {final}")
            if log_fp:
                try:
                    log_fp.write(f"Incremental backup created: {final}\n")
                except Exception:
                    pass

        elif args.archive:
            # Use a TemporaryDirectory for safe staging of archive
            with tempfile.TemporaryDirectory(prefix=f".tmp_{dest_name}_", dir=str(dest_base)) as tmpdir:
                tmpdir_path = Path(tmpdir)
                # register tmpdir for cleanup in case of signals/early exit
                cleanup_state.register_tmp_dir(tmpdir_path)

                # create the archive file path (without double-suffix issues)
                tmp_archive_path = tmpdir_path / f"{dest_name}.tar.gz"
                if log_fp:
                    try:
                        log_fp.write(f"Creating archive to temp: {tmp_archive_path}\n")
                    except Exception:
                        pass

                archive_temp = create_archive(
                    cwd,
                    tmp_archive_path,
                    arcname=dest_name,
                    preserve_symlinks=args.symlinks,
                    manifest=args.manifest,
                    manifest_sha=args.manifest_sha,
                    log_fp=log_fp,
                )

                # Move archive to final destination (with unique naming if necessary)
                final = make_unique_path(dest_base / f"{dest_name}.tar.gz")
                try:
                    atomic_move(archive_temp, final)
                except Exception as e:
                    if log_fp:
                        try:
                            log_fp.write(f"Failed to move archive into place: {e}\n")
                        except Exception:
                            pass
                    raise

                # Move checksum if it exists
                sha_src = archive_temp.with_name(archive_temp.name + ".sha256")
                if sha_src.exists():
                    sha_dst = final.with_name(final.name + ".sha256")
                    try:
                        atomic_move(sha_src, sha_dst)
                    except Exception as e:
                        if log_fp:
                            try:
                                log_fp.write(f"Failed to move archive sha into place: {e}\n")
                            except Exception:
                                pass

                # Unregister temp directory so cleanup won't remove the moved archive
                cleanup_state.unregister_tmp_dir(tmpdir_path)

                # Unregister any temp files that may have been registered (defensive)
                try:
                    cleanup_state.unregister_tmp_file(archive_temp)
                    cleanup_state.unregister_tmp_file(sha_src)
                except Exception:
                    pass

                print(f"Archive created: {final}")
                if log_fp:
                    try:
                        log_fp.write(f"Archive created at {final}\n")
                    except Exception:
                        pass

        else:
            final = copy_tree_atomic(
                cwd,
                dest_base,
                dest_name,
                preserve_symlinks=args.symlinks,
                manifest=args.manifest,
                manifest_sha=args.manifest_sha,
                log_fp=log_fp,
                show_progress=True,
                progress_interval=args.progress_interval,
                excludes=args.exclude,
            )
            print(f"Folder backup created: {final}")
            if log_fp:
                try:
                    log_fp.write(f"Folder backup created: {final}\n")
                except Exception:
                    pass

        if args.keep > 0:
            rotate_backups(dest_base, args.keep, foldername)
            if log_fp:
                try:
                    log_fp.write(f"Rotation kept {args.keep} backups for project {foldername}\n")
                except Exception:
                    pass

        print("Backup finished.")
        if log_fp:
            try:
                log_fp.write("Backup finished successfully\n")
            except Exception:
                pass

    except Exception as e:
        print("ERROR:", e)
        if log_fp:
            try:
                log_fp.write(f"ERROR: {e}\n")
                log_fp.flush()
            except Exception:
                pass
        cleanup_state.cleanup(verbose=True)
        if log_fp:
            try:
                log_fp.close()
            except Exception:
                pass
        sys.exit(2)
    finally:
        if log_fp:
            try:
                log_fp.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()