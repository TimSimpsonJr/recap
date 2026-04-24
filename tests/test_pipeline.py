"""Tests for pipeline orchestrator."""
import json
import pathlib
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
            Utterance(speaker_id="SPEAKER_00", speaker="SPEAKER_00", start=0.0, end=5.0, text="Hello"),
            Utterance(speaker_id="SPEAKER_01", speaker="SPEAKER_01", start=5.0, end=10.0, text="Hi"),
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


@pytest.fixture
def expected_note_path(vault_path):
    """The note path run_pipeline will actually produce given the standard fixtures."""
    return vault_path / "org" / "Meetings" / "2026-04-14 - Test Meeting.md"


# ---------------------------------------------------------------------------
# Patch targets (all lazy-imported inside run_pipeline)
#
# Intentionally omits `write_meeting_note`: tests let the real vault writer
# run and assert on actual file contents, per docs/plans/2026-04-14-fix-everything-design.md.
# ML stages (transcribe/diarize/analyze) stay mocked because running them
# under test is out of scope.
# ---------------------------------------------------------------------------
_PATCH_TRANSCRIBE = "recap.pipeline.transcribe.transcribe"
_PATCH_DIARIZE = "recap.pipeline.diarize.diarize"
_PATCH_ASSIGN = "recap.pipeline.diarize.assign_speakers"
_PATCH_ANALYZE = "recap.analyze.analyze"
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
        pipeline_config, vault_path, expected_note_path,
    ):
        """Assert ML stages run in order and export actually produces a real note file."""
        call_order = []

        def track(name, return_value=None):
            def side_effect(*a, **kw):
                call_order.append(name)
                return return_value
            return side_effect

        diarized = TranscriptResult(
            utterances=[
                Utterance(speaker_id="SPK_0", speaker="SPK_0", start=0.0, end=5.0, text="Hello"),
                Utterance(speaker_id="SPK_1", speaker="SPK_1", start=5.0, end=10.0, text="Hi"),
            ],
            raw_text="Hello Hi",
            language="en",
        )

        with (
            patch(_PATCH_DURATION, return_value=120.0),
            patch(_PATCH_TRANSCRIBE, side_effect=track("transcribe", mock_transcript)),
            patch(_PATCH_DIARIZE, side_effect=track("diarize", [{"start": 0, "end": 5, "speaker": "SPK_0"}])),
            patch(_PATCH_ASSIGN, side_effect=track("assign_speakers", diarized)),
            patch(_PATCH_ANALYZE, side_effect=track("analyze", mock_analysis)),
            patch(_PATCH_CONVERT, side_effect=track("convert", audio_file.with_suffix(".m4a"))),
            patch(_PATCH_DELETE_SRC),
        ):
            result = run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_slug="org",
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
            )

        # ML stages fired in the right order, with convert coming last (after export).
        assert call_order == [
            "transcribe", "diarize", "assign_speakers",
            "analyze", "convert",
        ]
        # The real export wrote a real file with canonical frontmatter.
        assert result == expected_note_path
        assert expected_note_path.exists()
        content = expected_note_path.read_text(encoding="utf-8")
        assert "pipeline-status: complete" in content
        assert "title: Test Meeting" in content


