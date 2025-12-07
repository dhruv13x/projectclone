#!/usr/bin/env python3
# src/projectclone/cli.py

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
import time
import tempfile
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

# Try to import RichHelpFormatter for better help output
try:
    from rich_argparse import RichHelpFormatter
except ImportError:
    RichHelpFormatter = argparse.HelpFormatter

# Define custom theme
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "command": "bold magenta",
})
console = Console(theme=custom_theme)

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
from .banner import print_logo
from . import cas_engine


def print_clone_help():
    """Prints the help panel for the clone/backup command using rich."""
    help_text = Text.from_markup(
        """
This command creates a backup of a project. It can operate in three main modes:
1. [bold]Folder Copy (default):[/bold] Creates a direct copy of the project.
2. [bold]Archive Mode (--archive):[/bold] Creates a compressed `.tar.gz` archive.
3. [bold]Incremental Mode (--incremental):[/bold] Uses `rsync` to efficiently update a backup.

[bold green]Usage Examples:[/bold green]
  [cyan]pv clone <note>[/cyan]                     Create a simple folder backup.
  [cyan]pv clone <note> --archive[/cyan]           Create a compressed tarball.
  [cyan]pv clone <note> --incremental[/cyan]      Create an rsync-based incremental backup.
  [cyan]pv clone <note> --cloud --bucket mybucket[/cyan] Create backup and upload to the cloud.
  [cyan]pv clone <note> --archive --exclude .venv[/cyan] Backup excluding .venv directory.
  [cyan]pv clone <note> --archive --exclude-symlinks[/cyan] Backup excluding all symbolic links.

[bold green]Key Options:[/bold green]
  [yellow]--dest <PATH>[/yellow]         Base destination folder for backups.
  [yellow]--keep <N>[/yellow]            Keep only the N newest backups for this project.
  [yellow]--exclude <PATTERN>[/yellow]   Exclude files/dirs matching the pattern (e.g. [cyan].venv[/cyan]).
  [yellow]--symlinks[/yellow]          Preserve symlinks as links (default: follow them).
  [yellow]--exclude-symlinks[/yellow]  Exclude all symlinks from the backup.
  [yellow]--manifest-sha[/yellow]       Generate SHA256 checksums for all files (slower).
  [yellow]--yes[/yellow]                 Skip the confirmation prompt.
  [yellow]--dry-run[/yellow]              Simulate the backup without writing files.

[bold green]Best Practices:[/bold green]
  • Run [cyan]pv init --smart[/cyan] first to auto-generate a [yellow].pvignore[/yellow] file for your project type.
  • Always exclude large generated folders like [cyan].venv[/cyan], [cyan]node_modules[/cyan], or [cyan]target[/cyan].
"""
    )
    panel = Panel(
        help_text,
        title="[bold magenta]Help: `pv clone` (Backup Command)[/bold magenta]",
        border_style="blue",
    )
    console.print(panel)


class RichHelpAction(argparse.Action):
    """A custom argparse action to show a rich-formatted help panel and exit."""
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        print_clone_help()
        parser.exit()


def get_cloud_credentials(resolver=None):
    """
    Resolves cloud credentials using the main project-vault resolver
    to ensure sources like Doppler are included.
    """
    if resolver is None:
        try:
            # Import the main credential resolver from the common library
            from src.common import credentials as resolver
        except ImportError:
            print("Error: Could not import 'src.common.credentials' for cloud operations.")
            return None, None, None

    # Use a dummy args object for the resolver
    class DummyArgs:
        key_id = None
        secret_key = None

    # Resolve credentials from all sources (CLI, Doppler, Env, Config)
    key_id, secret_key, source = resolver.resolve_credentials(DummyArgs(), allow_fail=True)

    # If keys are found, determine the provider type (b2 or s3)
    if key_id and secret_key:
        provider_info, _, _ = resolver.get_cloud_provider_info()
        provider_type = None
        if provider_info == "Backblaze B2":
            provider_type = "b2"
        elif provider_info == "AWS S3":
            provider_type = "s3"
        
        # Log the source for better debugging
        print(f"[dim]Authenticated via {source}[/dim]")
        return provider_type, key_id, secret_key
    
    return None, None, None


def upload_to_cloud(file_path, bucket_name, endpoint=None, log_fp=None):
    """
    Uploads the specified file to the cloud bucket.
    """
    try:
        from src.common import b2, s3
    except ImportError:
        msg = "Error: Could not import 'src.common'. Cloud features require the full Project Vault environment."
        print(msg)
        if log_fp:
            try:
                log_fp.write(msg + "\n")
            except Exception:
                pass
        return

    provider, key_id, app_key = get_cloud_credentials()

    if not key_id or not app_key:
        msg = "Error: Missing cloud credentials. Set PV_AWS_... or PV_B2_... environment variables."
        print(msg)
        if log_fp:
            try:
                log_fp.write(msg + "\n")
            except Exception:
                pass
        return

    manager = None
    try:
        # Logic: If endpoint provided OR we detected S3 creds, use S3Manager
        if endpoint or provider == "s3":
             manager = s3.S3Manager(key_id, app_key, bucket_name, endpoint)
        else:
             manager = b2.B2Manager(key_id, app_key, bucket_name)
    except Exception as e:
        msg = f"Error initializing cloud connection: {e}"
        print(msg)
        if log_fp:
            try:
                log_fp.write(msg + "\n")
            except Exception:
                pass
        return

    remote_name = file_path.name
    print(f"Uploading {remote_name} to bucket '{bucket_name}'...")
    if log_fp:
        try:
            log_fp.write(f"Starting upload of {remote_name} to {bucket_name}\n")
        except Exception:
            pass

    try:
        manager.upload_file(str(file_path), remote_name)
        print(f"✅ Upload successful: {remote_name}")
        if log_fp:
            try:
                log_fp.write(f"Upload successful: {remote_name}\n")
            except Exception:
                pass
    except Exception as e:
        msg = f"❌ Upload failed: {e}"
        print(msg)
        if log_fp:
            try:
                log_fp.write(msg + "\n")
            except Exception:
                pass


