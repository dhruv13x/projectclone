# projectclone/projectclone/gc_engine.py

import os
import sys
from src.common import manifest


def run_garbage_collection(vault_path: str, dry_run: bool = False) -> None:
    """
    Performs garbage collection on the vault by removing orphaned objects
    (objects not referenced by any snapshot).

    Args:
        vault_path: Path to the local vault directory.
        dry_run: If True, only simulate deletion.
    """
    snapshots_dir = os.path.join(vault_path, "snapshots")
    objects_dir = os.path.join(vault_path, "objects")
    
    if not os.path.exists(snapshots_dir) or not os.path.exists(objects_dir):
        print("Vault directories missing. Nothing to clean.")
        return

    print(f"Starting Garbage Collection on: {vault_path}")
    if dry_run:
        print("⚠️ DRY RUN MODE: No files will be deleted.")

    # --- Phase 1: Build Keep List ---
    print("Scanning snapshots to build reference list...")
    referenced_hashes = set()
    
    try:
        for filename in os.listdir(snapshots_dir):
            if not filename.endswith(".json"):
                continue
                
            manifest_path = os.path.join(snapshots_dir, filename)
            try:
                # Using manifest.load_manifest as per standard
                data = manifest.load_manifest(manifest_path)
                files = data.get("files", {})
                for file_hash in files.values():
                    referenced_hashes.add(file_hash)
            except Exception as e:
                # CRITICAL SAFETY: Abort if ANY snapshot is unreadable
                # We assume unreadable snapshots might reference objects we shouldn't delete.
                raise RuntimeError(f"CRITICAL SAFETY ERROR: Failed to parse snapshot '{filename}': {e}. Aborting GC to prevent data loss.")
                
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)

    print(f"Found {len(referenced_hashes)} active objects referenced by snapshots.")

    # --- Phase 2: Sweep Objects ---
    print("Sweeping objects directory...")
    orphaned_count = 0
    reclaimed_bytes = 0
    
    for filename in os.listdir(objects_dir):
        file_path = os.path.join(objects_dir, filename)
        
        if not os.path.isfile(file_path):
            continue
            
        # The filename IS the hash in the objects directory
        file_hash = filename
        
        if file_hash not in referenced_hashes:
            try:
                file_size = os.path.getsize(file_path)
                
                if dry_run:
                    print(f"Would delete: {filename} ({file_size} bytes)")
                else:
                    os.remove(file_path)
                    print(f"Deleted: {filename}")
                
                orphaned_count += 1
                reclaimed_bytes += file_size
                
            except OSError as e:
                print(f"Error processing {filename}: {e}")

    # Summary
    action = "Would reclaim" if dry_run else "Reclaimed"
    print("-" * 40)
    print(f"Total {action}: {orphaned_count} files, {reclaimed_bytes} bytes")
    print("-" * 40)
