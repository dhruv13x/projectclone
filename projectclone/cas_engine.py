# projectclone/projectclone/cas_engine.py

import sys
import os
from src.common import cas, manifest, ignore


def backup_to_vault(source_path: str, vault_path: str, project_name: str = None, hooks: dict = None, follow_symlinks: bool = False) -> str:
    """
    Performs a content-addressable backup of the source path to the vault.

    Args:
        source_path: The directory to back up.
        vault_path: The root directory of the backup vault.
        project_name: The name of the project. If None, it is derived from the source path.
        hooks: Dictionary containing lifecycle hooks (pre_snapshot, post_snapshot).

    Returns:
        The absolute path to the saved manifest file.
    """
    # Import hooks helper
    try:
        from src.common.hooks import run_hook
    except ImportError:
        # Fallback
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
        from src.common.hooks import run_hook

    # --- Run Pre-Snapshot Hook ---
    if hooks and "pre_snapshot" in hooks:
        run_hook("pre_snapshot", hooks["pre_snapshot"])

    # --- Safety Checks ---
    abs_source = os.path.abspath(source_path)
    abs_vault = os.path.abspath(vault_path)

    # Check 1: Identity
    if abs_source == abs_vault:
        print("❌ SAFETY ERROR: Source and Vault paths cannot be the same.")
        raise ValueError("Source and Vault paths cannot be the same.")

    # Prepare Ignore Patterns
    # Default ignores (system files)
    ignore_patterns = ['.git', '__pycache__', '.DS_Store']
    # Note: We do NOT ignore .pvignore or .vaultignore themselves, they should be backed up.

    # Load user ignores
    pvignore_path = os.path.join(source_path, ".pvignore")
    vaultignore_path = os.path.join(source_path, ".vaultignore")

    if os.path.exists(pvignore_path):
        ignore_patterns.extend(ignore.parse_ignore_file(pvignore_path))
    if os.path.exists(vaultignore_path):
        ignore_patterns.extend(ignore.parse_ignore_file(vaultignore_path))

    # Create PathSpec once
    spec = ignore.PathSpec.from_lines(ignore_patterns)

    # Check 2: Nesting (Vault inside Source)
    if abs_vault.startswith(abs_source) and (
        len(abs_vault) == len(abs_source) or abs_vault[len(abs_source)] == os.sep
    ):
        rel_vault = os.path.relpath(abs_vault, abs_source)
        if not spec.match_file(rel_vault, is_dir=True):
             print("❌ SAFETY ERROR: Vault path is inside Source path but not ignored.")
             print("   This causes infinite recursion (backing up the backup).")
             print(f"   Source: {abs_source}")
             print(f"   Vault:  {abs_vault}")
             print("   Fix: Add the vault directory to .pvignore or move the vault outside.")
             raise ValueError("Vault path is inside Source path but not ignored.")

    # --- Project Name Handling ---
    if project_name is None:
        project_name = os.path.basename(abs_source)
    
    # Simple sanitization
    import re
    safe_project_name = re.sub(r'[^a-zA-Z0-9_-]', '_', project_name)
    
    print(f"Using project name: {safe_project_name}")

    # Initialize the snapshot structure (Version 2)
    snapshot_data = manifest.create_snapshot_structure(source_path)
    
    objects_dir = os.path.join(vault_path, "objects")
    snapshots_dir = os.path.join(vault_path, "snapshots")

    print(f"Starting backup of '{source_path}' to '{vault_path}'...")

    # Walk through the source directory
    for root, dirs, files in os.walk(source_path, followlinks=follow_symlinks):
        # Calculate relative path for directory check
        rel_root = os.path.relpath(root, source_path)
        if rel_root == ".":
            rel_root = ""

        # Prune ignored directories
        for i in range(len(dirs) - 1, -1, -1):
            d = dirs[i]
            # Path relative to source root
            dir_rel = os.path.join(rel_root, d) if rel_root else d

            if spec.match_file(dir_rel, is_dir=True):
                print(f"Skipped directory: {dir_rel}")
                del dirs[i]

        for file in files:
            file_rel = os.path.join(rel_root, file) if rel_root else file

            if spec.match_file(file_rel, is_dir=False):
                print(f"Skipped file: {file_rel}")
                continue

            full_path = os.path.join(root, file)

            try:
                # Check for Symlink
                # If follow_symlinks is True, we treat symlinks to files as regular files (dereference)
                if os.path.islink(full_path) and not follow_symlinks:
                    target_path = os.readlink(full_path)
                    lstat = os.lstat(full_path)

                    snapshot_data["files"][file_rel] = {
                        "type": "symlink",
                        "target": target_path,
                        "mode": lstat.st_mode,
                        "mtime": lstat.st_mtime
                    }
                    print(f"Symlink: {file_rel} -> {target_path}")
                else:
                    # Regular file OR symlink when follow_symlinks=True
                    # Capture Metadata
                    stat = os.stat(full_path)

                    # Store Object
                    file_hash = cas.store_object(full_path, objects_dir)

                    # Record Entry (Version 2 Format)
                    snapshot_data["files"][file_rel] = {
                        "hash": file_hash,
                        "mode": stat.st_mode,
                        "mtime": stat.st_mtime,
                        "size": stat.st_size
                    }

                    print(f"Hashed: {file_rel} -> {file_hash}")
            except Exception as e:
                print(f"Error processing {file_rel}: {e}")
                raise

    # Save the manifest
    manifest_path = manifest.save_manifest(snapshot_data, snapshots_dir, project_name=safe_project_name)
    print(f"Backup complete. Manifest saved to: {manifest_path}")
    
    # --- Run Post-Snapshot Hook ---
    if hooks and "post_snapshot" in hooks:
        run_hook("post_snapshot", hooks["post_snapshot"])
    
    return manifest_path
