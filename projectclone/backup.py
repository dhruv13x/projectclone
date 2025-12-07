# src/projectclone/backup.py

import os
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path
from typing import Optional, List

from .cleanup import cleanup_state
from .scanner import matches_excludes, walk_stats, get_project_ignore_spec
from .utils import ensure_dir, sha256_of_file, make_unique_path, human_size


def atomic_move(src: Path, dst: Path) -> None:
    """
    Try atomic rename (os.replace). If that fails due to cross-device link,
    fall back to shutil.move (which copies and removes).
    """
    try:
        os.replace(str(src), str(dst))
    except OSError:
        shutil.move(str(src), str(dst))


def create_archive(
    src: Path,
    dest_temp_file: Path,
    arcname: Optional[str] = None,
    preserve_symlinks: bool = False,
    manifest: bool = False,
    manifest_sha: bool = False,
    log_fp=None,
    excludes: Optional[List[str]] = None,
    exclude_symlinks: bool = False,
) -> Path:
    """
    Create gzip tarball at dest_temp_file (ensure proper .tar.gz suffix) and return its Path.
    - dest_temp_file may already include .tar.gz or not; we normalize.
    - This function will NOT register the final archive for cleanup; callers should register the
      containing tmp directory if they want automatic cleanup.
    - Replaced recursive tar.add with manual walk to support consistent excludes and symlink filtering.
    """
    # normalize final path to end with .tar.gz
    name = str(dest_temp_file)
    if name.endswith(".tar.gz"):
        final_temp = Path(name)
    else:
        final_temp = dest_temp_file.with_suffix(".tar.gz")

    ensure_dir(final_temp.parent)

    top_level = arcname or src.name
    ignore_spec = get_project_ignore_spec(src)

    try:
        if log_fp:
            try:
                log_fp.write(f"Creating archive at temp {final_temp}\n")
            except Exception:
                pass
        
        # We manually walk the directory to ensure excludes and symlink rules are respected
        # exactly like in copy_tree_atomic.
        # dereference=True in gettarinfo matches "not preserve_symlinks" (follow links).
        
        with tarfile.open(final_temp, "w:gz", format=tarfile.PAX_FORMAT) as tar:
            # Add the root directory itself first (if it's a directory)
            if src.is_dir():
                # For the root dir, we add it as a directory structure
                t_info = tar.gettarinfo(str(src), arcname=str(top_level))
                tar.addfile(t_info)
                
                # Walk
                # If preserve_symlinks is True, we generally don't want to follow them in os.walk
                # BUT os.walk followlinks=True is about *directory* symlinks.
                # If we preserve symlinks, we treat them as files, so we don't follow.
                for dirpath, dirnames, filenames in os.walk(src, followlinks=not preserve_symlinks):
                    d_root = Path(dirpath)
                    
                    # Filter directories (in-place for os.walk pruning)
                    i = 0
                    while i < len(dirnames):
                         d = dirnames[i]
                         full_d = d_root / d
                         if matches_excludes(full_d, excludes, root=src, ignore_spec=ignore_spec):
                             del dirnames[i]
                         else:
                             i += 1
                    
                    # Calculate arcname relative path
                    rel_dir = os.path.relpath(dirpath, str(src))
                    if rel_dir == ".":
                        base_arc = top_level
                    else:
                        base_arc = str(Path(top_level) / rel_dir)

                    # We already added the root, so skipping "." if we did
                    if rel_dir != ".":
                        t_info = tar.gettarinfo(dirpath, arcname=base_arc)
                        tar.addfile(t_info)

                    for fn in filenames:
                        src_fp = Path(dirpath) / fn
                        
                        # Check excludes
                        if matches_excludes(src_fp, excludes, root=src, ignore_spec=ignore_spec):
                            continue
                        
                        # Check symlink exclusion
                        if exclude_symlinks and src_fp.is_symlink():
                            if log_fp:
                                try:
                                    log_fp.write(f"Skipping symlink (excluded): {src_fp}\n")
                                except: pass
                            continue

                        arc_path = str(Path(base_arc) / fn)
                        
                        try:
                            # gettarinfo with dereference logic
                            # If preserve_symlinks=True -> dereference=False (store as link)
                            # If preserve_symlinks=False -> dereference=True (store content)
                            # NOTE: gettarinfo with dereference=True will raise FileNotFoundError if link is broken
                            
                            t_info = tar.gettarinfo(str(src_fp), arcname=arc_path)
                            
                            # Force dereference if requested and it's a symlink
                            if not preserve_symlinks and src_fp.is_symlink():
                                # gettarinfo(dereference=False) by default in some python versions?
                                # actually tar.gettarinfo has no dereference arg in older python?
                                # Wait, checked docs: gettarinfo(name, arcname, fileobj)
                                # It stat()s the file. os.stat follows symlinks. os.lstat does not.
                                # tarfile.gettarinfo uses os.lstat by default! 
                                # To follow symlinks, we need to pass the stat object of the target?
                                # Or just rely on addfile?
                                
                                # Actually, `tar.add` handles this. Since we are manual, we must do it.
                                # If we want to store CONTENT of a symlink:
                                # We must treat it as a file.
                                
                                if src_fp.exists(): # Target exists
                                    # stat the target
                                    s = src_fp.stat() 
                                    t_info = tarfile.TarInfo(name=arc_path)
                                    t_info.size = s.st_size
                                    t_info.mtime = s.st_mtime
                                    t_info.mode = s.st_mode
                                    t_info.type = tarfile.REGTYPE
                                    with open(src_fp, "rb") as f:
                                        tar.addfile(t_info, fileobj=f)
                                else:
                                    if log_fp:
                                        log_fp.write(f"Skipping broken link: {src_fp}\n")
                            else:
                                # Preserve symlink OR regular file
                                # gettarinfo uses lstat, so it handles symlinks correctly (as links)
                                # providing we don't override it.
                                
                                if t_info.isreg():
                                    with open(src_fp, "rb") as f:
                                        tar.addfile(t_info, fileobj=f)
                                else:
                                    # Symlink, directory, etc.
                                    tar.addfile(t_info)
                                    
                        except Exception as e:
                            if log_fp:
                                try:
                                    log_fp.write(f"Error adding {src_fp}: {e}\n")
                                except: pass

            else:
                # Single file backup
                tar.add(str(src), arcname=str(top_level), recursive=False)

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

    # Load ignore spec once for the whole operation
    ignore_spec = get_project_ignore_spec(src)

    file_count, total_size = walk_stats(src, follow_symlinks=not preserve_symlinks, excludes=excludes, ignore_spec=ignore_spec)
    if log_fp:
        try:
            log_fp.write(f"Copying {file_count} files, approx {human_size(total_size)}\n")
        except Exception:
            pass
    copied = 0

    for dirpath, dirnames, filenames in os.walk(src, followlinks=not preserve_symlinks):
        # We must filter dirnames AND check ignore_spec
        # Use helper from scanner which now handles spec

        d_root = Path(dirpath)

        # Filter directories
        # We must iterate backwards to delete
        i = 0
        while i < len(dirnames):
             d = dirnames[i]
             full_d = d_root / d
             if matches_excludes(full_d, excludes, root=src, ignore_spec=ignore_spec):
                 del dirnames[i]
             else:
                 i += 1

        rel_dir = os.path.relpath(dirpath, str(src))
        dest_dir = tmp_dir.joinpath(rel_dir) if rel_dir != "." else tmp_dir
        ensure_dir(dest_dir)
        for fn in filenames:
            src_fp = Path(dirpath) / fn
            if matches_excludes(src_fp, excludes, root=src, ignore_spec=ignore_spec):
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
    # rsync excludes need to be passed as arguments.
    # We should add .pvignore content to args if possible?
    # Rsync supports --exclude-from. We can pass the path to .pvignore if it exists!

    args = ["rsync", "-aH", "--delete"]
    # default exclude .git folder inside repo (conservative)
    args += ["--exclude", "*/.git/*"]

    for ex in (excludes or []):
        args += ["--exclude", ex]

    # Add .pvignore / .vaultignore
    pvignore = src / ".pvignore"
    if pvignore.exists():
        args += ["--exclude-from", str(pvignore)]

    vaultignore = src / ".vaultignore"
    if vaultignore.exists():
         args += ["--exclude-from", str(vaultignore)]

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
