"""Tests for pipeline orchestrator."""
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from recap.models import (
    AnalysisResult,
    MeetingMetadata,
    Participant,
    ProfileStub,
    TranscriptResult,
    Utterance,
)
from recap.pipeline import PipelineRuntimeConfig, run_pipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_metadata():
    return MeetingMetadata(
        title="Test Meeting",
        date=date(2026, 4, 14),
        participants=[Participant(name="Tim"), Participant(name="Jane")],
        platform="teams",
    )


@pytest.fixture
def mock_transcript():
    return TranscriptResult(
        utterances=[
            Utterance(speaker="SPEAKER_00", start=0.0, end=5.0, text="Hello"),
            Utterance(speaker="SPEAKER_01", start=5.0, end=10.0, text="Hi"),
        ],
        raw_text="Hello Hi",
        language="en",
    )


@pytest.fixture
def mock_analysis():
    return AnalysisResult(
        speaker_mapping={"SPEAKER_00": "Tim", "SPEAKER_01": "Jane"},
        meeting_type="standup",
        summary="A quick standup.",
        key_points=[],
        decisions=[],
        action_items=[],
        follow_ups=[],
        relationship_notes=None,
        people=[ProfileStub(name="Tim"), ProfileStub(name="Jane")],
        companies=[ProfileStub(name="Acme")],
    )


@pytest.fixture
def pipeline_config(tmp_path):
    return PipelineRuntimeConfig(
        transcription_model="nvidia/parakeet-tdt-0.6b-v2",
        diarization_model="nvidia/diar_streaming_sortformer_4spk-v2.1",
        device="cpu",
        llm_backend="claude",
        ollama_model="",
        archive_format="aac",
        archive_bitrate="64k",
        delete_source_after_archive=False,
        auto_retry=False,
        max_retries=0,
        prompt_template_path=None,
        status_dir=tmp_path / "status",
    )


@pytest.fixture
def vault_path(tmp_path):
    vp = tmp_path / "vault"
    vp.mkdir()
    return vp


@pytest.fixture
def audio_file(tmp_path):
    af = tmp_path / "recording.flac"
    af.write_text("fake audio")
    return af


# ---------------------------------------------------------------------------
# Patch targets (all lazy-imported inside run_pipeline)
# ---------------------------------------------------------------------------
_PATCH_TRANSCRIBE = "recap.pipeline.transcribe.transcribe"
_PATCH_DIARIZE = "recap.pipeline.diarize.diarize"
_PATCH_ASSIGN = "recap.pipeline.diarize.assign_speakers"
_PATCH_ANALYZE = "recap.analyze.analyze"
_PATCH_WRITE_NOTE = "recap.vault.write_meeting_note"
_PATCH_WRITE_STUBS = "recap.vault.write_profile_stubs"
_PATCH_FIND_PREV = "recap.vault.find_previous_meeting"
_PATCH_CONVERT = "recap.pipeline.audio_convert.convert_flac_to_aac"
_PATCH_DELETE_SRC = "recap.pipeline.audio_convert.delete_source_if_configured"
_PATCH_DURATION = "recap.pipeline._get_audio_duration"  # lives in recap/pipeline/__init__.py


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStageOrder:
    """Verify that stages execute in the correct sequence."""

    def test_all_stages_run_in_order(
        self, audio_file, mock_metadata, mock_transcript, mock_analysis,
        pipeline_config, vault_path,
    ):
        call_order = []

        def track(name, return_value=None):
            def side_effect(*a, **kw):
                call_order.append(name)
                return return_value
            return side_effect

        diarized = TranscriptResult(
            utterances=[
                Utterance(speaker="SPK_0", start=0.0, end=5.0, text="Hello"),
                Utterance(speaker="SPK_1", start=5.0, end=10.0, text="Hi"),
            ],
            raw_text="Hello Hi",
            language="en",
        )
        note_path = vault_path / "org" / "Meetings" / "2026-04-14 - Test Meeting.md"

        with (
            patch(_PATCH_DURATION, return_value=120.0),
            patch(_PATCH_TRANSCRIBE, side_effect=track("transcribe", mock_transcript)),
            patch(_PATCH_DIARIZE, side_effect=track("diarize", [{"start": 0, "end": 5, "speaker": "SPK_0"}])),
            patch(_PATCH_ASSIGN, side_effect=track("assign_speakers", diarized)),
            patch(_PATCH_ANALYZE, side_effect=track("analyze", mock_analysis)),
            patch(_PATCH_WRITE_NOTE, side_effect=track("write_note", note_path)),
            patch(_PATCH_WRITE_STUBS, side_effect=track("write_stubs", [])),
            patch(_PATCH_FIND_PREV, return_value=None),
            patch(_PATCH_CONVERT, side_effect=track("convert", audio_file.with_suffix(".m4a"))),
            patch(_PATCH_DELETE_SRC),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
            )

        assert call_order == [
            "transcribe", "diarize", "assign_speakers",
            "analyze", "write_note", "write_stubs", "convert",
        ]


