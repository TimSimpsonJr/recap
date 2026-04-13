"""Tests for auto-start stub."""

from recap.daemon.autostart import install_autostart, remove_autostart, is_autostart_enabled
import pathlib


class TestAutoStartStub:
    def test_is_not_enabled(self):
        assert is_autostart_enabled() is False

    def test_install_returns_false(self, tmp_path):
        result = install_autostart(
            daemon_exe_path=tmp_path / "recap-daemon.exe",
            config_path=tmp_path / "config.yaml",
        )
        assert result is False

    def test_remove_returns_false(self):
        assert remove_autostart() is False
