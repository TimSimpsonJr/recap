"""Tests for config loading."""
import pathlib
import pytest
import yaml

from recap.config import RecapConfig, load_config


class TestRecapConfig:
    def test_load_full_config(self, tmp_path: pathlib.Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "vault_path": "C:/Users/tim/vault",
            "recordings_path": "C:/Users/tim/recap-data/recordings",
            "frames_path": "C:/Users/tim/recap-data/frames",
            "user_name": "Tim",
            "whisperx": {
                "model": "large-v3",
                "device": "cuda",
                "language": "en",
            },
            "huggingface_token": "hf_test",
            "todoist": {
                "api_token": "test_token",
                "default_project": "Recap",
                "project_map": {"standup": "Sprint Tasks"},
            },
            "claude": {"command": "claude"},
        }))
        config = load_config(config_file)
        assert config.vault_path == pathlib.Path("C:/Users/tim/vault")
        assert config.user_name == "Tim"
        assert config.whisperx.model == "large-v3"
        assert config.todoist.default_project == "Recap"
        assert config.todoist.project_for_type("standup") == "Sprint Tasks"
        assert config.todoist.project_for_type("unknown") == "Recap"

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config(pathlib.Path("/nonexistent/config.yaml"))

    def test_vault_directories(self, tmp_path: pathlib.Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "vault_path": str(tmp_path / "vault"),
            "recordings_path": str(tmp_path / "recordings"),
            "frames_path": str(tmp_path / "frames"),
            "user_name": "Tim",
            "whisperx": {"model": "large-v3", "device": "cuda", "language": "en"},
            "huggingface_token": "hf_test",
            "todoist": {"api_token": "t", "default_project": "Recap", "project_map": {}},
            "claude": {"command": "claude"},
        }))
        config = load_config(config_file)
        assert config.meetings_path == config.vault_path / "Work" / "Meetings"
        assert config.people_path == config.vault_path / "Work" / "People"
        assert config.companies_path == config.vault_path / "Work" / "Companies"