class TestStreamingTranscript:
    """When a streaming transcript with real speakers is provided, skip transcribe + diarize."""

    def test_skips_transcribe_and_diarize(
        self, audio_file, mock_metadata, mock_analysis, pipeline_config,
        vault_path, expected_note_path,
    ):
        streaming = TranscriptResult(
            utterances=[
                Utterance(speaker_id="Tim", speaker="Tim", start=0.0, end=5.0, text="Hello"),
                Utterance(speaker_id="Jane", speaker="Jane", start=5.0, end=10.0, text="Hi"),
            ],
            raw_text="Hello Hi",
            language="en",
        )

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE) as m_transcribe,
            patch(_PATCH_DIARIZE) as m_diarize,
            patch(_PATCH_ASSIGN) as m_assign,
            patch(_PATCH_ANALYZE, return_value=mock_analysis),
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_slug="org",
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
                streaming_transcript=streaming,
            )

        m_transcribe.assert_not_called()
        m_diarize.assert_not_called()
        m_assign.assert_not_called()
        # Export still ran -- real note on disk proves it.
        assert expected_note_path.exists()

    def test_all_unknown_speakers_falls_through(
        self, audio_file, mock_metadata, mock_transcript, mock_analysis,
        pipeline_config, vault_path, expected_note_path,
    ):
        """If streaming transcript has only UNKNOWN speakers, do NOT skip transcribe."""
        streaming = TranscriptResult(
            utterances=[
                Utterance(speaker_id="UNKNOWN", speaker="UNKNOWN", start=0.0, end=5.0, text="Hello"),
            ],
            raw_text="Hello",
            language="en",
        )
        diarized = TranscriptResult(
            utterances=[Utterance(speaker_id="SPK_0", speaker="SPK_0", start=0.0, end=5.0, text="Hello")],
            raw_text="Hello",
            language="en",
        )

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE, return_value=mock_transcript) as m_transcribe,
            patch(_PATCH_DIARIZE, return_value=[{"start": 0, "end": 5, "speaker": "SPK_0"}]),
            patch(_PATCH_ASSIGN, return_value=diarized),
            patch(_PATCH_ANALYZE, return_value=mock_analysis),
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_slug="org",
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
                streaming_transcript=streaming,
            )

        m_transcribe.assert_called_once()
        assert expected_note_path.exists()


class TestStatusTracking:
    """Verify status.json is written after each stage."""

    def test_status_updated_per_stage(
        self, audio_file, mock_metadata, mock_transcript, mock_analysis,
        pipeline_config, vault_path,
    ):
        diarized = TranscriptResult(
            utterances=[Utterance(speaker_id="SPK_0", speaker="SPK_0", start=0.0, end=5.0, text="Hello")],
            raw_text="Hello",
            language="en",
        )

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
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
            patch.object(Path, "write_text", spy_write_text),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_slug="org",
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
            )

        # Status file should have recorded each stage transition in order.
        pipeline_statuses = [s.get("pipeline-status") for s in statuses_seen]
        assert "transcribing" in pipeline_statuses
        assert "analyzing" in pipeline_statuses
        assert "exporting" in pipeline_statuses
        assert "complete" in pipeline_statuses


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
                org_slug="org",
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
            utterances=[Utterance(speaker_id="SPK_0", speaker="SPK_0", start=0.0, end=5.0, text="Hello")],
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
                org_slug="org",
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
        self, audio_file, mock_metadata, mock_analysis, pipeline_config,
        vault_path, expected_note_path,
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

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE) as m_transcribe,
            patch(_PATCH_DIARIZE) as m_diarize,
            patch(_PATCH_ASSIGN) as m_assign,
            patch(_PATCH_ANALYZE, return_value=mock_analysis) as m_analyze,
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
        ):
            run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_slug="org",
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
                from_stage="analyze",
            )

        m_transcribe.assert_not_called()
        m_diarize.assert_not_called()
        m_assign.assert_not_called()
        m_analyze.assert_called_once()
        # Export still ran even though we started from "analyze".
        assert expected_note_path.exists()