class TestStreamingTranscript:
    """When a streaming transcript with real speakers is provided, skip transcribe + diarize."""

    def test_skips_transcribe_and_diarize(
        self, audio_file, mock_metadata, mock_analysis, pipeline_config, vault_path,
    ):
        streaming = TranscriptResult(
            utterances=[
                Utterance(speaker="Tim", start=0.0, end=5.0, text="Hello"),
                Utterance(speaker="Jane", start=5.0, end=10.0, text="Hi"),
            ],
            raw_text="Hello Hi",
            language="en",
        )
        note_path = vault_path / "org" / "Meetings" / "2026-04-14 - Test Meeting.md"

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE) as m_transcribe,
            patch(_PATCH_DIARIZE) as m_diarize,
            patch(_PATCH_ASSIGN) as m_assign,
            patch(_PATCH_ANALYZE, return_value=mock_analysis),
            patch(_PATCH_WRITE_NOTE, return_value=note_path),
            patch(_PATCH_WRITE_STUBS, return_value=[]),
            patch(_PATCH_FIND_PREV, return_value=None),
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
                streaming_transcript=streaming,
            )

        m_transcribe.assert_not_called()
        m_diarize.assert_not_called()
        m_assign.assert_not_called()

    def test_all_unknown_speakers_falls_through(
        self, audio_file, mock_metadata, mock_transcript, mock_analysis,
        pipeline_config, vault_path,
    ):
        """If streaming transcript has only UNKNOWN speakers, do NOT skip transcribe."""
        streaming = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=0.0, end=5.0, text="Hello"),
            ],
            raw_text="Hello",
            language="en",
        )
        diarized = TranscriptResult(
            utterances=[Utterance(speaker="SPK_0", start=0.0, end=5.0, text="Hello")],
            raw_text="Hello",
            language="en",
        )
        note_path = vault_path / "org" / "Meetings" / "2026-04-14 - Test Meeting.md"

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE, return_value=mock_transcript) as m_transcribe,
            patch(_PATCH_DIARIZE, return_value=[{"start": 0, "end": 5, "speaker": "SPK_0"}]),
            patch(_PATCH_ASSIGN, return_value=diarized),
            patch(_PATCH_ANALYZE, return_value=mock_analysis),
            patch(_PATCH_WRITE_NOTE, return_value=note_path),
            patch(_PATCH_WRITE_STUBS, return_value=[]),
            patch(_PATCH_FIND_PREV, return_value=None),
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
                streaming_transcript=streaming,
            )

        m_transcribe.assert_called_once()