def vault_main():
    parser = argparse.ArgumentParser(prog="projectclone vault", description="Backup to content-addressable vault", formatter_class=RichHelpFormatter)
    parser.add_argument("source", nargs="?", default=".", help="The project directory to backup")
    parser.add_argument("vault_path", help="The destination directory for the vault")
    parser.add_argument("--name", help="Set a custom project name for the snapshot")
    parser.add_argument("--symlinks", action="store_true", help="preserve symlinks instead of copying targets")
    args = parser.parse_args(sys.argv[2:])

    try:
        source_path = os.path.abspath(os.path.expanduser(os.path.expandvars(args.source)))
        vault_path = os.path.abspath(os.path.expanduser(os.path.expandvars(args.vault_path)))
        cas_engine.backup_to_vault(source_path, vault_path, project_name=args.name, follow_symlinks=not args.symlinks)
    except Exception as e:
        console.print(f"[error]Error: {e}[/error]")
        sys.exit(1)


def parse_args():
    default_dest = Path.home() / "project_backups"
    p = argparse.ArgumentParser(
        description="Backup current directory into a destination folder",
        add_help=False # Disable default help
    )
    p.add_argument('-h', '--help', action=RichHelpAction, help='Show this help message and exit.')
    p.add_argument("short_note", nargs="?", default=None, help="short note to append to backup folder (e.g. 1000_pytests_passed)")
    p.add_argument("--dest", default=str(default_dest), help="base destination folder (default: ~/project_backups)")
    p.add_argument("-a", "--archive", action="store_true", help="create compressed tar.gz archive instead of folder")
    p.add_argument("--manifest", action="store_true", help="write MANIFEST.txt (sizes only)")
    p.add_argument("--manifest-sha", action="store_true", help="compute per-file SHA256 (can be slow)")
    p.add_argument("--symlinks", action="store_true", help="preserve symlinks instead of copying targets")
    p.add_argument("--exclude-symlinks", action="store_true", help="exclude symlinks from backup completely")
    p.add_argument("--keep", type=int, default=0, help="keep N newest backups for this project (0 = keep all)")
    p.add_argument("--yes", action="store_true", help="skip confirmation after space estimate")
    p.add_argument("--progress-interval", type=int, default=50, help="print progress every N files")
    p.add_argument("--exclude", action="append", default=[], help="exclude files/dirs (substring or glob) - can be used multiple times")
    p.add_argument("--dry-run", action="store_true", help="only estimate and show actions, do not write (for incremental allow rsync dry-run)")
    p.add_argument("--incremental", action="store_true", help="use rsync incremental (requires rsync)")
    p.add_argument("--verbose", action="store_true", help="verbose logging")
    p.add_argument("--cloud", action="store_true", help="upload the backup to cloud after creation")
    p.add_argument("--bucket", help="target cloud bucket name (required if --cloud is used)")
    p.add_argument("--endpoint", help="target cloud endpoint URL (optional)")
    p.add_argument(
        "--version", action="version", version=f"%(prog)s 1.0.0", help="Show program's version number and exit"
    )
    
    # A simple check to show help if no arguments are given.
    if len(sys.argv) == 1 or (len(sys.argv) == 2 and sys.argv[1] == '-h'):
        print_clone_help()
        sys.exit(0)
        
    args = p.parse_args()

    if not args.short_note:
        console.print("[bold red]Error:[/bold red] The 'short_note' argument is required.")
        print_clone_help()
        sys.exit(1)

    return args


def main():
    start_time = time.time()
    print_logo()
    if len(sys.argv) > 1 and sys.argv[1] == "vault":
        vault_main()
        return

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
            import shutil
            total, used, free = shutil.disk_usage(str(dest_base))
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
            print("Could not determine destination free space")
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
        final_output_path = None
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
            final_output_path = final
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
                    excludes=args.exclude,
                    exclude_symlinks=args.exclude_symlinks,
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
                final_output_path = final
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
            final_output_path = final
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
        
        # Cloud Upload Trigger
        if args.cloud and final_output_path and not args.dry_run:
            if not args.bucket:
                print("WARNING: --cloud specified but no --bucket provided. Skipping upload.")
                if log_fp:
                    try:
                        log_fp.write("WARNING: --cloud specified but no --bucket provided. Skipping upload.\n")
                    except Exception:
                        pass
            else:
                upload_to_cloud(final_output_path, args.bucket, args.endpoint, log_fp)

        print("Backup finished.")
        if log_fp:
            try:
                log_fp.write("Backup finished successfully\n")
            except Exception:
                pass

        # Summary
        end_time = time.time()
        duration = end_time - start_time
        
        if final_output_path and final_output_path.exists():
            size_str = "unknown size"
            try:
                if final_output_path.is_file():
                    size = final_output_path.stat().st_size
                    size_str = human_size(size)
                elif final_output_path.is_dir():
                    # Calculate dir size roughly for summary? Or just say directory.
                    # Re-walking might be slow for huge dirs, but user asked for "final size".
                    # Let's do a quick walk.
                    total = 0
                    for p in final_output_path.rglob('*'):
                        if p.is_file():
                            total += p.stat().st_size
                    size_str = human_size(total)
            except Exception:
                pass
            
            summary = f"✨ Summary: {size_str} created in {duration:.2f}s"
            print(summary)
            if log_fp:
                try:
                    log_fp.write(f"{summary}\n")
                except: pass

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