class TestReturnValue:
    """run_pipeline returns the path to the meeting note."""

    def test_returns_note_path(
        self, audio_file, mock_metadata, mock_transcript, mock_analysis,
        pipeline_config, vault_path, expected_note_path,
    ):
        diarized = TranscriptResult(
            utterances=[Utterance(speaker_id="SPK_0", speaker="SPK_0", start=0.0, end=5.0, text="Hello")],
            raw_text="Hello",
            language="en",
        )

        with (
            patch(_PATCH_DURATION, return_value=60.0),
            patch(_PATCH_TRANSCRIBE, return_value=mock_transcript),
            patch(_PATCH_DIARIZE, return_value=[]),
            patch(_PATCH_ASSIGN, return_value=diarized),
            patch(_PATCH_ANALYZE, return_value=mock_analysis),
            patch(_PATCH_CONVERT, return_value=audio_file.with_suffix(".m4a")),
            patch(_PATCH_DELETE_SRC),
        ):
            result = run_pipeline(
                audio_path=audio_file,
                metadata=mock_metadata,
                config=pipeline_config,
                org_slug="org",
                org_subfolder="org",
                vault_path=vault_path,
                user_name="Tim",
            )

        assert result == expected_note_path
        assert result.exists()


def test_run_pipeline_export_writes_canonical_frontmatter(tmp_path, monkeypatch):
    """End-to-end test of the export stage: pipeline produces canonical frontmatter."""
    from recap.artifacts import save_transcript, save_analysis
    from recap.models import (
        AnalysisResult, MeetingMetadata, Participant, ProfileStub,
        TranscriptResult, Utterance,
    )
    from recap.pipeline import run_pipeline, PipelineRuntimeConfig
    from datetime import date
    import yaml

    # Arrange: a fake audio path with pre-existing transcript + analysis artifacts
    audio_path = tmp_path / "2026-04-14-140000-disbursecloud.flac"
    audio_path.touch()

    transcript = TranscriptResult(
        utterances=[Utterance(speaker_id="Alice", speaker="Alice", start=0.0, end=1.0, text="hi")],
        raw_text="hi", language="en",
    )
    save_transcript(audio_path, transcript)

    analysis = AnalysisResult(
        speaker_mapping={},
        meeting_type="standup", summary="s",
        key_points=[], decisions=[], action_items=[], follow_ups=[],
        relationship_notes=None,
        people=[],
        companies=[ProfileStub(name="Acme")],
    )
    save_analysis(audio_path, analysis)

    metadata = MeetingMetadata(
        title="Standup",
        date=date(2026, 4, 14),
        participants=[Participant(name="Alice")],
        platform="google_meet",
    )

    vault = tmp_path / "vault"
    config = PipelineRuntimeConfig(
        archive_format="flac",  # skip convert stage
    )

    # Act: run pipeline from export stage
    note_path = run_pipeline(
        audio_path=audio_path,
        metadata=metadata,
        config=config,
        org_slug="disbursecloud",
        org_subfolder="Clients/Disbursecloud",
        vault_path=vault,
        user_name="Tim",
        from_stage="export",
    )

    # Assert: canonical frontmatter present, org is slug, org-subfolder is path
    content = note_path.read_text(encoding="utf-8")
    _, fm_block, _ = content.split("---\n", 2)
    fm = yaml.safe_load(fm_block)

    assert fm["org"] == "disbursecloud"  # slug, not path
    assert fm["org-subfolder"] == "Clients/Disbursecloud"
    assert fm["duration"]  # set (non-empty)
    assert fm["type"] == "standup"
    assert fm["tags"] == ["meeting/standup"]
    assert fm["companies"] == ["[[Acme]]"]
    assert fm["recording"] == "2026-04-14-140000-disbursecloud.flac"
    assert fm["pipeline-status"] == "complete"