class TestStatusTracking:
    """Verify status.json is written after each stage."""

    def test_status_updated_per_stage(
        self, audio_file, mock_metadata, mock_transcript, mock_analysis,
        pipeline_config, vault_path,
    ):
        diarized = TranscriptResult(
            utterances=[Utterance(speaker="SPK_0", start=0.0, end=5.0, text="Hello")],
            raw_text="Hello",
            language="en",
        )
        note_path = vault_path / "org" / "Meetings" / "2026-04-14 - Test Meeting.md"

        statuses_seen = []

        original_write = Path.write_text

        def spy_write_text(self_path, content, *a, **kw):
            original_write(self_path, content, *a, **kw)
            if self_path.name == "recording.json" and self_path.parent.name == "status":
                statuses_seen.append(json.loads(content))

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE, return_value=mock_transcript),
            patch(_PATCH_DIARIZE, return_value=[]),
            patch(_PATCH_ASSIGN, return_value=diarized),
            patch(_PATCH_ANALYZE, return_value=mock_analysis),
            patch(_PATCH_WRITE_NOTE, return_value=note_path),
            patch(_PATCH_WRITE_STUBS, return_value=[]),
            patch(_PATCH_FIND_PREV, return_value=None),
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
            patch.object(Path, "write_text", spy_write_text),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
            )

        # Should have status writes for: transcribe start/complete, diarize start/complete,
        # analyze start/complete, export start/complete, convert start/complete, final complete
        pipeline_statuses = [s.get("pipeline-status") for s in statuses_seen]
        assert "transcribing" in pipeline_statuses
        assert "analyzing" in pipeline_statuses
        assert "complete" in pipeline_statuses

    def test_final_status_is_complete(
        self, audio_file, mock_metadata, mock_transcript, mock_analysis,
        pipeline_config, vault_path,
    ):
        diarized = TranscriptResult(
            utterances=[Utterance(speaker="SPK_0", start=0.0, end=5.0, text="Hello")],
            raw_text="Hello",
            language="en",
        )
        note_path = vault_path / "org" / "Meetings" / "2026-04-14 - Test Meeting.md"

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE, return_value=mock_transcript),
            patch(_PATCH_DIARIZE, return_value=[]),
            patch(_PATCH_ASSIGN, return_value=diarized),
            patch(_PATCH_ANALYZE, return_value=mock_analysis),
            patch(_PATCH_WRITE_NOTE, return_value=note_path),
            patch(_PATCH_WRITE_STUBS, return_value=[]),
            patch(_PATCH_FIND_PREV, return_value=None),
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
            )

        status_file = pipeline_config.status_dir / "recording.json"
        assert status_file.exists()
        final = json.loads(status_file.read_text())
        assert final["pipeline-status"] == "complete"


class TestFailureStatus:
    """On stage failure, status.json records the failure."""

    def test_transcribe_failure_writes_status(
        self, audio_file, mock_metadata, pipeline_config, vault_path,
    ):
        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE, side_effect=RuntimeError("GPU exploded")),
            pytest.raises(RuntimeError, match="GPU exploded"),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
            )

        status_file = pipeline_config.status_dir / "recording.json"
        assert status_file.exists()
        data = json.loads(status_file.read_text())
        assert data["pipeline-status"] == "failed:transcribe"
        assert "error" in data

    def test_analyze_failure_writes_status(
        self, audio_file, mock_metadata, mock_transcript, pipeline_config, vault_path,
    ):
        diarized = TranscriptResult(
            utterances=[Utterance(speaker="SPK_0", start=0.0, end=5.0, text="Hello")],
            raw_text="Hello",
            language="en",
        )

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE, return_value=mock_transcript),
            patch(_PATCH_DIARIZE, return_value=[]),
            patch(_PATCH_ASSIGN, return_value=diarized),
            patch(_PATCH_ANALYZE, side_effect=RuntimeError("Claude is down")),
            pytest.raises(RuntimeError, match="Claude is down"),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
            )

        status_file = pipeline_config.status_dir / "recording.json"
        data = json.loads(status_file.read_text())
        assert data["pipeline-status"] == "failed:analyze"


