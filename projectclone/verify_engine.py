import os
import filecmp
from collections import namedtuple

# Define result structure
VerificationResult = namedtuple("VerificationResult", ["success", "errors"])

def verify_directories(original_path, clone_path):
    """
    Recursively compares two directories.
    Returns VerificationResult(success, errors).
    """
    errors = []

    # Normalize paths
    original_path = os.path.abspath(original_path)
    clone_path = os.path.abspath(clone_path)

    # 1. Walk original to find missing files or content mismatches in clone
    for root, dirs, files in os.walk(original_path):
        rel_path = os.path.relpath(root, original_path)
        clone_root = os.path.join(clone_path, rel_path)

        if not os.path.exists(clone_root):
            errors.append(f"Missing directory: {rel_path}")
            # Skip subdirectories if parent is missing
            dirs[:] = []
            continue

        for file in files:
            orig_file = os.path.join(root, file)
            clone_file = os.path.join(clone_root, file)
            rel_file_path = os.path.join(rel_path, file)

            if not os.path.exists(clone_file):
                errors.append(f"Missing file: {rel_file_path}")
                continue

            # Compare content
            if not filecmp.cmp(orig_file, clone_file, shallow=False):
                errors.append(f"Content mismatch: {rel_file_path}")

    # 2. Walk clone to find extra files
    for root, dirs, files in os.walk(clone_path):
        rel_path = os.path.relpath(root, clone_path)
        orig_root = os.path.join(original_path, rel_path)

        if not os.path.exists(orig_root):
            errors.append(f"Extra directory: {rel_path}")
            # Don't recurse into extra dirs to avoid spamming errors
            dirs[:] = []
            continue

        for file in files:
            clone_file = os.path.join(root, file)
            orig_file = os.path.join(orig_root, file)
            rel_file_path = os.path.join(rel_path, file)

            if not os.path.exists(orig_file):
                errors.append(f"Extra file: {rel_file_path}")

    return VerificationResult(success=len(errors) == 0, errors=errors)

# Alias for compatibility if needed
verify_clone = verify_directories