def test_run_pipeline_against_calendar_seeded_note_backfills_frontmatter(tmp_path):
    """End-to-end: pipeline running against a pre-seeded calendar note backfills canonical
    frontmatter without discarding calendar-owned keys or the agenda section.

    This is the load-bearing Bug A fix: the primitive-level test in test_vault_upsert.py
    verifies the merge semantics directly, but this test exercises the full export stage
    via run_pipeline so a future regression in either layer surfaces here.
    """
    from recap.artifacts import RecordingMetadata, save_transcript, save_analysis
    from recap.models import (
        AnalysisResult, MeetingMetadata, Participant, ProfileStub,
        TranscriptResult, Utterance,
    )
    from recap.pipeline import run_pipeline, PipelineRuntimeConfig
    from datetime import date
    import yaml

    # Arrange: audio + artifacts in the recordings dir
    audio_path = tmp_path / "2026-04-14-140000-disbursecloud.flac"
    audio_path.touch()

    transcript = TranscriptResult(
        utterances=[Utterance(speaker_id="Alice", speaker="Alice", start=0.0, end=1.0, text="hi")],
        raw_text="hi", language="en",
    )
    save_transcript(audio_path, transcript)

    analysis = AnalysisResult(
        speaker_mapping={},
        meeting_type="quarterly_review", summary="Productive Q2 discussion.",
        key_points=[], decisions=[], action_items=[], follow_ups=[],
        relationship_notes=None,
        people=[],
        companies=[ProfileStub(name="Acme")],
    )
    save_analysis(audio_path, analysis)

    # Pre-seed a calendar-written note (frontmatter + agenda, no marker)
    vault = tmp_path / "vault"
    meetings_dir = vault / "Clients/Disbursecloud" / "Meetings"
    meetings_dir.mkdir(parents=True)
    calendar_note = meetings_dir / "2026-04-14 - Q2 Review.md"
    calendar_note.write_text(
        "---\n"
        "date: 2026-04-14\n"
        "time: 14:00-15:00\n"
        "title: Q2 Review\n"
        "participants:\n"
        "- '[[Alice]]'\n"
        "calendar-source: google\n"
        "org: disbursecloud\n"
        "meeting-link: https://meet.google.com/abc\n"
        "event-id: evt-123\n"
        "pipeline-status: pending\n"
        "---\n"
        "\n"
        "## Agenda\n\nDiscuss Q2 targets.\n",
        encoding="utf-8",
    )

    metadata = MeetingMetadata(
        title="Q2 Review",
        date=date(2026, 4, 14),
        participants=[Participant(name="Alice")],
        platform="google_meet",
    )

    # RecordingMetadata with note_path set — this is how __main__.py tells run_pipeline
    # which pre-existing calendar note to upsert into.
    recording_metadata = RecordingMetadata(
        org="disbursecloud",
        note_path=str(calendar_note),
        title="Q2 Review",
        date="2026-04-14",
        participants=[Participant(name="Alice")],
        platform="google_meet",
        calendar_source="google",
        event_id="evt-123",
        meeting_link="https://meet.google.com/abc",
    )

    config = PipelineRuntimeConfig(
        archive_format="flac",  # skip convert stage
    )

    # Act: run pipeline from export stage against the pre-seeded calendar note
    note_path = run_pipeline(
        audio_path=audio_path,
        metadata=metadata,
        config=config,
        org_slug="disbursecloud",
        org_subfolder="Clients/Disbursecloud",
        vault_path=vault,
        user_name="Tim",
        from_stage="export",
        recording_metadata=recording_metadata,
    )

    # The resolved path should be the pre-existing calendar note
    assert note_path == calendar_note

    # Assert: merged frontmatter + agenda preserved + body below marker
    content = note_path.read_text(encoding="utf-8")
    _, fm_block, rest = content.split("---\n", 2)
    fm = yaml.safe_load(fm_block)

    # Calendar-owned keys preserved
    assert fm["time"] == "14:00-15:00"
    assert fm["event-id"] == "evt-123"
    assert fm["calendar-source"] == "google"
    assert fm["meeting-link"] == "https://meet.google.com/abc"

    # Pipeline-owned keys present and authoritative
    assert fm["duration"]  # non-empty
    assert fm["type"] == "quarterly_review"
    assert fm["tags"] == ["meeting/quarterly_review"]
    assert fm["companies"] == ["[[Acme]]"]
    assert fm["recording"] == "2026-04-14-140000-disbursecloud.flac"
    assert fm["pipeline-status"] == "complete"

    # Agenda preserved above marker; body below marker
    from recap.vault import MEETING_RECORD_MARKER
    assert MEETING_RECORD_MARKER in rest
    marker_idx = rest.index(MEETING_RECORD_MARKER)
    assert "## Agenda" in rest[:marker_idx]
    assert "Discuss Q2 targets." in rest[:marker_idx]
    assert "## Summary" in rest[marker_idx:]


