# projectclone/projectclone/diff_engine.py

import os
import sys
import difflib
from rich.console import Console
from rich.syntax import Syntax

# Import common modules
try:
    from src.common import manifest, cas
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
    from src.common import manifest, cas

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

def show_diff(source_path: str, vault_path: str, target_file: str):
    """
    Compares a specific file in the workspace with its version in the latest snapshot.
    """
    console = Console()
    abs_source = os.path.abspath(source_path)
    abs_target = os.path.abspath(target_file)
    
    # 1. Validate Target
    if not abs_target.startswith(abs_source):
        console.print(f"[red]Error:[/red] File '{target_file}' is not inside the source project '{source_path}'.")
        return

    rel_path = os.path.relpath(abs_target, abs_source)
    project_name = os.path.basename(abs_source)
    # Sanitize project name (same logic as cas_engine/status_engine)
    import re
    project_name = re.sub(r'[^a-zA-Z0-9_-]', '_', project_name)

    # 2. Find Latest Snapshot
    latest_manifest_path = _get_latest_snapshot(vault_path, project_name)
    if not latest_manifest_path:
        console.print(f"[yellow]No snapshots found for project '{project_name}'. cannot diff.[/yellow]")
        return

    # 3. Load Manifest
    try:
        data = manifest.load_manifest(latest_manifest_path)
        manifest_files = data.get("files", {})
    except Exception as e:
        console.print(f"[red]Error loading manifest:[/red] {e}")
        return

    # 4. Get File Hash
    if rel_path not in manifest_files:
        console.print(f"[yellow]File '{rel_path}' is new (not in latest snapshot).[/yellow]")
        return

    file_hash = manifest_files[rel_path]
    object_path = os.path.join(vault_path, "objects", file_hash)

    if not os.path.exists(object_path):
        console.print(f"[red]Error:[/red] Object for '{rel_path}' (hash: {file_hash}) missing in vault.")
        return

    # 5. Perform Diff
    try:
        old_lines = cas.read_object_text(object_path)
        
        with open(abs_target, "r", encoding="utf-8", errors="replace") as f:
            new_lines = f.readlines()
            
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"{rel_path} (Snapshot {data.get('timestamp')})",
            tofile=f"{rel_path} (Current)",
            lineterm=""
        )
        
        diff_text = "".join(diff)
        
        if not diff_text:
            console.print(f"[green]File '{rel_path}' matches the snapshot.[/green]")
        else:
            syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=True)
            console.print(syntax)

    except Exception as e:
        console.print(f"[red]Error performing diff:[/red] {e}")
