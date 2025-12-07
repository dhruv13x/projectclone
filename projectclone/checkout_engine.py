# projectclone/projectclone/checkout_engine.py

import os
import sys
import shutil
from rich.console import Console

# Import common modules
try:
    from src.common import manifest, cas
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
    from src.common import manifest

def _get_latest_snapshot(vault_path: str, project_name: str):
    """Finds the path to the latest snapshot manifest for a project."""
    snapshots_dir = os.path.join(vault_path, "snapshots", project_name)
    if not os.path.exists(snapshots_dir):
        return None

    files = sorted(
        [f for f in os.listdir(snapshots_dir) if f.endswith(".json")],
        reverse=True
    )
    if not files:
        return None
    return os.path.join(snapshots_dir, files[0])

def checkout_file(source_root: str, vault_path: str, target_file: str, force: bool = False):
    """
    Restores a specific file from the latest snapshot, overwriting the local copy.
    """
    console = Console()
    abs_source = os.path.abspath(source_root)
    abs_target = os.path.abspath(target_file)
    
    if not abs_target.startswith(abs_source):
        console.print(f"[red]Error:[/red] File '{target_file}' is not inside the project root '{source_root}'.")
        return

    rel_path = os.path.relpath(abs_target, abs_source)
    
    project_name = os.path.basename(abs_source)
    import re
    project_name = re.sub(r'[^a-zA-Z0-9_-]', '_', project_name)

    latest_manifest_path = _get_latest_snapshot(vault_path, project_name)
    if not latest_manifest_path:
        console.print(f"[yellow]No snapshots found for project '{project_name}'. Cannot checkout.[/yellow]")
        return

    try:
        data = manifest.load_manifest(latest_manifest_path)
        manifest_files = data.get("files", {})
    except Exception as e:
        console.print(f"[red]Error loading manifest:[/red] {e}")
        return

    if rel_path not in manifest_files:
        console.print(f"[yellow]File '{rel_path}' was not found in the latest snapshot.[/yellow]")
        return

    # Handle V1 vs V2
    entry = manifest_files[rel_path]
    if isinstance(entry, str):
        file_hash = entry
        metadata = None
    else:
        file_hash = entry.get("hash")
        metadata = entry

    object_path = os.path.join(vault_path, "objects", file_hash)

    if not os.path.exists(object_path):
        console.print(f"[red]Error:[/red] Object for '{rel_path}' (hash: {file_hash}) is missing from the vault.")
        return

    if os.path.exists(abs_target) and not force:
        console.print(f"[bold red]Warning:[/bold red] This will overwrite local changes to '{rel_path}'.")
        ans = input("Are you sure? [y/N] ").strip().lower()
        if ans not in ('y', 'yes'):
            console.print("Aborted.")
            return

    try:
        # Use cas helper to handle compression/decompression
        cas.restore_object_to_file(object_path, abs_target)
        
        # Apply Metadata
        if metadata:
            try:
                if "mode" in metadata:
                    os.chmod(abs_target, metadata["mode"])
                if "mtime" in metadata:
                    mtime = metadata["mtime"]
                    os.utime(abs_target, (mtime, mtime))
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to apply metadata:[/yellow] {e}")

        console.print(f"[green]Restored '{rel_path}' from snapshot {data.get('timestamp')}[/green]")
    except Exception as e:
        console.print(f"[red]Error restoring file:[/red] {e}")
