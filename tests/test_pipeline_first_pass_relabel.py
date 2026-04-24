"""Tests for first-pass auto-relabel (#28)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from recap.artifacts import speakers_path
from recap.models import MeetingMetadata, Participant, TranscriptResult, Utterance
from recap.pipeline import _maybe_apply_first_pass_relabel


def _md(participants: list[str]) -> MeetingMetadata:
    return MeetingMetadata(
        title="Test", date=date(2026, 4, 24),
        participants=[Participant(name=n) for n in participants],
        platform="test",
    )


def _tr(speaker_ids: list[str]) -> TranscriptResult:
    return TranscriptResult(
        utterances=[
            Utterance(speaker_id=sid, speaker=sid, start=0, end=1, text="x")
            for sid in speaker_ids
        ],
        raw_text="x", language="en",
    )


def test_case_a_writes_mapping(tmp_path: Path):
    audio = tmp_path / "r.flac"
    audio.touch()
    _maybe_apply_first_pass_relabel(audio, _tr(["SPEAKER_00"]), _md(["Alice"]))
    sp = json.loads(speakers_path(audio).read_text())
    assert sp == {"SPEAKER_00": "Alice"}


def test_zero_participants_no_write(tmp_path: Path):
    audio = tmp_path / "r.flac"
    audio.touch()
    _maybe_apply_first_pass_relabel(audio, _tr(["SPEAKER_00"]), _md([]))
    assert not speakers_path(audio).exists()


def test_two_participants_no_write(tmp_path: Path):
    audio = tmp_path / "r.flac"
    audio.touch()
    _maybe_apply_first_pass_relabel(audio, _tr(["SPEAKER_00"]), _md(["Alice", "Bob"]))
    assert not speakers_path(audio).exists()


def test_two_speaker_ids_no_write(tmp_path: Path):
    audio = tmp_path / "r.flac"
    audio.touch()
    _maybe_apply_first_pass_relabel(
        audio, _tr(["SPEAKER_00", "SPEAKER_01"]), _md(["Alice"]),
    )
    assert not speakers_path(audio).exists()


def test_respects_existing_speakers_json(tmp_path: Path):
    audio = tmp_path / "r.flac"
    audio.touch()
    speakers_path(audio).write_text('{"SPEAKER_00": "PreCorrected"}')
    _maybe_apply_first_pass_relabel(audio, _tr(["SPEAKER_00"]), _md(["Alice"]))
    sp = json.loads(speakers_path(audio).read_text())
    assert sp == {"SPEAKER_00": "PreCorrected"}


def test_ineligible_participant_no_write(tmp_path: Path):
    audio = tmp_path / "r.flac"
    audio.touch()
    _maybe_apply_first_pass_relabel(
        audio, _tr(["SPEAKER_00"]), _md(["Unknown Speaker 1"]),
    )
    assert not speakers_path(audio).exists()
