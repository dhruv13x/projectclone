# projectclone/projectclone/sync_engine.py

import os
from src.common import b2, s3


def _get_storage_manager(bucket_name: str, endpoint: str, key_id: str, app_key: str):
    """
    Factory to return the appropriate storage manager (S3 or B2).
    """
    # Logic: If an endpoint is provided OR we have AWS credentials in env, prefer S3.
    # Otherwise, default to B2 Native.
    if endpoint or os.environ.get("AWS_ACCESS_KEY_ID"):
        return s3.S3Manager(key_id, app_key, bucket_name, endpoint)
    else:
        return b2.B2Manager(key_id, app_key, bucket_name)


def sync_to_cloud(vault_path: str, bucket_name: str, endpoint: str, key_id: str, app_key: str, dry_run: bool = False):
    """
    Syncs the local vault content (objects and snapshots) to a Cloud Bucket (S3 or B2).
    
    Args:
        vault_path: Path to the local vault directory.
        bucket_name: Name of the target bucket.
        endpoint: S3 Endpoint URL (optional).
        key_id: Access Key ID.
        app_key: Secret Access Key.
        dry_run: If True, simulate the upload.
    """
    print(f"Connecting to cloud bucket: {bucket_name}...")
    manager = _get_storage_manager(bucket_name, endpoint, key_id, app_key)
    
    print("Fetching file list from cloud...")
    remote_files = manager.list_file_names()
    print(f"Found {len(remote_files)} existing files in cloud.")
    
    items_to_push = 0

    # --- Phase 1: Sync Objects ---
    local_objects_dir = os.path.join(vault_path, "objects")
    if os.path.exists(local_objects_dir):
        for root, _, files in os.walk(local_objects_dir):
            for file in files:
                local_path = os.path.join(root, file)
                # Remote key structure: objects/<hash>
                remote_key = f"objects/{file}"
                
                if remote_key in remote_files:
                    if not dry_run:
                        print(f"Skipping object: {file} (Exists)")
                else:
                    if dry_run:
                        print(f"[Dry Run] Would push object: {file}")
                    else:
                        # Uploading happens inside manager.upload_file which prints progress
                        manager.upload_file(local_path, remote_key)
                    items_to_push += 1
    else:
        print(f"No objects directory found at {local_objects_dir}")

    # --- Phase 2: Sync Snapshots ---
    local_snapshots_dir = os.path.join(vault_path, "snapshots")
    if os.path.exists(local_snapshots_dir):
        for root, _, files in os.walk(local_snapshots_dir):
            for file in files:
                if not file.endswith(".json"):
                    continue
                
                local_path = os.path.join(root, file)
                
                # Calculate relative path to preserve directory structure
                # e.g., /vault/snapshots/project_A/snap.json -> project_A/snap.json
                rel_path = os.path.relpath(local_path, local_snapshots_dir)
                
                # Remote key: snapshots/project_A/snap.json
                # We use forward slashes for cloud keys
                remote_key = f"snapshots/{rel_path}".replace(os.sep, "/")
                
                if remote_key in remote_files:
                    if not dry_run:
                        print(f"Skipping snapshot: {rel_path} (Exists)")
                else:
                    if dry_run:
                        print(f"[Dry Run] Would push snapshot: {rel_path}")
                    else:
                        manager.upload_file(local_path, remote_key)
                    items_to_push += 1
    else:
        print(f"No snapshots directory found at {local_snapshots_dir}")

    if dry_run:
        print(f"Dry run complete. {items_to_push} items would be pushed.")
    else:
        print(f"Cloud sync complete. {items_to_push} items pushed.")


def sync_from_cloud(vault_path: str, bucket_name: str, endpoint: str, key_id: str, app_key: str, dry_run: bool = False):
    """
    Syncs the local vault content (objects and snapshots) FROM a Cloud Bucket.
    Downloads any objects or snapshots that are missing locally.
    
    Args:
        vault_path: Path to the local vault directory.
        bucket_name: Name of the source bucket.
        endpoint: S3 Endpoint URL (optional).
        key_id: Access Key ID.
        app_key: Secret Access Key.
        dry_run: If True, simulate the download.
    """
    print(f"Connecting to cloud bucket: {bucket_name}...")
    manager = _get_storage_manager(bucket_name, endpoint, key_id, app_key)
    
    print("Fetching file list from cloud...")
    remote_files = manager.list_file_names()
    print(f"Found {len(remote_files)} files in cloud.")

    items_to_pull = 0

    # --- Phase 1: Sync Objects (Cloud -> Local) ---
    print("Scanning for objects to pull...")
    for remote_file in remote_files:
        if remote_file.startswith("objects/"):
            # Extract filename (hash) from remote path "objects/hash"
            filename = os.path.basename(remote_file)
            local_path = os.path.join(vault_path, "objects", filename)
            
            if os.path.exists(local_path):
                if not dry_run:
                    print(f"Skipping object: {filename} (Exists)")
            else:
                if dry_run:
                    print(f"[Dry Run] Would pull object: {filename}")
                else:
                    manager.download_file(remote_file, local_path)
                items_to_pull += 1
        
        # --- Phase 2: Sync Snapshots (Cloud -> Local) ---
        elif remote_file.startswith("snapshots/") and remote_file.endswith(".json"):
            # remote_file is like "snapshots/project_A/snap.json"
            # We map this to vault_path/snapshots/project_A/snap.json
            
            # Remove the "snapshots/" prefix for clean joining (safe way)
            # split('/', 1)[1] gives "project_A/snap.json"
            rel_path = remote_file.split('/', 1)[1]
            
            local_path = os.path.join(vault_path, "snapshots", rel_path)
            
            if os.path.exists(local_path):
                if not dry_run:
                    print(f"Skipping snapshot: {rel_path} (Exists)")
            else:
                if dry_run:
                    print(f"[Dry Run] Would pull snapshot: {rel_path}")
                else:
                    manager.download_file(remote_file, local_path)
                items_to_pull += 1
    
    if dry_run:
        print(f"Dry run complete. {items_to_pull} items would be pulled.")
    else:
        print(f"Cloud download complete. {items_to_pull} items pulled.")
