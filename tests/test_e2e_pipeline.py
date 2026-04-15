"""End-to-end pipeline test (Phase 6 Task 2).

Mocks ML stages only (transcribe / diarize / analyze) -- everything
between them runs for real: the vault writer, artifacts sidecars,
EventIndex updates, and FLAC duration probing via ffprobe. Validates
the contract the daemon depends on after a recording finishes.

Two subtests:
1. baseline run-pipeline-on-fresh-recording writes canonical frontmatter
2. calendar-seeded upsert preserves calendar-owned fields and flips status

Per parent design (docs/plans/2026-04-14-fix-everything-design.md
sections 0.1 and 397-408), the canonical frontmatter contract is
load-bearing and must survive both the baseline write and the
calendar-seeded upsert path.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from datetime import date
from unittest.mock import patch

import pytest
import yaml

from recap.artifacts import RecordingMetadata, write_recording_metadata
from recap.daemon.calendar.index import EventIndex
from recap.daemon.calendar.sync import CalendarEvent, write_calendar_note
from recap.daemon.config import OrgConfig
from recap.models import (
    ActionItem,
    AnalysisResult,
    KeyPoint,
    MeetingMetadata,
    Participant,
    ProfileStub,
    TranscriptResult,
    Utterance,
)
from recap.pipeline import PipelineRuntimeConfig, run_pipeline


# Patch targets match the lazy imports inside run_pipeline. See
# tests/test_pipeline.py for the canonical list.
_PATCH_TRANSCRIBE = "recap.pipeline.transcribe.transcribe"
_PATCH_DIARIZE = "recap.pipeline.diarize.diarize"
_PATCH_ASSIGN = "recap.pipeline.diarize.assign_speakers"
_PATCH_ANALYZE = "recap.analyze.analyze"
_PATCH_CONVERT = "recap.pipeline.audio_convert.convert_flac_to_aac"
_PATCH_DELETE_SRC = "recap.pipeline.audio_convert.delete_source_if_configured"


def _make_silent_flac(path: pathlib.Path, seconds: int = 2) -> None:
    """Generate a short silent FLAC via ffmpeg so ffprobe can read duration.

    Keeping this at 2s to minimize test runtime while still producing
    a real audio file that `_get_audio_duration` can probe.
    """
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=16000",
            "-t", str(seconds),
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def vault_path(tmp_path: pathlib.Path) -> pathlib.Path:
    """Fresh tmp vault. Pipeline + calendar sync create their own subfolders."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def recordings_path(tmp_path: pathlib.Path) -> pathlib.Path:
    rec = tmp_path / "recordings"
    rec.mkdir()
    return rec


@pytest.fixture
def runtime_config(tmp_path: pathlib.Path) -> PipelineRuntimeConfig:
    """Realistic PipelineRuntimeConfig with status_dir wired up."""
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


def _make_analysis(
    summary: str,
    key_point_topic: str,
    assignee: str,
    description: str,
) -> AnalysisResult:
    return AnalysisResult(
        speaker_mapping={"SPEAKER_00": "Alex", "SPEAKER_01": "Bri"},
        meeting_type="planning",
        summary=summary,
        key_points=[KeyPoint(topic=key_point_topic, detail="Team aligned on direction.")],
        decisions=[],
        action_items=[
            ActionItem(
                assignee=assignee,
                description=description,
                due_date=None,
                priority="normal",
            ),
        ],
        follow_ups=[],
        relationship_notes=None,
        people=[ProfileStub(name="Alex"), ProfileStub(name="Bri")],
        companies=[],
    )


