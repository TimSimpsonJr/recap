"""Tests for daemon config loading."""
import pytest
import yaml

from recap.daemon.config import load_daemon_config


class TestLoadDaemonConfig:
    def test_loads_minimal_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path / "vault"),
            "recordings-path": str(tmp_path / "recordings"),
        }))
        config = load_daemon_config(config_file)
        assert config.vault_path == tmp_path / "vault"
        assert config.recordings_path == tmp_path / "recordings"

    def test_default_org_is_identified(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
            "orgs": {
                "work": {"subfolder": "_Recap/Work", "llm-backend": "claude", "default": True},
                "personal": {"subfolder": "_Recap/Personal", "llm-backend": "claude"},
            },
        }))
        config = load_daemon_config(config_file)
        assert config.default_org.name == "work"
        assert config.default_org.llm_backend == "claude"

    def test_rejects_unknown_config_version(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 99,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
        }))
        with pytest.raises(ValueError, match="config-version"):
            load_daemon_config(config_file)

    def test_missing_vault_path_raises(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "recordings-path": str(tmp_path),
        }))
        with pytest.raises(ValueError, match="vault-path"):
            load_daemon_config(config_file)

    def test_missing_recordings_path_raises(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
        }))
        with pytest.raises(ValueError, match="recordings-path"):
            load_daemon_config(config_file)

    def test_detection_defaults(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
        }))
        config = load_daemon_config(config_file)
        assert config.detection.teams.enabled is True
        assert config.detection.teams.behavior == "auto-record"
        assert config.detection.signal.behavior == "prompt"

    def test_recording_defaults(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
        }))
        config = load_daemon_config(config_file)
        assert config.recording.format == "flac"
        assert config.recording.archive_format == "aac"
        assert config.recording.silence_timeout_minutes == 5
        assert config.recording.max_duration_hours == 4

    def test_pipeline_defaults(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
        }))
        config = load_daemon_config(config_file)
        assert config.pipeline.transcription_model == "nvidia/parakeet-tdt-0.6b-v2"
        assert config.pipeline.diarization_model == "nvidia/diar_streaming_sortformer_4spk-v2.1"
        assert config.pipeline.auto_retry is True
        assert config.pipeline.max_retries == 1

    def test_daemon_port_defaults(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
        }))
        config = load_daemon_config(config_file)
        assert config.daemon_ports.extension_port_start == 17839
        assert config.daemon_ports.extension_port_end == 17845
        assert config.daemon_ports.plugin_port == 9847
        assert config.daemon_ports.auto_start is False

    def test_calendar_sync_defaults(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
        }))
        config = load_daemon_config(config_file)
        assert config.calendar_sync.interval_minutes == 15
        assert config.calendar_sync.sync_on_startup is True

    def test_logging_defaults(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
        }))
        config = load_daemon_config(config_file)
        assert config.logging.path == "_Recap/.recap/logs"
        assert config.logging.retention_days == 7

    def test_full_config_loads(self, tmp_path):
        """Test loading a full config with all sections populated."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path / "vault"),
            "recordings-path": str(tmp_path / "recordings"),
            "orgs": {
                "disbursecloud": {
                    "subfolder": "_Recap/Disbursecloud",
                    "llm-backend": "claude",
                    "default": True,
                },
                "personal": {
                    "subfolder": "_Recap/Personal",
                    "llm-backend": "claude",
                },
            },
            "calendars": {
                "zoho": {"org": "disbursecloud"},
                "google": {"default-org": "personal"},
            },
            "detection": {
                "teams": {
                    "enabled": True,
                    "behavior": "auto-record",
                    "default-org": "disbursecloud",
                },
                "zoom": {
                    "enabled": False,
                    "behavior": "prompt",
                },
            },
            "known-contacts": [
                {"name": "Jane Smith", "display-name": "Jane Smith"},
            ],
            "recording": {
                "format": "wav",
                "archive-format": "opus",
                "delete-source-after-archive": True,
                "silence-timeout-minutes": 10,
                "max-duration-hours": 2,
            },
            "pipeline": {
                "transcription-model": "custom/model",
                "diarization-model": "custom/diar",
                "auto-retry": False,
                "max-retries": 3,
            },
            "calendar-sync": {
                "interval-minutes": 30,
                "sync-on-startup": False,
            },
            "logging": {
                "path": "custom/logs",
                "retention-days": 14,
            },
            "daemon": {
                "extension-port-start": 18000,
                "extension-port-end": 18010,
                "plugin-port": 9999,
                "auto-start": True,
            },
        }))
        config = load_daemon_config(config_file)

        assert config.vault_path == tmp_path / "vault"
        assert config.recordings_path == tmp_path / "recordings"

        assert config.default_org.name == "disbursecloud"
        assert len(config.orgs) == 2

        assert config.recording.format == "wav"
        assert config.recording.archive_format == "opus"
        assert config.recording.delete_source_after_archive is True

        assert config.pipeline.transcription_model == "custom/model"
        assert config.pipeline.auto_retry is False
        assert config.pipeline.max_retries == 3

        assert config.detection.teams.enabled is True
        assert config.detection.zoom.enabled is False
        assert config.detection.zoom.behavior == "prompt"

        assert config.calendar_sync.interval_minutes == 30
        assert config.logging.retention_days == 14
        assert config.daemon_ports.plugin_port == 9999
        assert config.daemon_ports.auto_start is True

        assert len(config.known_contacts) == 1
        assert config.known_contacts[0].name == "Jane Smith"
        assert config.known_contacts[0].display_name == "Jane Smith"

        assert len(config.calendars) == 2
        assert config.calendars["zoho"].org == "disbursecloud"
        assert config.calendars["google"].default_org == "personal"

    def test_default_org_falls_back_to_first(self, tmp_path):
        """When no org is marked default, the first one is returned."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
            "orgs": {
                "alpha": {"subfolder": "_Recap/Alpha", "llm-backend": "claude"},
                "beta": {"subfolder": "_Recap/Beta", "llm-backend": "ollama"},
            },
        }))
        config = load_daemon_config(config_file)
        assert config.default_org.name == "alpha"

    def test_no_orgs_default_org_returns_none(self, tmp_path):
        """When no orgs are defined, default_org returns None."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "config-version": 1,
            "vault-path": str(tmp_path),
            "recordings-path": str(tmp_path),
        }))
        config = load_daemon_config(config_file)
        assert config.default_org is None
