# tests/test_utils.py

import re
from pathlib import Path

import pytest

from projectclone.utils import (
    sanitize_token,
    timestamp,
    human_size,
    sha256_of_file,
    ensure_dir,
    make_unique_path,
)


@pytest.fixture
def temp_dest(tmp_path: Path):
    """Temp dest base dir."""
    dest = tmp_path / "dest"
    dest.mkdir()
    yield dest


class TestHelpers:
    def test_sanitize_token(self):
        assert sanitize_token("valid note") == "valid_note"
        assert sanitize_token("invalid: /\\ chars") == "invalid_chars"
        assert sanitize_token("") == "note"
        assert sanitize_token("  multiple__underscores  ") == "multiple_underscores"

    def test_timestamp(self):
        ts = timestamp()
        assert re.match(r"\d{4}-\d{2}-\d{2}_\d{6}", ts)

    def test_human_size(self):
        assert human_size(0) == "0.0B"
        assert human_size(1023) == "1023.0B"
        assert human_size(1024) == "1.0KB"
        assert human_size(1024**3 - 1) == "1024.0MB"  # Correct rounding
        assert human_size(1024**4) == "1.0TB"  # 1 TiB

    def test_sha256_of_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("test content")
        expected = "6ae8a75555209fd6c44157c0aed8016e763ff435a19cf186f76863140143ff72"
        assert sha256_of_file(f) == expected

    def test_ensure_dir(self, tmp_path):
        p = tmp_path / "nested" / "dir"
        ensure_dir(p)
        assert p.exists()
        assert p.is_dir()

    def test_make_unique_path(self, temp_dest):
        base = temp_dest / "existing"
        base.mkdir()
        unique = make_unique_path(base)
        assert unique.name == "existing-1"
        assert not unique.exists()  # Not created, just named

    def test_make_unique_path_incrementing(self, tmp_path):
        base = tmp_path / "same"
        base.mkdir()
        (tmp_path / "same-1").mkdir()
        (tmp_path / "same-2").mkdir()
        new = make_unique_path(tmp_path / "same")
        assert new.name == "same-3"
