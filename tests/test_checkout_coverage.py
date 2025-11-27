# projectclone/tests/test_checkout_coverage.py


import os
import sys
import pytest
from unittest.mock import MagicMock, patch, mock_open
from projectclone import checkout_engine

class TestCheckoutCoverage:

    @pytest.fixture
    def setup_env(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "snapshots").mkdir()
        (vault / "objects").mkdir()
        return src, vault

    def test_checkout_outside_root(self, setup_env, capsys):
        src, vault = setup_env
        target = src.parent / "outside.txt"

        checkout_engine.checkout_file(str(src), str(vault), str(target))
        captured = capsys.readouterr()
        # "is not inside the project root"
        assert "not" in captured.out and "inside the project root" in captured.out

    def test_checkout_no_snapshots(self, setup_env, capsys):
        src, vault = setup_env
        target = src / "f1.txt"

        checkout_engine.checkout_file(str(src), str(vault), str(target))
        captured = capsys.readouterr()
        assert "No snapshots found" in captured.out

    def test_checkout_missing_manifest(self, setup_env, capsys):
        src, vault = setup_env
        target = src / "f1.txt"

        (vault / "snapshots" / "src").mkdir(parents=True)
        (vault / "snapshots" / "src" / "s.json").write_text("{broken")

        checkout_engine.checkout_file(str(src), str(vault), str(target))
        captured = capsys.readouterr()
        assert "Error loading manifest" in captured.out

    def test_checkout_file_not_in_manifest(self, setup_env, capsys):
        src, vault = setup_env
        target = src / "f1.txt"

        (vault / "snapshots" / "src").mkdir(parents=True)
        (vault / "snapshots" / "src" / "s.json").write_text('{"files": {}}')

        checkout_engine.checkout_file(str(src), str(vault), str(target))
        captured = capsys.readouterr()
        assert "was not found in the latest snapshot" in captured.out

    def test_checkout_object_missing(self, setup_env, capsys):
        src, vault = setup_env
        target = src / "f1.txt"

        (vault / "snapshots" / "src").mkdir(parents=True)
        (vault / "snapshots" / "src" / "s.json").write_text('{"files": {"f1.txt": "hash1"}}')

        checkout_engine.checkout_file(str(src), str(vault), str(target))
        captured = capsys.readouterr()
        assert "is missing from the vault" in captured.out

    def test_checkout_overwrite_abort(self, setup_env, capsys):
        src, vault = setup_env
        target = src / "f1.txt"
        target.write_text("local")

        (vault / "snapshots" / "src").mkdir(parents=True)
        (vault / "snapshots" / "src" / "s.json").write_text('{"files": {"f1.txt": "hash1"}}')
        (vault / "objects" / "hash1").write_text("remote")

        with patch("builtins.input", return_value="n"):
            checkout_engine.checkout_file(str(src), str(vault), str(target))

        captured = capsys.readouterr()
        assert "Aborted" in captured.out
        assert target.read_text() == "local"

    def test_checkout_metadata_application(self, setup_env, capsys):
        src, vault = setup_env
        target = src / "f1.txt"

        (vault / "snapshots" / "src").mkdir(parents=True)
        (vault / "snapshots" / "src" / "s.json").write_text('{"files": {"f1.txt": {"hash": "hash1", "mode": 511}}}') # 0o777 = 511
        (vault / "objects" / "hash1").write_text("remote")

        checkout_engine.checkout_file(str(src), str(vault), str(target))

        captured = capsys.readouterr()
        assert "Restored 'f1.txt'" in captured.out
        import stat
        assert stat.S_IMODE(target.stat().st_mode) == 0o777
