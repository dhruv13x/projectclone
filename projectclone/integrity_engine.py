# projectclone/projectclone/integrity_engine.py

import os
from src.common import cas


def verify_vault(vault_path: str) -> bool:
    """
    Verifies the integrity of the vault by checking if the stored object's content
    matches its filename (which should be its SHA256 hash).

    Args:
        vault_path: The root path of the vault.

    Returns:
        True if the vault is healthy (0 corruptions), False otherwise.
    """
    objects_dir = os.path.join(vault_path, "objects")
    
    if not os.path.exists(objects_dir):
        print(f"Error: Objects directory not found at {objects_dir}")
        return False

    print(f"Verifying vault integrity at: {objects_dir}")

    total_files = 0
    corrupted_files = 0
    
    for root, _, files in os.walk(objects_dir):
        for i, filename in enumerate(files):
            total_files += 1
            file_path = os.path.join(root, filename)
            
            try:
                # The filename is expected to be the hash
                expected_hash = filename
                actual_hash = cas.calculate_hash(file_path)
                
                if expected_hash == actual_hash:
                    # Optional: Print progress every 100 files
                    if i % 100 == 0:
                        print(f"✅ OK: {filename}")
                else:
                    print(f"❌ CORRUPTION DETECTED: {filename}")
                    print(f"   Path: {file_path}")
                    print(f"   Expected: {expected_hash}")
                    print(f"   Actual:   {actual_hash}")
                    corrupted_files += 1
                    
            except Exception as e:
                print(f"❌ ERROR processing {filename}: {e}")
                corrupted_files += 1

    print("-" * 40)
    print(f"Total Files Checked: {total_files}")
    print(f"Total Corrupted Files: {corrupted_files}")
    print("-" * 40)
    
    if corrupted_files == 0:
        print("✨ Vault Integrity Verified: HEALTHY")
        return True
    else:
        print("⚠️ Vault Integrity Verification FAILED: CORRUPTED")
        return False
