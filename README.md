# projectclone 🧬  
### Exact, reproducible, full-state project snapshots — with git, caches, env artifacts & symlinks

[![PyPI](https://img.shields.io/pypi/v/projectclone.svg)](https://pypi.org/project/projectclone/)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Build](https://img.shields.io/github/actions/workflow/status/dhruv13x/projectclone/publish.yml)](https://github.com/dhruv13x/projectclone/actions)
[![Downloads](https://img.shields.io/pypi/dm/projectclone.svg)](https://pypi.org/project/projectclone/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Android%20(Termux)-orange.svg)]()

---

## 🚀 Overview

`projectclone` creates **exact, faithful, self-contained copies** of your project workspace —  
including:

✔ Source code  
✔ `.git` repo & history  
✔ Virtualenvs & caches (unless excluded)  
✔ Symlinks, metadata, file times  
✔ Logs, config, db files, secrets *(your machine-level security applies)*

### Why this tool?

For developers who need **guaranteed reproducible project states**, across:

- major refactors
- release checkpoints
- deployment backups
- research experiments
- CI/CD artifact preservation
- Termux / mobile dev environments
- Secure environment rollbacks
- Code forensics / disaster recovery

> Think of it as:  
> **`git commit` + `rsync --link-dest` + `tar` + secure state freezer**  
> in one reliable command.

---

## ✨ Key Features

| Feature | Description |
|---|---|
Full directory clone | Copies every file (or hard-linked incremental mode)  
Archive mode | `.tar.gz` compressed snapshot with optional SHA256 manifest  
Incremental mode | `rsync --link-dest` deduplication like Time Machine / Borg  
Safety-first design | Atomic ops, temp dirs, cleanup on failure, UID bit stripping  
Manifest options | Size manifest + per-file SHA256 manifest for integrity  
Cross-device aware | Safely moves temp artifacts across filesystems  
Smart excludes | Glob/substring excludes (optional)  
Dry-run mode | Estimate + preview changes  
Rotation | Keep N most recent backups  
Progress indicators | Real-time file copy count + sizes  
Termux optimized | Works seamlessly in Termux + proot Ubuntu  

---

## 📦 Installation

### Standard install

```sh
pip install projectclone

Termux / Android

pkg install rsync proot-distro
pip install projectclone


---

🔧 Usage

Basic backup to default location

projectclone backup_1k_tests

Creates:

/sdcard/project_backups/2025-02-03_172501-myproject-backup_1k_tests/


---

Archive backup (compressed)

projectclone release_v1 --archive

Outputs:

release_v1.tar.gz
release_v1.tar.gz.sha256


---

Incremental (fast snapshots, dedup)

projectclone checkpoint --incremental


---

Show what will happen (safe preview)

projectclone rc --dry-run


---

Excluding files

projectclone nightly --exclude __pycache__ --exclude .mypy_cache


---

Keep last 5 clones (rotation)

projectclone stable --keep 5


---

Full help

projectclone --help


---

🛠 Options

Flag	Meaning

--archive	Create .tar.gz snapshot
--incremental	Rsync incremental mode with hardlinks
--manifest	Create size manifest
--manifest-sha	Per-file SHA256 manifest (slow)
--exclude PATTERN	Exclude matching paths
--dest DIR	Override destination directory
--dry-run	No writes — preview only
--symlinks	Preserve symbolic links
--yes	Skip confirmation prompt
--keep N	Keep only N recent snapshots
--verbose	Verbose logs
--progress-interval N	Print progress every N files



---

🔐 Safety & Guarantees

Atomic writes (temp → atomic move)

Auto-cleanup temp dirs on interrupt

Cross-filesystem safe move logic

Clears setuid/setgid bits for security

Write-protected log file (chmod 600 when supported)



---

📁 Default Backup Location

Platform	Path

Linux	~/project_backups (or provided)
Termux	/sdcard/project_backups



---

🧪 Testing

pip install -e .[dev]
pytest -v


---

📜 License

MIT — free for personal & commercial use.


---

🤝 Contributing

PRs welcome — especially for:

Restore module

Remote sync targets (S3, GDrive, SSH)

Fuse mounts / streaming restore

Compression tuning (lz4, zstd)

pydantic backed config file



---

⭐ Support / Motivation

Star the repo to support development 🙏
Every ⭐ helps justify more time invested.

git clone https://github.com/dhruv13x/projectclone


---

🧠 Author

Dhruv
Mobile-first DevOps explorer | Rust & Python | Cloud | Termux power-user


---

🧩 Roadmap

projectclone restore

zstd / lz4 compression modes

remote backup: s3 / ssh / gdrive

.projectcloneignore support

encrypted archives

GUI wrapper (Android / desktop)



---

💬 Final Word

> Code evolves — backups must keep up.



With projectclone, every project state becomes reproducible forever.

Freeze. Trust. Restore. Repeat.

---