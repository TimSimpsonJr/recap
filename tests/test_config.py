"""Tests for daemon config loading (recap.daemon.config)."""
import pathlib

import pytest
import yaml

from recap.daemon.config import load_daemon_config


class TestDaemonConfig:
    def test_load_minimal_config(self, tmp_path: pathlib.Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path / "vault"),
            "recordings-path": str(tmp_path / "recordings"),
            "user-name": "Tim",
        }))
        config = load_daemon_config(config_file)
        assert config.vault_path == tmp_path / "vault"
        assert config.user_name == "Tim"

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_daemon_config(pathlib.Path("/nonexistent/config.yaml"))

    def test_missing_vault_path_raises(self, tmp_path: pathlib.Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "recordings-path": str(tmp_path / "recordings"),
        }))
        with pytest.raises(ValueError, match="vault-path"):
            load_daemon_config(config_file)

    def test_wrong_version_raises(self, tmp_path: pathlib.Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 99,
            "vault-path": str(tmp_path / "vault"),
            "recordings-path": str(tmp_path / "recordings"),
        }))
        with pytest.raises(ValueError, match="config-version"):
            load_daemon_config(config_file)

    def test_orgs_parsed(self, tmp_path: pathlib.Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path / "vault"),
            "recordings-path": str(tmp_path / "recordings"),
            "orgs": {
                "work": {"subfolder": "Work", "default": True},
                "personal": {"subfolder": "Personal"},
            },
        }))
        config = load_daemon_config(config_file)
        assert len(config.orgs) == 2
        assert config.default_org.name == "work"
        assert config.default_org.subfolder == "Work"
