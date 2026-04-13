"""Tests for daemon startup validation."""
from unittest.mock import patch
from recap.daemon.startup import validate_startup, StartupCheck, StartupResult


class TestStartupValidation:
    def test_vault_path_exists(self, tmp_path):
        result = validate_startup(vault_path=tmp_path, check_gpu=False)
        vault_check = next(c for c in result.checks if c.name == "vault_path")
        assert vault_check.passed is True

    def test_vault_path_missing(self, tmp_path):
        result = validate_startup(vault_path=tmp_path / "nonexistent", check_gpu=False)
        vault_check = next(c for c in result.checks if c.name == "vault_path")
        assert vault_check.passed is False
        assert "not found" in vault_check.message.lower()

    def test_vault_path_missing_is_fatal(self, tmp_path):
        result = validate_startup(vault_path=tmp_path / "nonexistent", check_gpu=False)
        assert result.can_start is False

    def test_gpu_missing_is_non_fatal(self, tmp_path):
        with patch("recap.daemon.startup._check_cuda", return_value=False):
            result = validate_startup(vault_path=tmp_path, check_gpu=True)
        gpu_check = next(c for c in result.checks if c.name == "gpu")
        assert gpu_check.passed is False
        assert result.can_start is True

    def test_result_contains_all_checks(self, tmp_path):
        with patch("recap.daemon.startup._check_cuda", return_value=True):
            with patch("recap.daemon.startup._check_audio_devices", return_value=True):
                with patch("recap.daemon.startup._check_keyring", return_value=True):
                    result = validate_startup(vault_path=tmp_path, check_gpu=True)
        check_names = {c.name for c in result.checks}
        assert "vault_path" in check_names
        assert "gpu" in check_names
        assert "audio_devices" in check_names
        assert "keyring" in check_names

    def test_warnings_returns_non_fatal_failures(self, tmp_path):
        with patch("recap.daemon.startup._check_cuda", return_value=False):
            with patch("recap.daemon.startup._check_audio_devices", return_value=True):
                with patch("recap.daemon.startup._check_keyring", return_value=True):
                    result = validate_startup(vault_path=tmp_path, check_gpu=True)
        assert len(result.warnings) == 1
        assert result.warnings[0].name == "gpu"
