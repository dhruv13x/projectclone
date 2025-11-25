<div align="center">
  <img src="https://raw.githubusercontent.com/dhruv13x/projectclone/main/projectclone_logo.png" alt="projectclone logo" width="200"/>
</div>

<div align="center">

[![PyPI version](https://img.shields.io/pypi/v/projectclone.svg)](https://pypi.org/project/projectclone/)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Build status](https://github.com/dhruv13x/projectclone/actions/workflows/publish.yml/badge.svg)](https://github.com/dhruv13x/projectclone/actions/workflows/publish.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

# 🧬 projectclone
**Exact, reproducible, full-state project snapshots — including git, caches, env artifacts & symlinks.**

## About
`projectclone` creates exact, faithful, self-contained snapshots of your project directory. This enables true reproducibility and safe rollback points across environments and devices. It's for developers who need guaranteed restorable project states.

### The `projectclone` Ecosystem
`projectclone` is part of a two-tool ecosystem for safe, reliable backups.

| Tool | Responsibility |
|---|---|
| `projectclone` | **Create** state snapshots *(non-destructive)* |
| [`projectrestore`](https://github.com/dhruv13x/projectrestore) | **Apply** snapshots safely *(atomic & secure)* |

This design keeps the backup tool focused and non-destructive, while the restore tool handles the complexities of atomic and secure restoration.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- `rsync` (for incremental backups)

### Installation
```bash
pip install projectclone
```

### Usage Example
```bash
# Create a backup with a note
projectclone my_first_backup

# Create a compressed archive
projectclone release_v1 --archive

# Create an incremental backup
projectclone nightly --incremental
```
> **To restore a backup, use the [`projectrestore`](https://github.com/dhruv13x/projectrestore) tool.**

---

## ✨ Key Features
- **Full directory clone**: Exact deep copy with metadata.
- **Archive mode**: Creates a `.tar.gz` with an optional SHA-256 manifest.
- **Incremental mode**: Hard-link deduplicated snapshots (like Time Machine).
- **Atomic safety**: Uses a temporary staging directory for safe, atomic operations.
- **Dry-run mode**: Preview the backup process without modifying anything.
- **Rotation**: Automatically keeps the last N snapshots.
- **Exclude filters**: Exclude files and directories using glob patterns.

---

## ⚙️ Configuration & Advanced Usage

### CLI Arguments
| Flag | Shorthand | Description | Default |
|---|---|---|---|
| `--dest` | | Base destination folder | `/sdcard/project_backups` |
| `--archive` | `-a` | Create a compressed `.tar.gz` archive | `False` |
| `--manifest` | | Write a `MANIFEST.txt` with file sizes | `False` |
| `--manifest-sha` | | Compute per-file SHA256 checksums | `False` |
| `--symlinks` | | Preserve symlinks instead of copying their targets | `False` |
| `--keep` | | Number of recent backups to keep | `0` (keep all) |
| `--yes` | | Skip confirmation prompts | `False` |
| `--progress-interval`| | Print progress every N files | `50` |
| `--exclude` | | Exclude files/dirs (can be used multiple times) | `[]` |
| `--dry-run` | | Preview actions without writing to disk | `False` |
| `--incremental` | | Use `rsync` for incremental backups | `False` |
| `--verbose` | | Enable verbose logging | `False` |
| `--version` | | Show the program's version and exit | |

---

## 🔐 Safety Guarantees
- **Atomic Operations**: Backups are staged in a temporary directory and moved to their final destination atomically, preventing partial or corrupt backups.
- **Secure Cleanup**: Temporary files and directories are securely cleaned up on successful completion or failure.
- **Cross-Device Safety**: The tool intelligently falls back to a safe copy-and-delete operation when moving files across different filesystems.
- **Permission Handling**: The tool drops `setuid`/`setgid` bits and sets restrictive permissions on log files.
- **Non-Destructive**: `projectclone` never overwrites existing directories, ensuring your data is safe.

---

## 🏗️ Architecture
```
src/projectclone/
├── __init__.py
├── backup.py       # Core backup logic
├── banner.py       # ASCII art
├── cleanup.py      # Temporary file cleanup
├── cli.py          # Command-line interface
├── rotation.py     # Backup rotation logic
├── scanner.py      # File scanning and stats
└── utils.py        # Utility functions
```

The tool works by scanning the project directory, creating a temporary staging directory, and then either copying the files, creating an archive, or running `rsync` for an incremental backup. Once complete, the backup is moved to its final destination atomically.

---

## 🗺️ Roadmap
- `.projectcloneignore` file for exclusions
- Support for `zstd` / `lz4` compression
- Remote targets (SSH, S3, GDrive)
- Encrypted archives

---

## 🤝 Contributing & License
Contributions are welcome! Please open an issue or submit a pull request. This project is licensed under the MIT License.