def test_run_pipeline_creates_new_note_with_calendar_fields_from_recording_metadata(
    tmp_path, monkeypatch,
):
    """Codex-reported bug: creating a brand-new note (no pre-seeded calendar note)
    dropped event_id, meeting_link, and calendar_source from the frontmatter
    because build_canonical_frontmatter only saw MeetingMetadata.
    """
    from recap.artifacts import save_transcript, save_analysis, RecordingMetadata
    from recap.models import (
        AnalysisResult, MeetingMetadata, Participant, ProfileStub,
        TranscriptResult, Utterance,
    )
    from recap.pipeline import run_pipeline, PipelineRuntimeConfig
    from datetime import date
    import yaml

    audio_path = tmp_path / "2026-04-14-140000-disbursecloud.flac"
    audio_path.touch()

    transcript = TranscriptResult(
        utterances=[Utterance(speaker_id="Alice", speaker="Alice", start=0.0, end=1.0, text="hi")],
        raw_text="hi", language="en",
    )
    save_transcript(audio_path, transcript)

    analysis = AnalysisResult(
        speaker_mapping={}, meeting_type="standup", summary="s",
        key_points=[], decisions=[], action_items=[], follow_ups=[],
        relationship_notes=None, people=[],
        companies=[ProfileStub(name="Acme")],
    )
    save_analysis(audio_path, analysis)

    metadata = MeetingMetadata(
        title="Standup",
        date=date(2026, 4, 14),
        participants=[Participant(name="Alice")],
        platform="google_meet",
    )

    recording_metadata = RecordingMetadata(
        org="disbursecloud",
        note_path="",
        title="Standup",
        date="2026-04-14",
        participants=[Participant(name="Alice")],
        platform="google_meet",
        calendar_source="google",
        event_id="evt-123",
        meeting_link="https://meet.google.com/abc",
    )

    vault = tmp_path / "vault"
    config = PipelineRuntimeConfig(archive_format="flac")

    note_path = run_pipeline(
        audio_path=audio_path,
        metadata=metadata,
        config=config,
        org_slug="disbursecloud",
        org_subfolder="Clients/Disbursecloud",
        vault_path=vault,
        user_name="Tim",
        from_stage="export",
        recording_metadata=recording_metadata,
    )

    content = note_path.read_text(encoding="utf-8")
    _, fm_block, _ = content.split("---\n", 2)
    fm = yaml.safe_load(fm_block)

    # Calendar fields present on brand-new note
    assert fm["calendar-source"] == "google"
    assert fm["event-id"] == "evt-123"
    assert fm["meeting-link"] == "https://meet.google.com/abc"

    # Pipeline fields also present
    assert fm["pipeline-status"] == "complete"
    assert fm["org"] == "disbursecloud"
    assert fm["org-subfolder"] == "Clients/Disbursecloud"


