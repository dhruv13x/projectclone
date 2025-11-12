from projectclone.cleanup import (
    CleanupState,
    cleanup_state,
)


class TestCleanupState:
    def test_cleanup_state(self, tmp_path):
        state = CleanupState()
        tmp_d = tmp_path / "tmpd"
        tmp_d.mkdir()
        state.register_tmp_dir(tmp_d)
        tmp_f = tmp_path / "tmpf"
        tmp_f.touch()
        state.register_tmp_file(tmp_f)
        # Cleanup removes
        state.cleanup()
        assert not tmp_d.exists()
        assert not tmp_f.exists()
        # Unregister prevents removal
        tmp_d.mkdir()
        state.register_tmp_dir(tmp_d)
        state.unregister_tmp_dir(tmp_d)
        state.cleanup()
        assert tmp_d.exists()

    def test_cleanup_state_integration(self, tmp_path):
        f = tmp_path / "tempfile.tmp"
        d = tmp_path / "tempdir"
        f.write_text("x")
        d.mkdir()
        (d / "inside.txt").write_text("ok")
        cleanup_state.register_tmp_file(f)
        cleanup_state.register_tmp_dir(d)
        cleanup_state.cleanup(verbose=False)
        assert not f.exists()
        assert not d.exists()
