# projectclone 🧬  
### Exact, reproducible, full-state project snapshots — including git, caches, env artifacts & symlinks

[![PyPI](https://img.shields.io/pypi/v/projectclone.svg)](https://pypi.org/project/projectclone/)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Build](https://img.shields.io/github/actions/workflow/status/dhruv13x/projectclone/publish.yml)](https://github.com/dhruv13x/projectclone/actions)
[![Downloads](https://img.shields.io/pypi/dm/projectclone.svg)](https://pypi.org/project/projectclone/)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Android%20(Termux)-orange.svg)

---

## 🚀 Overview

`projectclone` creates **exact, faithful, self-contained snapshots** of your project directory, including:

✔ Source code  
✔ `.git` repo & history  
✔ Virtualenvs & caches *(unless excluded)*  
✔ File timestamps, metadata, symlinks  
✔ Configs, logs, local DBs  
✔ Environment-specific state

This enables **true reproducibility** and **safe rollback points** across environments and devices.

### Why this tool?

For developers who need **guaranteed restorable project states**, across:

- Major refactors
- Release checkpoints
- Deployment backups
- Research environments
- Offline disaster recovery
- CI/CD artifact capture
- Termux/mobile development
- Reproducible experiments

> Think:  
> `git commit` + `tar` + `rsync --link-dest` + atomic backup discipline  
> — in one tool.

---

## 🔗 Restore tool

For restoring projectclone backups, use its companion tool:

### 👉 [`projectrestore`](https://github.com/dhruv13x/projectrestore)

| Tool | Responsibility |
|---|---|
`projectclone` | **Create** state snapshots *(non-destructive)*
`projectrestore` | **Apply** snapshots safely *(atomic & secure)*

This design keeps the backup tool safe, focused, and non-destructive — while giving the restore tool full security hardening and atomic restore semantics.

---

## ✨ Features

| Feature | Description |
|---|---|
Full directory clone | Exact deep copy with metadata  
Archive mode | `.tar.gz` with optional SHA-256 manifest  
Incremental mode | Hard-link dedup snapshots (like Time Machine / Borg)  
Atomic safety | Temp staging → atomic move → rollback on fail  
Cross-filesystem safe | Intelligent move vs copy fallback  
Dry-run mode | Preview without modifying anything  
Rotation | Keep only the last N snapshots  
Exclude filters | Glob / substring file exclusion  
Progress UI | Live counters and size reporting  
Termux ready | Works on Android + proot Ubuntu

---

## 📦 Installation

### 🐍 Standard install

```sh
pip install projectclone

📱 Termux / Android

pkg install rsync proot-distro
pip install projectclone


---

🔧 Usage Examples

Basic backup

projectclone backup_1k_tests

Creates:

/sdcard/project_backups/2025-02-03_172501-myproject-backup_1k_tests/


---

Archive mode

projectclone release_v1 --archive

Produces:

release_v1.tar.gz
release_v1.tar.gz.sha256


---

Incremental backup (deduplicated snapshots)

projectclone checkpoint --incremental


---

Exclude files

projectclone nightly --exclude __pycache__ --exclude .mypy_cache


---

Retain last 5 backups

projectclone stable --keep 5


---

Dry-run safety preview

projectclone test --dry-run


---

Full help

projectclone --help


---

🛠 Options Summary

Flag	Meaning

--archive	Create .tar.gz archive
--incremental	Hard-linked incremental mode
--manifest	Size manifest
--manifest-sha	Per-file SHA-256 manifest
--exclude	Exclude patterns
--dest DIR	Custom destination
--dry-run	Preview, no writes
--symlinks	Preserve symlinks
--keep N	Keep only last N backups
--yes	Auto-confirm operations
--verbose	Debug logging



---

🔐 Safety Guarantees

Atomic staging → atomic final move

Secure cleanup on failure

Cross-device move fallback

Drops setuid/setgid bits

Tight log permissions (chmod 600 where supported)

Non-destructive: never overwrites directories



---

📁 Default Paths

Platform	Location

Linux	~/project_backups
Termux	/sdcard/project_backups



---

🧪 Development

pip install -e .[dev]
pytest -v


---

📜 License

MIT — open source & production-friendly.


---

🤝 Contributing

Ideas & PRs welcome — especially around:

Compression tuning (zstd / lz4)

Remote sync (SSH / S3 / GDrive)

Fuse mounts / stream extraction

Config file support



---

⭐ Support

If this tool protects your work, please ⭐️ the repo — your support drives development.

git clone https://github.com/dhruv13x/projectclone


---

🧠 Author

Dhruv
Mobile-first DevOps explorer | Rust & Python | Cloud | Termux power-user


---

🧩 Roadmap

.projectcloneignore

zstd / lz4 compression

Remote targets (SSH / S3 / GDrive)

Encrypted archives

GUI wrapper (Android & Desktop)


> Restore is intentionally delegated to
projectrestore → secure, atomic, rollback-safe recovery




---

💬 Final Word

> Code evolves — backups must keep up.
Restore safely — with tools designed for it.



With projectclone, every project state becomes portable, reproducible, and future-proof.

Clone. Freeze. Protect. Restore via projectrestore.


---
