"""Tests for _apply_speaker_mapping keyed by speaker_id (#28)."""
from __future__ import annotations

from recap.models import TranscriptResult, Utterance
from recap.pipeline import _apply_speaker_mapping


def _make_transcript(utterances: list[Utterance]) -> TranscriptResult:
    return TranscriptResult(
        utterances=utterances,
        raw_text=" ".join(u.text for u in utterances),
        language="en",
    )


def test_maps_display_label_by_speaker_id():
    t = _make_transcript([
        Utterance(speaker_id="SPEAKER_00", speaker="SPEAKER_00", start=0, end=1, text="hi"),
        Utterance(speaker_id="SPEAKER_01", speaker="SPEAKER_01", start=1, end=2, text="hey"),
    ])
    mapped = _apply_speaker_mapping(t, {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"})
    assert mapped.utterances[0].speaker == "Alice"
    assert mapped.utterances[1].speaker == "Bob"


def test_preserves_speaker_id_on_mapped_utterances():
    t = _make_transcript([
        Utterance(speaker_id="SPEAKER_00", speaker="SPEAKER_00", start=0, end=1, text="hi"),
    ])
    mapped = _apply_speaker_mapping(t, {"SPEAKER_00": "Alice"})
    assert mapped.utterances[0].speaker_id == "SPEAKER_00"


def test_unmapped_speaker_id_leaves_speaker_unchanged():
    t = _make_transcript([
        Utterance(speaker_id="SPEAKER_00", speaker="SPEAKER_00", start=0, end=1, text="hi"),
        Utterance(speaker_id="SPEAKER_01", speaker="SPEAKER_01", start=1, end=2, text="hey"),
    ])
    mapped = _apply_speaker_mapping(t, {"SPEAKER_00": "Alice"})
    assert mapped.utterances[0].speaker == "Alice"
    assert mapped.utterances[1].speaker == "SPEAKER_01"


def test_re_correction_maps_from_current_speaker_id():
    """After Alice was mapped, speaker='Alice' speaker_id=SPEAKER_00.
    Re-correcting to Bob must key on SPEAKER_00, not on 'Alice'."""
    t = _make_transcript([
        Utterance(speaker_id="SPEAKER_00", speaker="Alice", start=0, end=1, text="hi"),
    ])
    mapped = _apply_speaker_mapping(t, {"SPEAKER_00": "Bob"})
    assert mapped.utterances[0].speaker == "Bob"
    assert mapped.utterances[0].speaker_id == "SPEAKER_00"


def test_legacy_mapping_keyed_by_display_label_is_no_op():
    """Pre-#28 .speakers.json files key by display label. Those keys
    don't match new speaker_id values, so mapping silently no-ops.
    Documented behavior."""
    t = _make_transcript([
        Utterance(speaker_id="SPEAKER_00", speaker="SPEAKER_00", start=0, end=1, text="hi"),
    ])
    # Legacy mapping keyed by display label.
    mapped = _apply_speaker_mapping(t, {"some_old_display_label": "Alice"})
    assert mapped.utterances[0].speaker == "SPEAKER_00"  # unchanged
