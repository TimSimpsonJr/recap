"""Tests for daemon runtime_config helpers.

These exercise the pure helper extracted from __main__.py; the helper was
moved into its own module so tests can import it without pulling in GUI
dependencies (pystray, etc.) that only the daemon entry point needs.
"""
from __future__ import annotations

import pathlib

from recap.artifacts import RecordingMetadata
from recap.daemon.config import (
    DaemonConfig,
    OrgConfig,
    PipelineSettings,
    RecordingConfig,
)
from recap.daemon.runtime_config import build_runtime_config


def _make_daemon_config() -> DaemonConfig:
    cfg = DaemonConfig.__new__(DaemonConfig)
    # Fill required fields minimally — DaemonConfig has many defaults
    cfg.vault_path = pathlib.Path("/tmp/vault")
    cfg.recordings_path = pathlib.Path("/tmp/rec")
    cfg.pipeline = PipelineSettings()
    cfg.recording = RecordingConfig()
    return cfg


def _make_org(llm_backend: str = "claude") -> OrgConfig:
    return OrgConfig(name="test", subfolder="Test", llm_backend=llm_backend)


class TestBuildRuntimeConfig:
    def test_uses_recording_metadata_backend_when_set(self):
        daemon_config = _make_daemon_config()
        org = _make_org(llm_backend="claude")
        metadata = RecordingMetadata(
            org="test", note_path="", title="t",
            date="2026-04-14", participants=[], platform="signal",
            llm_backend="ollama",
        )

        runtime = build_runtime_config(daemon_config, org, metadata)
        assert runtime.llm_backend == "ollama"

    def test_falls_back_to_org_config_when_metadata_backend_absent(self):
        daemon_config = _make_daemon_config()
        org = _make_org(llm_backend="claude")
        # Simulate legacy metadata by setting the default
        metadata = RecordingMetadata(
            org="test", note_path="", title="t",
            date="2026-04-14", participants=[], platform="manual",
            # llm_backend defaults to "claude", which matches org default
        )

        runtime = build_runtime_config(daemon_config, org, metadata)
        assert runtime.llm_backend == "claude"
