"""Tests for effective_participants union in reprocess flow (#28 Task 13)."""
from __future__ import annotations

from datetime import date

import pytest

from recap.daemon.config import KnownContact
from recap.models import MeetingMetadata, Participant, TranscriptResult, Utterance
from recap.pipeline import _build_effective_participants


def _md(participants: list[Participant]) -> MeetingMetadata:
    return MeetingMetadata(
        title="T", date=date(2026, 4, 24),
        participants=participants, platform="test",
    )


def _tr(speakers: list[tuple[str, str]]) -> TranscriptResult:
    """Utterances: (speaker_id, display_label) pairs."""
    return TranscriptResult(
        utterances=[
            Utterance(speaker_id=sid, speaker=disp, start=0, end=1, text="x")
            for sid, disp in speakers
        ],
        raw_text="x", language="en",
    )


def test_union_enrichment_then_correction():
    """Enrichment Alice + transcript SPEAKER_01->Bob => union [Alice, Bob]."""
    metadata = _md([Participant(name="Alice", email="alice@x.com")])
    transcript = _tr([("SPEAKER_00", "Alice"), ("SPEAKER_01", "Bob")])
    result = _build_effective_participants(metadata, transcript, known_contacts=[])
    assert [p.name for p in result] == ["Alice", "Bob"]


def test_enrichment_only_when_transcript_has_no_eligible_speakers():
    """Transcript SPEAKER_00 ineligible => result is just enrichment."""
    metadata = _md([Participant(name="Alice")])
    transcript = _tr([("SPEAKER_00", "SPEAKER_00")])  # ineligible display
    result = _build_effective_participants(metadata, transcript, known_contacts=[])
    assert [p.name for p in result] == ["Alice"]


def test_correction_adds_names_not_in_enrichment():
    """Enrichment empty + transcript Alice => Alice added via correction."""
    metadata = _md([])
    transcript = _tr([("SPEAKER_00", "Alice")])
    result = _build_effective_participants(metadata, transcript, known_contacts=[])
    assert [p.name for p in result] == ["Alice"]


def test_stale_enrichment_stays_alongside_correction():
    """Documented limitation: enrichment's Bob (stale) stays alongside Alice (corrected)."""
    metadata = _md([Participant(name="Bob")])
    transcript = _tr([("SPEAKER_00", "Alice")])
    result = _build_effective_participants(metadata, transcript, known_contacts=[])
    assert [p.name for p in result] == ["Bob", "Alice"]


def test_re_canonicalizes_via_aliases():
    """Enrichment has 'Sean M.'; known_contacts has Sean Mooney with that alias."""
    metadata = _md([Participant(name="Sean M.")])
    transcript = _tr([])
    contacts = [KnownContact(
        name="Sean Mooney", display_name="Sean Mooney",
        aliases=["Sean M."],
    )]
    result = _build_effective_participants(metadata, transcript, contacts)
    assert [p.name for p in result] == ["Sean Mooney"]


def test_re_canonicalizes_via_email():
    """Enrichment has Nickname with email; contact has matching email."""
    metadata = _md([Participant(name="Nickname", email="sean@x.com")])
    transcript = _tr([])
    contacts = [KnownContact(
        name="Sean Mooney", display_name="Sean Mooney",
        email="sean@x.com",
    )]
    result = _build_effective_participants(metadata, transcript, contacts)
    assert [p.name for p in result] == ["Sean Mooney"]


def test_duplicates_removed_by_name():
    """Same-named enrichment entries merge; correction matches too."""
    metadata = _md([Participant(name="Alice"), Participant(name="Alice")])
    transcript = _tr([("SPEAKER_00", "Alice")])
    result = _build_effective_participants(metadata, transcript, known_contacts=[])
    assert [p.name for p in result] == ["Alice"]


def test_preserves_first_seen_order():
    """Enrichment order preserved; transcript-only names appended after."""
    metadata = _md([Participant(name="Bob"), Participant(name="Alice")])
    transcript = _tr([("SPEAKER_00", "Carol"), ("SPEAKER_01", "Alice")])
    result = _build_effective_participants(metadata, transcript, known_contacts=[])
    assert [p.name for p in result] == ["Bob", "Alice", "Carol"]