def _make_transcript() -> TranscriptResult:
    return TranscriptResult(
        utterances=[
            Utterance(speaker="Alex", start=1.0, end=4.0, text="Welcome to sprint planning."),
            Utterance(speaker="Bri", start=4.5, end=7.0, text="Let's start with the priorities."),
        ],
        raw_text="Welcome to sprint planning. Let's start with the priorities.",
        language="en",
    )


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg + ffprobe required for real audio duration",
)
def test_run_pipeline_writes_full_meeting_note(
    vault_path: pathlib.Path,
    recordings_path: pathlib.Path,
    runtime_config: PipelineRuntimeConfig,
) -> None:
    """Baseline: fresh recording -> full canonical frontmatter + body sections.

    Validates the Phase 6 acceptance criterion for section 397: the
    note written by run_pipeline has canonical frontmatter fully
    present and a body with Summary / Key Points / Action Items.
    """
    audio_path = recordings_path / "2026-04-15-100000-alpha.flac"
    _make_silent_flac(audio_path)

    participants = [Participant(name="Alex"), Participant(name="Bri")]
    metadata = MeetingMetadata(
        title="Sprint planning",
        date=date(2026, 4, 15),
        participants=participants,
        platform="meet",
    )
    rec_meta = RecordingMetadata(
        org="alpha",
        note_path="",
        title="Sprint planning",
        date="2026-04-15",
        participants=participants,
        platform="meet",
        llm_backend="claude",
    )
    write_recording_metadata(audio_path, rec_meta)

    transcript = _make_transcript()
    analysis = _make_analysis(
        summary="Sprint planning kicked off; Alex and Bri aligned on priorities.",
        key_point_topic="Aligned on priorities",
        assignee="Alex",
        description="draft priorities doc",
    )

    with (
        patch(_PATCH_TRANSCRIBE, return_value=transcript),
        patch(_PATCH_DIARIZE, return_value=[
            {"speaker": "Alex", "start": 1.0, "end": 4.0},
            {"speaker": "Bri", "start": 4.5, "end": 7.0},
        ]),
        patch(_PATCH_ASSIGN, return_value=transcript),
        patch(_PATCH_ANALYZE, return_value=analysis),
        patch(_PATCH_CONVERT, return_value=audio_path.with_suffix(".m4a")),
        patch(_PATCH_DELETE_SRC),
    ):
        note_path = run_pipeline(
            audio_path=audio_path,
            metadata=metadata,
            config=runtime_config,
            org_slug="alpha",
            org_subfolder="Clients/Alpha",
            vault_path=vault_path,
            user_name="Tim",
            recording_metadata=rec_meta,
        )

    assert note_path.exists()

    text = note_path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    parts = text.split("---\n", 2)
    assert len(parts) >= 3, "Note must have YAML frontmatter delimited by ---"
    fm = yaml.safe_load(parts[1])

    # ---- Canonical frontmatter contract (docs/plans/2026-04-14-fix-everything-design.md section 0.1) ----
    # Exact keys emitted by recap/vault.py::build_canonical_frontmatter for a fresh note:
    # date, title, org, org-subfolder, platform, participants, companies, duration,
    # type, tags, pipeline-status, recording.
    expected_keys = {
        "date", "title", "org", "org-subfolder", "platform",
        "participants", "companies", "duration", "type", "tags",
        "pipeline-status", "recording",
    }
    missing = expected_keys - set(fm.keys())
    assert not missing, f"Missing canonical frontmatter keys: {missing}"
    assert fm["pipeline-status"] == "complete"
    assert fm["org"] == "alpha"
    assert fm["org-subfolder"] == "Clients/Alpha"
    assert fm["platform"] == "meet"
    assert fm["title"] == "Sprint planning"
    assert fm["date"] == "2026-04-15"
    assert fm["participants"] == ["[[Alex]]", "[[Bri]]"]
    assert fm["recording"] == "2026-04-15-100000-alpha.m4a"  # archive_format=aac

    # ---- Body contract ----
    body = parts[2]
    assert "## Summary" in body
    assert "Sprint planning kicked off" in body
    assert "## Key Points" in body
    assert "Aligned on priorities" in body
    assert "## Action Items" in body
    assert "draft priorities doc" in body
    # user_name=Tim, assignee="Alex" -> should render as a [[Alex]] wikilink
    assert "[[Alex]]" in body

    # ---- Artifacts sidecars on disk ----
    assert audio_path.with_suffix(".transcript.json").exists()
    assert audio_path.with_suffix(".analysis.json").exists()
    assert audio_path.with_suffix(".metadata.json").exists()

    # ---- Status file updated to "complete" ----
    status_file = runtime_config.status_dir / f"{audio_path.stem}.json"
    assert status_file.exists()
    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert status["pipeline-status"] == "complete"

    # ---- EventJournal: pipeline does NOT write to the vault's events.jsonl ----
    # The pipeline_complete event is emitted by recap/daemon/__main__.py
    # after run_pipeline returns, not by run_pipeline itself. The e2e
    # test deliberately does NOT instantiate a Daemon, so no journal
    # entry is expected here. This is documented behavior, not a gap.
    journal_path = vault_path / "_Recap" / ".recap" / "events.jsonl"
    assert not journal_path.exists(), (
        "run_pipeline should not write to the event journal on its own; "
        "that is the daemon wrapper's responsibility"
    )


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg + ffprobe required for real audio duration",
)
def test_run_pipeline_upserts_calendar_seeded_note(
    vault_path: pathlib.Path,
    recordings_path: pathlib.Path,
    runtime_config: PipelineRuntimeConfig,
) -> None:
    """Calendar stub + pipeline run -> one note with canonical frontmatter.

    Phase 6 acceptance (docs/plans/2026-04-14-fix-everything-design.md
    section 408): full canonical frontmatter must survive the upsert,
    event-id and calendar-source must be preserved, and pipeline-status
    must flip from "pending" (the value write_calendar_note writes) to
    "complete".
    """
    org_cfg = OrgConfig(
        name="alpha",
        subfolder="Clients/Alpha",
        llm_backend="claude",
        default=True,
    )
    event = CalendarEvent(
        event_id="evt-cal-1",
        title="Sprint planning",
        date="2026-04-15",
        time="10:00-11:00",
        participants=["Alex", "Bri"],
        calendar_source="google",
        org="alpha",
        meeting_link="https://meet.google.com/xyz",
        description="Sprint planning agenda",
    )
    index_path = vault_path / "_Recap" / ".recap" / "event-index.json"
    event_index = EventIndex(index_path)

    seeded_note_path = write_calendar_note(
        event=event,
        vault_path=vault_path,
        org_config=org_cfg,
        event_index=event_index,
    )
    seeded_text = seeded_note_path.read_text(encoding="utf-8")
    seeded_fm = yaml.safe_load(seeded_text.split("---\n", 2)[1])
    # Sanity: calendar stub has event-id and is "pending" (the value the
    # current sync.py writes; the plan doc's "scheduled" is outdated).
    assert seeded_fm["event-id"] == "evt-cal-1"
    assert seeded_fm["pipeline-status"] == "pending"
    assert seeded_fm["calendar-source"] == "google"
    assert seeded_fm["meeting-link"] == "https://meet.google.com/xyz"

    # Now the recording lands with the SAME event_id -> upsert, not duplicate.
    audio_path = recordings_path / "2026-04-15-100000-alpha.flac"
    _make_silent_flac(audio_path)

    participants = [Participant(name="Alex"), Participant(name="Bri")]
    metadata = MeetingMetadata(
        title="Sprint planning",
        date=date(2026, 4, 15),
        participants=participants,
        platform="meet",
    )
    rec_meta = RecordingMetadata(
        org="alpha",
        note_path="",
        title="Sprint planning",
        date="2026-04-15",
        participants=participants,
        platform="meet",
        calendar_source="google",
        event_id="evt-cal-1",  # upsert key
        meeting_link="https://meet.google.com/xyz",
        llm_backend="claude",
    )
    write_recording_metadata(audio_path, rec_meta)

    transcript = _make_transcript()
    analysis = _make_analysis(
        summary="Sprint planning kicked off; team aligned.",
        key_point_topic="Aligned on priorities",
        assignee="Bri",
        description="circulate notes",
    )

    with (
        patch(_PATCH_TRANSCRIBE, return_value=transcript),
        patch(_PATCH_DIARIZE, return_value=[
            {"speaker": "Alex", "start": 1.0, "end": 4.0},
        ]),
        patch(_PATCH_ASSIGN, return_value=transcript),
        patch(_PATCH_ANALYZE, return_value=analysis),
        patch(_PATCH_CONVERT, return_value=audio_path.with_suffix(".m4a")),
        patch(_PATCH_DELETE_SRC),
    ):
        final_note_path = run_pipeline(
            audio_path=audio_path,
            metadata=metadata,
            config=runtime_config,
            org_slug="alpha",
            org_subfolder="Clients/Alpha",
            vault_path=vault_path,
            user_name="Tim",
            recording_metadata=rec_meta,
            event_index=event_index,
        )

    # ---- No duplicate notes ----
    meetings_dir = vault_path / "Clients" / "Alpha" / "Meetings"
    notes = list(meetings_dir.glob("*.md"))
    assert len(notes) == 1, (
        f"Expected exactly 1 meeting note after upsert, got {len(notes)}: "
        f"{[n.name for n in notes]}"
    )
    assert final_note_path == notes[0]
    # And the upsert should have hit the seeded note in place.
    assert final_note_path == seeded_note_path

    # ---- Canonical frontmatter intact after upsert ----
    final_text = final_note_path.read_text(encoding="utf-8")
    fm = yaml.safe_load(final_text.split("---\n", 2)[1])
    expected_canonical_keys = {
        "date", "title", "org", "org-subfolder", "platform",
        "participants", "companies", "duration", "type", "tags",
        "pipeline-status", "recording",
    }
    missing = expected_canonical_keys - set(fm.keys())
    assert not missing, (
        f"Canonical frontmatter incomplete after calendar-seeded upsert: "
        f"missing {missing}"
    )
    # Calendar-owned fields survived the upsert.
    assert fm.get("event-id") == "evt-cal-1", (
        "event-id from calendar stub must survive upsert"
    )
    assert fm.get("calendar-source") == "google"
    assert fm.get("meeting-link") == "https://meet.google.com/xyz"
    # Pipeline-status flipped from "pending" to "complete".
    assert fm["pipeline-status"] == "complete"

    # ---- Body sections present ----
    body = final_text.split("---\n", 2)[2]
    assert "## Summary" in body
    assert "Sprint planning kicked off" in body
    assert "## Action Items" in body
    assert "circulate notes" in body

    # ---- EventIndex entry points at the final note path ----
    refreshed_index = EventIndex(index_path)
    entry = refreshed_index.lookup("evt-cal-1")
    assert entry is not None, "EventIndex must retain entry for event-id"
    resolved = vault_path / entry.path
    assert resolved == final_note_path, (
        f"EventIndex entry {entry.path} should resolve to final note "
        f"{final_note_path.relative_to(vault_path)}"
    )
