"""Build pipeline runtime configs from daemon + org + recording metadata.

Extracted from __main__ so tests can import it without pulling in GUI
dependencies (pystray, etc.) that only the daemon entry point needs.
"""
from __future__ import annotations

from recap.artifacts import RecordingMetadata
from recap.daemon.config import DaemonConfig, OrgConfig
from recap.pipeline import PipelineRuntimeConfig


def build_runtime_config(
    config: DaemonConfig,
    org_config: OrgConfig,
    recording_metadata: RecordingMetadata | None = None,
) -> PipelineRuntimeConfig:
    """Build a PipelineRuntimeConfig from daemon config, org config, and (optionally) recording metadata.

    If recording_metadata has an llm_backend explicitly set (non-None), it overrides
    org_config.llm_backend. This is how the Signal popup's backend choice reaches
    analyze. A `None` llm_backend (the default) means "no explicit override," so the
    org default wins — avoiding a silent regression where the default "claude" value
    masks an org configured for ollama.
    """
    backend = (
        recording_metadata.llm_backend
        if recording_metadata is not None and recording_metadata.llm_backend is not None
        else org_config.llm_backend
    )
    return PipelineRuntimeConfig(
        transcription_model=config.pipeline.transcription_model,
        diarization_model=config.pipeline.diarization_model,
        device="cuda",
        llm_backend=backend,
        ollama_model=config.ollama.model,
        archive_format=config.recording.archive_format,
        archive_bitrate="64k",
        delete_source_after_archive=config.recording.delete_source_after_archive,
        auto_retry=config.pipeline.auto_retry,
        max_retries=config.pipeline.max_retries,
        prompt_template_path=None,
        status_dir=config.vault_path / "_Recap" / ".recap" / "status",
        known_contacts=config.known_contacts,
    )