class TestFromStage:
    """from_stage should skip all stages before the specified one."""

    def test_from_analyze_skips_transcribe_and_diarize(
        self, audio_file, mock_metadata, mock_analysis, pipeline_config, vault_path,
    ):
        # Create a saved transcript file so the skip-load works
        transcript_save = audio_file.with_suffix(".transcript.json")
        transcript_data = {
            "utterances": [
                {"speaker": "SPK_0", "start": 0.0, "end": 5.0, "text": "Hello"},
            ],
            "raw_text": "Hello",
            "language": "en",
        }
        transcript_save.write_text(json.dumps(transcript_data))

        note_path = vault_path / "org" / "Meetings" / "2026-04-14 - Test Meeting.md"

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE) as m_transcribe,
            patch(_PATCH_DIARIZE) as m_diarize,
            patch(_PATCH_ASSIGN) as m_assign,
            patch(_PATCH_ANALYZE, return_value=mock_analysis) as m_analyze,
            patch(_PATCH_WRITE_NOTE, return_value=note_path),
            patch(_PATCH_WRITE_STUBS, return_value=[]),
            patch(_PATCH_FIND_PREV, return_value=None),
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
                from_stage="analyze",
            )

        m_transcribe.assert_not_called()
        m_diarize.assert_not_called()
        m_assign.assert_not_called()
        m_analyze.assert_called_once()


class TestMeetingNoteFrontmatter:
    """Verify that note frontmatter is updated on completion."""

    def test_frontmatter_updated_on_complete(
        self, audio_file, mock_metadata, mock_transcript, mock_analysis,
        pipeline_config, vault_path,
    ):
        meetings_dir = vault_path / "org" / "Meetings"
        meetings_dir.mkdir(parents=True, exist_ok=True)
        note_path = meetings_dir / "2026-04-14 - Test Meeting.md"

        # Create a note with frontmatter that write_meeting_note would create
        note_path.write_text(
            "---\npipeline-status: analyzing\n---\n\n## Meeting Record\n\nContent here\n",
            encoding="utf-8",
        )

        diarized = TranscriptResult(
            utterances=[Utterance(speaker="SPK_0", start=0.0, end=5.0, text="Hello")],
            raw_text="Hello",
            language="en",
        )

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE, return_value=mock_transcript),
            patch(_PATCH_DIARIZE, return_value=[]),
            patch(_PATCH_ASSIGN, return_value=diarized),
            patch(_PATCH_ANALYZE, return_value=mock_analysis),
            patch(_PATCH_WRITE_NOTE, return_value=note_path),
            patch(_PATCH_WRITE_STUBS, return_value=[]),
            patch(_PATCH_FIND_PREV, return_value=None),
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
            )

        content = note_path.read_text(encoding="utf-8")
        assert "pipeline-status: complete" in content


class TestReturnValue:
    """run_pipeline returns the path to the meeting note."""

    def test_returns_note_path(
        self, audio_file, mock_metadata, mock_transcript, mock_analysis,
        pipeline_config, vault_path,
    ):
        diarized = TranscriptResult(
            utterances=[Utterance(speaker="SPK_0", start=0.0, end=5.0, text="Hello")],
            raw_text="Hello",
            language="en",
        )
        expected_note = vault_path / "org" / "Meetings" / "2026-04-14 - Test Meeting.md"

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE, return_value=mock_transcript),
            patch(_PATCH_DIARIZE, return_value=[]),
            patch(_PATCH_ASSIGN, return_value=diarized),
            patch(_PATCH_ANALYZE, return_value=mock_analysis),
            patch(_PATCH_WRITE_NOTE, return_value=expected_note),
            patch(_PATCH_WRITE_STUBS, return_value=[]),
            patch(_PATCH_FIND_PREV, return_value=None),
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
        ):
            result = run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
            )

        assert result == expected_note