def test_run_pipeline_writes_vault_relative_note_path(tmp_path):
    """After Phase 2, recording_metadata.note_path is vault-relative after pipeline run."""
    from recap.artifacts import (
        save_transcript, save_analysis, load_recording_metadata, RecordingMetadata,
    )
    from recap.models import (
        AnalysisResult, MeetingMetadata, Participant,
        TranscriptResult, Utterance,
    )
    from recap.pipeline import run_pipeline, PipelineRuntimeConfig
    from datetime import date

    audio_path = tmp_path / "2026-04-14-140000-d.flac"
    audio_path.touch()
    save_transcript(audio_path, TranscriptResult(
        utterances=[Utterance(speaker_id="Alice", speaker="Alice", start=0, end=1, text="hi")],
        raw_text="hi", language="en",
    ))
    save_analysis(audio_path, AnalysisResult(
        speaker_mapping={}, meeting_type="standup", summary="s",
        key_points=[], decisions=[], action_items=[], follow_ups=[],
        relationship_notes=None, people=[], companies=[],
    ))
    metadata = MeetingMetadata(
        title="Standup", date=date(2026, 4, 14),
        participants=[Participant(name="Alice")], platform="manual",
    )
    recording_metadata = RecordingMetadata(
        org="d", note_path="", title="Standup", date="2026-04-14",
        participants=[Participant(name="Alice")], platform="manual",
    )
    vault = tmp_path / "vault"
    config = PipelineRuntimeConfig(archive_format="flac")

    run_pipeline(
        audio_path=audio_path, metadata=metadata, config=config,
        org_slug="d", org_subfolder="DFolder", vault_path=vault, user_name="T",
        from_stage="export", recording_metadata=recording_metadata,
    )

    # After the run, metadata file should have a vault-relative note_path
    reloaded = load_recording_metadata(audio_path)
    assert reloaded is not None
    assert reloaded.note_path  # non-empty
    assert not pathlib.Path(reloaded.note_path).is_absolute()
    # And the path should resolve correctly
    abs_path = vault / reloaded.note_path
    assert abs_path.exists()


def test_run_pipeline_reads_legacy_absolute_note_path(tmp_path):
    """Legacy metadata files with absolute note_path should still work."""
    from recap.artifacts import (
        save_transcript, save_analysis, write_recording_metadata, RecordingMetadata,
    )
    from recap.models import (
        AnalysisResult, MeetingMetadata, Participant,
        TranscriptResult, Utterance,
    )
    from recap.pipeline import run_pipeline, PipelineRuntimeConfig
    from datetime import date

    audio_path = tmp_path / "rec.flac"
    audio_path.touch()
    save_transcript(audio_path, TranscriptResult(
        utterances=[Utterance(speaker_id="A", speaker="A", start=0, end=1, text="hi")],
        raw_text="hi", language="en",
    ))
    save_analysis(audio_path, AnalysisResult(
        speaker_mapping={}, meeting_type="standup", summary="s",
        key_points=[], decisions=[], action_items=[], follow_ups=[],
        relationship_notes=None, people=[], companies=[],
    ))

    vault = tmp_path / "vault"
    meetings = vault / "DFolder/Meetings"
    meetings.mkdir(parents=True)
    legacy_note = meetings / "2026-04-14 - Standup.md"
    legacy_note.write_text(
        "---\ndate: 2026-04-14\n---\n\n## Agenda\n", encoding="utf-8",
    )

    recording_metadata = RecordingMetadata(
        org="d", note_path=str(legacy_note),  # absolute — legacy shape
        title="Standup", date="2026-04-14", participants=[], platform="manual",
    )
    write_recording_metadata(audio_path, recording_metadata)

    metadata = MeetingMetadata(
        title="Standup", date=date(2026, 4, 14),
        participants=[], platform="manual",
    )
    config = PipelineRuntimeConfig(archive_format="flac")

    run_pipeline(
        audio_path=audio_path, metadata=metadata, config=config,
        org_slug="d", org_subfolder="DFolder", vault_path=vault, user_name="T",
        from_stage="export", recording_metadata=recording_metadata,
    )

    # The absolute path was resolved correctly and the note was updated
    content = legacy_note.read_text(encoding="utf-8")
    assert "pipeline-status: complete" in content

    # Verify the metadata file was migrated to vault-relative form
    from recap.artifacts import load_recording_metadata
    reloaded = load_recording_metadata(audio_path)
    assert reloaded is not None
    assert not pathlib.Path(reloaded.note_path).is_absolute()
    assert reloaded.note_path == "DFolder/Meetings/2026-04-14 - Standup.md"
