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

import argparse
import datetime
import os
import sys
import tempfile
from pathlib import Path

from .backup import (
    atomic_move,
    create_archive,
    copy_tree_atomic,
    have_rsync,
    rsync_incremental,
)
from .cleanup import cleanup_state
from .rotation import rotate_backups
from .scanner import walk_stats
from .utils import sanitize_token, timestamp, human_size, ensure_dir, make_unique_path


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
    try:
        ensure_dir(dest_base)
    except Exception as e:
        print(f"ERROR: Could not create destination directory {dest_base}: {e}")
        sys.exit(2)

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
