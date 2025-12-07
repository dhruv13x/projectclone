# projectclone/tests/test_ignore.py

import pytest
from pathlib import Path
from src.common.ignore import PathSpec

class TestPathSpec:
    def test_basic_match(self):
        spec = PathSpec.from_lines([
            "*.log",
            "temp/",
            "secret.txt"
        ])

        assert spec.match_file("app.log") is True
        assert spec.match_file("logs/app.log") is True

        # 'temp/' only matches if it is a directory
        assert spec.match_file("temp", is_dir=True) is True
        assert spec.match_file("temp", is_dir=False) is False

        assert spec.match_file("src/temp", is_dir=True) is True  # Should match directory anywhere
        assert spec.match_file("secret.txt") is True
        assert spec.match_file("src/secret.txt") is True

        assert spec.match_file("app.txt") is False
        assert spec.match_file("temparary") is False

    def test_comments_and_empty_lines(self):
        spec = PathSpec.from_lines([
            "# This is a comment",
            "",
            "   # Indented comment",
            "file.txt"
        ])
        assert spec.match_file("file.txt") is True
        assert spec.match_file("# This is a comment") is False

    def test_anchored_match(self):
        spec = PathSpec.from_lines([
            "/root_only.txt",
            "/build/"
        ])
        assert spec.match_file("root_only.txt") is True
        assert spec.match_file("subdir/root_only.txt") is False

        assert spec.match_file("build", is_dir=True) is True
        assert spec.match_file("subdir/build", is_dir=True) is False

    def test_negation(self):
        spec = PathSpec.from_lines([
            "*.log",
            "!important.log",
            "!logs/keep.log"
        ])
        assert spec.match_file("error.log") is True

        # !important.log un-ignores important.log
        assert spec.match_file("important.log") is False

        # !important.log matches basename, so un-ignores logs/important.log too
        assert spec.match_file("logs/important.log") is False

        # !logs/keep.log un-ignores logs/keep.log
        assert spec.match_file("logs/keep.log") is False

        assert spec.match_file("logs/other.log") is True

    def test_nested_wildcards(self):
        spec = PathSpec.from_lines([
            "foo/**/bar"
        ])
        assert spec.match_file("foo/bar") is True
        assert spec.match_file("foo/baz/bar") is True
        assert spec.match_file("foo/a/b/c/bar") is True
        assert spec.match_file("bar") is False

    def test_directory_only_match(self):
        spec = PathSpec.from_lines(["build/"])

        assert spec.match_file("build", is_dir=True) is True
        assert spec.match_file("build", is_dir=False) is False
        assert spec.match_file("src/build", is_dir=True) is True

    def test_complex_precedence(self):
        spec = PathSpec.from_lines([
            "exclude_all/*",
            "!exclude_all/keep.txt",
            "exclude_all/keep.txt" # re-exclude
        ])
        assert spec.match_file("exclude_all/foo.txt") is True
        assert spec.match_file("exclude_all/keep.txt") is True

        spec2 = PathSpec.from_lines([
            "exclude_all/*",
            "!exclude_all/keep.txt"
        ])
        assert spec2.match_file("exclude_all/keep.txt") is False
