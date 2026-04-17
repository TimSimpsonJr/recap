"""GPU-required ML pipeline tests.

Load real models and exercise the batch pipeline end-to-end. Skipped
when CUDA is unavailable via the cuda_guard fixture.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pytest

from tests.conftest import make_silent_flac

pytestmark = pytest.mark.integration


def test_parakeet_transcribes_silent_audio_without_error(parakeet_asr_model, tmp_path):
    """Real Parakeet model processes a silent FLAC without raising."""
    audio_path = make_silent_flac(tmp_path / "silent.flac", seconds=2)
    results = parakeet_asr_model.transcribe([str(audio_path)])
    assert len(results) == 1
    assert hasattr(results[0], "text")


def test_sortformer_diarizes_silent_audio_without_error(tmp_path, cuda_guard):
    """Exercises recap.pipeline.diarize.diarize() -- production path."""
    from recap.pipeline.diarize import diarize
    audio_path = make_silent_flac(tmp_path / "silent.flac", seconds=2)
    result = diarize(audio_path)
    assert isinstance(result, list)


def test_run_pipeline_end_to_end_on_silent_audio(tmp_path, cuda_guard):
    """Full batch pipeline with real Parakeet + Sortformer + stubbed analyze."""
    from recap.artifacts import RecordingMetadata, write_recording_metadata
    from recap.models import MeetingMetadata
    from recap.pipeline import PipelineRuntimeConfig, run_pipeline

    audio_path = make_silent_flac(tmp_path / "test-meeting.flac", seconds=3)
    vault_path = tmp_path / "vault"
    (vault_path / "Test" / "Meetings").mkdir(parents=True)
    seeded_note_path = "Test/Meetings/2026-04-16 - Integration Test.md"

    recording_metadata = RecordingMetadata(
        org="test",
        note_path=seeded_note_path,
        title="Integration Test",
        date="2026-04-16",
        participants=[],
        platform="calendar",
    )
    write_recording_metadata(audio_path, recording_metadata)

    meeting_metadata = MeetingMetadata(
        title="Integration Test",
        date=date(2026, 4, 16),
        participants=[],
        platform="calendar",
    )

    pipeline_config = PipelineRuntimeConfig(
        transcription_model="nvidia/parakeet-tdt-0.6b-v2",
        diarization_model="nvidia/diar_streaming_sortformer_4spk-v2.1",
        device="cuda",
        llm_backend="claude",
        ollama_model="",
        archive_format="aac",
        archive_bitrate="64k",
        delete_source_after_archive=False,
        auto_retry=False,
        max_retries=0,
        prompt_template_path=None,
        status_dir=vault_path / "_Recap" / ".recap" / "status",
    )

    stub_analysis = {
        "speaker_mapping": {},
        "meeting_type": "other",
        "summary": "integration test stub",
        "key_points": [],
        "decisions": [],
        "action_items": [],
        "follow_ups": None,
        "relationship_notes": None,
        "people": [],
        "companies": [],
    }

    with patch("recap.analyze.subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {
            "returncode": 0,
            "stdout": json.dumps(stub_analysis),
            "stderr": "",
        })()
        run_pipeline(
            audio_path=audio_path,
            metadata=meeting_metadata,
            config=pipeline_config,
            org_slug="test",
            org_subfolder="Test",
            vault_path=vault_path,
            user_name="Tim",
            recording_metadata=recording_metadata,
        )

    note_path = vault_path / seeded_note_path
    assert note_path.exists()
    note_text = note_path.read_text()
    assert "## Summary" in note_text
    assert "pipeline-status: complete" in note_text
    assert "integration test stub" in note_text
