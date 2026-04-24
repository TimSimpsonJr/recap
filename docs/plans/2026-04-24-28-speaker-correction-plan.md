# Issue #28 — Speaker Correction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task.

**Goal:** Stable speaker identity (`speaker_id`), end-to-end correction round-trip, first-pass auto-relabel, and a gated contact-creation flow that converges duplicate aliases onto canonical identities via #29's enrichment data.

**Architecture:** `Utterance` gains immutable `speaker_id` + mutable `speaker` display label. `KnownContact` gains `aliases` + `email`. Client-side 8-step resolution engine + daemon-side atomic contact mutations + live config refresh + canonical People stub creation on correction save. Reprocess builds ephemeral `effective_participants` (enrichment + correction union) before analyze + export.

**Tech Stack:** Python 3.12 + aiohttp + ruamel.yaml; Obsidian plugin (TypeScript + existing Vitest); pytest; manual acceptance for UI.

**Design reference:** [docs/plans/2026-04-24-28-speaker-correction-design.md](docs/plans/2026-04-24-28-speaker-correction-design.md)
**Follow-up:** [#37 — Merge duplicate identities](https://github.com/TimSimpsonJr/recap/issues/37)

---

## Task Overview

1. Shared helpers (`_normalize`, `_is_eligible_person_label`)
2. `Utterance` schema + `from_dict` backfill + `TranscriptResult.from_dict` delegation
3. `_apply_speaker_mapping` keyed by `speaker_id`
4. `KnownContact` + `aliases` + `email` schema
5. `match_known_contacts` email-first + alias-aware refactor
6. `resolve_recording_path` shared helper + clip endpoint refactor to use it
7. `GET /api/meetings/{stem}/speakers` endpoint
8. `_maybe_apply_first_pass_relabel` + pipeline wiring
9. Clip endpoint `speaker_id` migration + cache filename change
10. `_apply_contact_mutations` + atomic ruamel write
11. `daemon.refresh_config()` + detector subservice propagation
12. `_ensure_people_stub` daemon helper
13. Reprocess pipeline: `effective_participants` ephemeral metadata
14. `POST /api/meetings/speakers` amendment (stem/legacy, contact_mutations, stub, trigger)
15. Plugin `normalize` + `resolve` pure functions + Vitest tests
16. Plugin `DaemonClient` additions (`getMeetingSpeakers`, `saveSpeakerCorrections`, clip by speaker_id)
17. Plugin modal rewrite (any speaker, resolution engine integration, save orchestration)
18. End-to-end integration test
19. MANIFEST + acceptance checklist + server.py docstring typo fix
20. Final verification

---

## Task 1: Shared identity helpers

**Files:**
- Create: `recap/identity.py`
- Create: `tests/test_identity.py`

**Step 1: Write failing tests**

```python
# tests/test_identity.py
"""Tests for shared identity helpers used by first-pass relabel,
reprocess participant union, and correction eligibility."""
from __future__ import annotations

import pytest

from recap.identity import _is_eligible_person_label, _normalize


class TestNormalize:
    def test_casefold(self):
        assert _normalize("Alice") == "alice"

    def test_strip_whitespace(self):
        assert _normalize("  Alice  ") == "alice"

    def test_collapse_internal_whitespace(self):
        assert _normalize("Sean  Mooney") == "sean mooney"

    def test_strip_periods_and_commas(self):
        assert _normalize("Sean M.") == "sean m"
        assert _normalize("Smith, John") == "smith john"
        assert _normalize("J.D.") == "jd"

    def test_empty_input_returns_empty(self):
        assert _normalize("") == ""
        assert _normalize("   ") == ""


class TestIsEligiblePersonLabel:
    def test_plain_name_eligible(self):
        assert _is_eligible_person_label("Sean Mooney") is True

    def test_speaker_xx_ineligible(self):
        assert _is_eligible_person_label("SPEAKER_00") is False
        assert _is_eligible_person_label("SPEAKER_12") is False

    def test_unknown_ineligible(self):
        assert _is_eligible_person_label("UNKNOWN") is False
        assert _is_eligible_person_label("Unknown Speaker 1") is False
        assert _is_eligible_person_label("unknown speaker 3") is False

    def test_parenthetical_ineligible(self):
        assert _is_eligible_person_label("Sean (development team)") is False

    def test_empty_ineligible(self):
        assert _is_eligible_person_label("") is False
        assert _is_eligible_person_label("   ") is False

    def test_initials_eligible(self):
        assert _is_eligible_person_label("Sean M.") is True
```

**Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python -m pytest tests/test_identity.py -v --override-ini="addopts="
```

Expected: ImportError for `recap.identity`.

**Step 3: Implement `recap/identity.py`**

```python
"""Shared identity helpers used across pipeline and daemon paths.

Scope:
- _normalize: lowercase + whitespace + punctuation normalization used by
  match_known_contacts (enrichment) AND client-side resolution.
- _is_eligible_person_label: daemon-level eligibility filter used by
  first-pass auto-relabel AND reprocess participant union.

Client-side (plugin) has a stricter version with Company-collision and
multi-person-form guards that require vault scan context.
"""
from __future__ import annotations

import re

_SPEAKER_ID_RE = re.compile(r"^SPEAKER_\d+$")
_UNKNOWN_RE = re.compile(r"^(UNKNOWN|Unknown Speaker.*)$", re.IGNORECASE)
_PARENTHETICAL_RE = re.compile(r"\([^)]+\)")
_MULTI_WS_RE = re.compile(r"\s+")
_STRIP_PUNCT_RE = re.compile(r"[.,]")


def _normalize(text: str) -> str:
    """casefold + strip + collapse whitespace + strip . and ,.

    Used by match_known_contacts and must match the plugin-side
    normalize() exactly (see obsidian-recap/src/correction/normalize.ts).
    """
    s = text.strip()
    if not s:
        return ""
    s = _STRIP_PUNCT_RE.sub("", s)
    s = _MULTI_WS_RE.sub(" ", s)
    return s.casefold().strip()


def _is_eligible_person_label(label: str) -> bool:
    """Daemon-level eligibility: rejects SPEAKER_XX, UNKNOWN*,
    parenthetical-containing, empty/whitespace. Accepts plain names
    and initials. Plugin adds Company-collision and multi-person guards."""
    s = label.strip()
    if not s:
        return False
    if _SPEAKER_ID_RE.match(s):
        return False
    if _UNKNOWN_RE.match(s):
        return False
    if _PARENTHETICAL_RE.search(s):
        return False
    return True
```

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_identity.py -v --override-ini="addopts="
```

Expected: 14 passing.

**Step 5: Commit**

```bash
git add recap/identity.py tests/test_identity.py
git commit -m "feat(#28): shared identity helpers (_normalize, _is_eligible_person_label)"
```

---

## Task 2: `Utterance` schema + `from_dict` migration

**Files:**
- Modify: `recap/models.py` (Utterance + TranscriptResult)
- Modify: `tests/test_models.py` (extend)

**Step 1: Write failing tests**

Add to `tests/test_models.py`:

```python
class TestUtteranceSchema:
    """Utterance.speaker_id stable identity + backfill migration (#28)."""

    def test_from_dict_backfills_speaker_id_when_missing(self):
        from recap.models import Utterance
        u = Utterance.from_dict({
            "speaker": "SPEAKER_00",
            "start": 0.0, "end": 1.0, "text": "hi",
        })
        assert u.speaker_id == "SPEAKER_00"
        assert u.speaker == "SPEAKER_00"

    def test_from_dict_preserves_explicit_speaker_id(self):
        from recap.models import Utterance
        u = Utterance.from_dict({
            "speaker_id": "SPEAKER_00",
            "speaker": "Alice",
            "start": 0.0, "end": 1.0, "text": "hi",
        })
        assert u.speaker_id == "SPEAKER_00"
        assert u.speaker == "Alice"

    def test_to_dict_roundtrip_contains_both_fields(self):
        from recap.models import Utterance
        u = Utterance(
            speaker_id="SPEAKER_00", speaker="Alice",
            start=0.0, end=1.0, text="hi",
        )
        d = u.to_dict()
        assert d["speaker_id"] == "SPEAKER_00"
        assert d["speaker"] == "Alice"

    def test_transcript_result_from_dict_delegates_to_utterance(self):
        from recap.models import TranscriptResult
        t = TranscriptResult.from_dict({
            "utterances": [
                {"speaker": "SPEAKER_00", "start": 0, "end": 1, "text": "a"},
                {"speaker": "SPEAKER_01", "start": 1, "end": 2, "text": "b"},
            ],
            "raw_text": "a b",
            "language": "en",
        })
        assert t.utterances[0].speaker_id == "SPEAKER_00"
        assert t.utterances[1].speaker_id == "SPEAKER_01"

    def test_legacy_transcript_all_backfill(self):
        """Transcript with no speaker_id fields anywhere → every utterance
        backfills speaker_id=speaker."""
        from recap.models import TranscriptResult
        t = TranscriptResult.from_dict({
            "utterances": [
                {"speaker": "Alice", "start": 0, "end": 1, "text": "hi"},
                {"speaker": "Bob", "start": 1, "end": 2, "text": "hey"},
            ],
            "raw_text": "hi hey", "language": "en",
        })
        assert [u.speaker_id for u in t.utterances] == ["Alice", "Bob"]
        assert [u.speaker for u in t.utterances] == ["Alice", "Bob"]
```

**Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python -m pytest tests/test_models.py::TestUtteranceSchema -v --override-ini="addopts="
```

Expected: AttributeError on `from_dict` or missing `speaker_id` attribute.

**Step 3: Implement in `recap/models.py`**

Edit the `Utterance` dataclass (around line 52):

```python
@dataclass
class Utterance:
    speaker_id: str  # immutable diarized identity; never rewritten after first write
    speaker: str     # mutable display label; rewritten by _apply_speaker_mapping
    start: float
    end: float
    text: str

    @classmethod
    def from_dict(cls, data: dict) -> "Utterance":
        """Load-boundary backfill: pre-#28 artifacts lack speaker_id.
        Default speaker_id = speaker so legacy transcripts load cleanly."""
        speaker = data["speaker"]
        return cls(
            speaker_id=data.get("speaker_id", speaker),
            speaker=speaker,
            start=data["start"],
            end=data["end"],
            text=data["text"],
        )

    def to_dict(self) -> dict:
        return {
            "speaker_id": self.speaker_id,
            "speaker": self.speaker,
            "start": self.start,
            "end": self.end,
            "text": self.text,
        }
```

Change `TranscriptResult.from_dict` (around line 81) to delegate per-utterance:

```python
@classmethod
def from_dict(cls, data: dict) -> "TranscriptResult":
    return cls(
        utterances=[Utterance.from_dict(u) for u in data.get("utterances", [])],
        raw_text=data.get("raw_text", ""),
        language=data.get("language", "en"),
    )
```

Callers that construct `Utterance(...)` directly (grep for `Utterance(speaker=`) need `speaker_id` added. Expected sites include `recap/pipeline/diarize.py` (assign_speakers), `recap/pipeline/__init__.py` (_apply_speaker_mapping — handled in Task 3), and any test fixtures. Fix all direct constructions to pass `speaker_id` explicitly.

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_models.py -v --override-ini="addopts="
.venv/Scripts/python -m pytest tests/ -x --override-ini="addopts=" 2>&1 | tail -20
```

Expected: new tests pass; fix any callers broken by the required `speaker_id` field.

**Step 5: Commit**

```bash
git add recap/models.py tests/test_models.py recap/pipeline/diarize.py  # add other files touched
git commit -m "feat(#28): Utterance.speaker_id stable identity + from_dict backfill"
```

**Self-review checklist:**
- All 5 new tests pass.
- No test regressions across the suite.
- Every direct `Utterance(...)` construction in the codebase passes `speaker_id` (grep verified).
- Existing on-disk `.transcript.json` files still load cleanly (backfill verified by roundtrip test).

---

## Task 3: `_apply_speaker_mapping` keyed by `speaker_id`

**Files:**
- Modify: `recap/pipeline/__init__.py` (around line 198)
- Create: `tests/test_pipeline_speaker_mapping.py`

**Step 1: Write failing tests**

```python
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
    """After Alice was mapped, speaker="Alice" speaker_id=SPEAKER_00.
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
```

**Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python -m pytest tests/test_pipeline_speaker_mapping.py -v --override-ini="addopts="
```

**Step 3: Implement — edit `recap/pipeline/__init__.py:198-217`**

Replace the existing `_apply_speaker_mapping` function body:

```python
def _apply_speaker_mapping(
    transcript: TranscriptResult,
    mapping: dict[str, str],
) -> TranscriptResult:
    """Return a copy of *transcript* with mutable display labels rewritten
    per *mapping*. Mapping keys are speaker_id values; mapping values are
    the new display labels. speaker_id is preserved on every utterance.

    Legacy .speakers.json files keyed by display label silently no-op
    because their keys won't match speaker_id values. First post-#28 save
    rewrites the file keyed by speaker_id.
    """
    from recap.models import Utterance
    new_utterances = [
        Utterance(
            speaker_id=u.speaker_id,
            speaker=mapping.get(u.speaker_id, u.speaker),
            start=u.start,
            end=u.end,
            text=u.text,
        )
        for u in transcript.utterances
    ]
    return TranscriptResult(
        utterances=new_utterances,
        raw_text=transcript.raw_text,
        language=transcript.language,
    )
```

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_pipeline_speaker_mapping.py tests/test_pipeline_*.py -v --override-ini="addopts="
```

Expected: 5 new pass, existing pipeline tests unchanged.

**Step 5: Commit**

```bash
git add recap/pipeline/__init__.py tests/test_pipeline_speaker_mapping.py
git commit -m "feat(#28): _apply_speaker_mapping keyed by speaker_id"
```

---

## Task 4: `KnownContact` schema + `aliases` + `email`

**Files:**
- Modify: `recap/daemon/config.py` (KnownContact dataclass)
- Create or extend: `tests/test_daemon_config.py`

**Step 1: Write failing tests**

Extend tests/test_daemon_config.py (create if missing; follow patterns from other config tests):

```python
class TestKnownContactSchema:
    """KnownContact schema extensions (#28): aliases + email."""

    def test_aliases_defaults_to_empty_list(self):
        from recap.daemon.config import KnownContact
        c = KnownContact(name="Alice", display_name="Alice")
        assert c.aliases == []

    def test_email_defaults_to_none(self):
        from recap.daemon.config import KnownContact
        c = KnownContact(name="Alice", display_name="Alice")
        assert c.email is None

    def test_accepts_aliases(self):
        from recap.daemon.config import KnownContact
        c = KnownContact(name="Sean Mooney", display_name="Sean Mooney",
                         aliases=["Sean M.", "Sean"])
        assert c.aliases == ["Sean M.", "Sean"]

    def test_accepts_email(self):
        from recap.daemon.config import KnownContact
        c = KnownContact(name="Alice", display_name="Alice",
                         email="alice@example.com")
        assert c.email == "alice@example.com"


class TestKnownContactYamlLoad:
    """ruamel load of known-contacts with new fields."""

    def test_loads_minimal_entry(self, tmp_path):
        """Pre-#28 entries with only name + display-name still load."""
        # Test the existing config-loading path through parse_daemon_config_dict
        # or similar existing entry point. The test asserts a YAML blob with
        # only `name` + `display-name` loads cleanly with aliases=[] email=None.
        # Exact test shape depends on existing test patterns for config loading.
        pass  # Implementer: mirror existing config-load tests in the file.

    def test_loads_with_all_new_fields(self, tmp_path):
        """New-shape YAML with aliases + email loads correctly."""
        pass  # Implementer: similar pattern.
```

**Note to implementer:** The exact YAML load test shape depends on how `tests/test_daemon_config.py` (or wherever config parsing is tested) is structured. Follow existing patterns for loading test YAML via `parse_daemon_config_dict` or the canonical loader. If no such test file exists, create one that exercises the existing load path.

**Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python -m pytest tests/test_daemon_config.py::TestKnownContactSchema -v --override-ini="addopts="
```

**Step 3: Implement in `recap/daemon/config.py`**

Find the `KnownContact` dataclass and extend:

```python
from dataclasses import dataclass, field

@dataclass
class KnownContact:
    name: str
    display_name: str
    aliases: list[str] = field(default_factory=list)
    email: str | None = None
```

Update the YAML loader (likely `parse_daemon_config_dict` or similar in the same module or `api_config.py`) to read `aliases` and `email` fields from each `known-contacts` entry. Defaults to `[]` and `None` if missing.

Kebab-case ↔ snake-case translation in `api_config.py` (per MANIFEST line 89 — "Config API translation boundary") needs to handle `aliases` (same in both) and `email` (same in both).

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_daemon_config.py -v --override-ini="addopts="
```

**Step 5: Commit**

```bash
git add recap/daemon/config.py tests/test_daemon_config.py
git commit -m "feat(#28): KnownContact + aliases + email schema"
```

---

## Task 5: `match_known_contacts` email-first + alias-aware

**Files:**
- Modify: `recap/daemon/recorder/enrichment.py`
- Modify: `tests/test_enrichment.py`

**Step 1: Write failing tests**

Add to `tests/test_enrichment.py`:

```python
from recap.models import Participant


class TestMatchKnownContactsEmailFirst:
    def test_email_match_wins_over_name(self):
        from recap.daemon.config import KnownContact
        from recap.daemon.recorder.enrichment import match_known_contacts
        contacts = [
            KnownContact(name="Alice Smith", display_name="Alice Smith",
                         email="alice@x.com"),
            KnownContact(name="Bob", display_name="Bob"),
        ]
        observed = [Participant(name="Bob", email="alice@x.com")]
        result = match_known_contacts(observed, contacts)
        assert result[0].name == "Alice Smith"

    def test_case_insensitive_email_match(self):
        from recap.daemon.config import KnownContact
        from recap.daemon.recorder.enrichment import match_known_contacts
        contacts = [KnownContact(name="Alice", display_name="Alice",
                                 email="ALICE@X.COM")]
        observed = [Participant(name="nobody", email="alice@x.com")]
        result = match_known_contacts(observed, contacts)
        assert result[0].name == "Alice"


class TestMatchKnownContactsAliases:
    def test_alias_match_returns_canonical_name(self):
        from recap.daemon.config import KnownContact
        from recap.daemon.recorder.enrichment import match_known_contacts
        contacts = [KnownContact(
            name="Sean Mooney", display_name="Sean Mooney",
            aliases=["Sean M.", "Sean"],
        )]
        observed = [Participant(name="Sean M.", email=None)]
        result = match_known_contacts(observed, contacts)
        assert result[0].name == "Sean Mooney"

    def test_empty_alias_does_not_match_empty_input(self):
        """Empty fields must be skipped when building the lookup index."""
        from recap.daemon.config import KnownContact
        from recap.daemon.recorder.enrichment import match_known_contacts
        contacts = [KnownContact(
            name="Alice", display_name="Alice",
            aliases=["", "   "],  # garbage entries
        )]
        observed = [Participant(name="", email=None)]
        result = match_known_contacts(observed, contacts)
        # No false match on empty string.
        assert result[0].name == ""


class TestMatchKnownContactsPassthrough:
    def test_no_match_returns_unchanged(self):
        from recap.daemon.recorder.enrichment import match_known_contacts
        observed = [Participant(name="Unknown", email=None)]
        result = match_known_contacts(observed, [])
        assert result[0].name == "Unknown"

    def test_preserves_email_from_observed_when_match_has_none(self):
        from recap.daemon.config import KnownContact
        from recap.daemon.recorder.enrichment import match_known_contacts
        contacts = [KnownContact(name="Alice", display_name="Alice")]
        observed = [Participant(name="Alice", email="alice@x.com")]
        result = match_known_contacts(observed, contacts)
        assert result[0].email == "alice@x.com"
```

**Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python -m pytest tests/test_enrichment.py -v --override-ini="addopts="
```

Expected: failures due to signature change (old returns `list[str]`, new returns `list[Participant]`).

**Step 3: Implement — rewrite `match_known_contacts` in `recap/daemon/recorder/enrichment.py`**

```python
from recap.identity import _normalize
from recap.models import Participant


def match_known_contacts(
    observed: list[Participant],
    contacts: list[KnownContact],
) -> list[Participant]:
    """Canonicalize observed participants against known_contacts.

    Precedence:
      1. Email match (case-insensitive exact) — strongest dedup signal
      2. Normalized name match against name / display_name / aliases
      3. Passthrough (no match)

    Returns Participant objects with canonical name (and preserved email).
    Empty fields are skipped when building the lookup index.
    """
    by_email: dict[str, KnownContact] = {}
    for c in contacts:
        if c.email:
            by_email[c.email.casefold()] = c

    by_name: dict[str, KnownContact] = {}
    for c in contacts:
        if c.name:
            by_name[_normalize(c.name)] = c
        if c.display_name:
            by_name[_normalize(c.display_name)] = c
        for alias in c.aliases:
            if alias:
                by_name[_normalize(alias)] = c

    out: list[Participant] = []
    for p in observed:
        match = None
        if p.email:
            match = by_email.get(p.email.casefold())
        if match is None:
            match = by_name.get(_normalize(p.name))
        if match is not None:
            out.append(Participant(name=match.name, email=p.email or match.email))
        else:
            out.append(p)
    return out
```

**Step 3b:** Update every caller of `match_known_contacts`. Grep for the name; rewrite callers to pass `list[Participant]` instead of `list[str]`. Likely call sites:
- `recap/daemon/recorder/enrichment.py::enrich_meeting_metadata` — currently passes `list[str]`; wrap into `Participant(name=n, email=None)` or rewrite the path to produce Participants from the start.
- `recap/daemon/recorder/detector.py` — if any direct callers.
- `recap/pipeline/__init__.py` — Task 13's re-canonicalization pass will add a new call site.

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_enrichment.py tests/ -x --override-ini="addopts="
```

**Step 5: Commit**

```bash
git add recap/daemon/recorder/enrichment.py tests/test_enrichment.py  # plus touched callers
git commit -m "feat(#28): match_known_contacts email-first + alias-aware"
```

---

## Task 6: `resolve_recording_path` shared helper

**Files:**
- Modify: `recap/artifacts.py` (add helper)
- Modify: `recap/daemon/server.py` (clip endpoint refactor)
- Create: `tests/test_artifacts_path_resolver.py`

**Step 1: Write failing tests**

```python
"""Tests for resolve_recording_path shared helper (#28)."""
from __future__ import annotations

from pathlib import Path

from recap.artifacts import resolve_recording_path


def test_returns_flac_when_only_flac_exists(tmp_path: Path):
    (tmp_path / "rec.flac").touch()
    result = resolve_recording_path(tmp_path, "rec")
    assert result == tmp_path / "rec.flac"


def test_returns_m4a_when_only_m4a_exists(tmp_path: Path):
    (tmp_path / "rec.m4a").touch()
    result = resolve_recording_path(tmp_path, "rec")
    assert result == tmp_path / "rec.m4a"


def test_prefers_flac_when_both_exist(tmp_path: Path):
    (tmp_path / "rec.flac").touch()
    (tmp_path / "rec.m4a").touch()
    result = resolve_recording_path(tmp_path, "rec")
    assert result == tmp_path / "rec.flac"


def test_returns_none_when_neither_exists(tmp_path: Path):
    assert resolve_recording_path(tmp_path, "rec") is None


def test_handles_stem_with_spaces_and_unicode(tmp_path: Path):
    stem = "2026-04-24 Meeting élan"
    (tmp_path / f"{stem}.flac").touch()
    result = resolve_recording_path(tmp_path, stem)
    assert result == tmp_path / f"{stem}.flac"
```

**Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python -m pytest tests/test_artifacts_path_resolver.py -v --override-ini="addopts="
```

**Step 3: Implement in `recap/artifacts.py`**

Add near other path helpers:

```python
def resolve_recording_path(recordings_path: Path, stem: str) -> Path | None:
    """Resolve a bare recording stem to its on-disk file.

    Precedence: .flac first, then .m4a. Returns None if neither exists.
    Used by /api/meetings/speakers and /api/recordings/{stem}/clip so
    both endpoints agree on which artifact is the source of truth.
    """
    flac = recordings_path / f"{stem}.flac"
    if flac.exists():
        return flac
    m4a = recordings_path / f"{stem}.m4a"
    if m4a.exists():
        return m4a
    return None
```

**Step 4: Refactor clip endpoint at `recap/daemon/server.py:277-350`**

Find the inline FLAC/M4A probe in the clip endpoint. Replace with `resolve_recording_path(daemon.config.recordings_path, stem)`. On `None` return, respond 404.

**Step 5: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_artifacts_path_resolver.py tests/test_clip_endpoint.py -v --override-ini="addopts="
```

Expected: new tests pass; clip endpoint tests still pass (behavior unchanged).

**Step 6: Commit**

```bash
git add recap/artifacts.py recap/daemon/server.py tests/test_artifacts_path_resolver.py
git commit -m "feat(#28): resolve_recording_path shared FLAC/M4A helper"
```

---

## Task 7: `GET /api/meetings/{stem}/speakers`

**Files:**
- Modify: `recap/daemon/server.py` (new endpoint + route)
- Modify: `tests/test_daemon_server.py` (new test class)

**Step 1: Write failing tests**

Add `TestApiMeetingSpeakersGet` class to `tests/test_daemon_server.py`:

```python
@pytest.mark.asyncio
class TestApiMeetingSpeakersGet:
    """GET /api/meetings/{stem}/speakers — returns speaker list from transcript."""

    async def test_returns_401_without_auth(self, daemon_client):
        client, _ = daemon_client
        resp = await client.get("/api/meetings/some-stem/speakers")
        assert resp.status == 401

    async def test_returns_404_for_missing_recording(self, daemon_client):
        client, _ = daemon_client
        resp = await client.get(
            "/api/meetings/nonexistent/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_returns_404_when_transcript_missing(self, daemon_client, tmp_path):
        client, daemon = daemon_client
        # Create a recording with no transcript.
        (daemon.config.recordings_path / "rec.flac").touch()
        resp = await client.get(
            "/api/meetings/rec/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_returns_distinct_speakers_in_order(self, daemon_client, tmp_path):
        """Distinct (speaker_id, display) pairs in first-seen order."""
        client, daemon = daemon_client
        audio = daemon.config.recordings_path / "rec.flac"
        audio.touch()
        from recap.artifacts import save_transcript
        from recap.models import TranscriptResult, Utterance
        save_transcript(audio, TranscriptResult(
            utterances=[
                Utterance(speaker_id="SPEAKER_00", speaker="Alice",
                          start=0, end=1, text="hi"),
                Utterance(speaker_id="SPEAKER_01", speaker="Bob",
                          start=1, end=2, text="hey"),
                Utterance(speaker_id="SPEAKER_00", speaker="Alice",
                          start=2, end=3, text="again"),
            ],
            raw_text="...", language="en",
        ))
        resp = await client.get(
            "/api/meetings/rec/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["speakers"] == [
            {"speaker_id": "SPEAKER_00", "display": "Alice"},
            {"speaker_id": "SPEAKER_01", "display": "Bob"},
        ]

    async def test_backfills_legacy_transcript_on_the_fly(self, daemon_client, tmp_path):
        """Pre-#28 transcript with only `speaker` field still produces correct output."""
        client, daemon = daemon_client
        audio = daemon.config.recordings_path / "rec.flac"
        audio.touch()
        import json
        from recap.artifacts import transcript_path
        legacy = {
            "utterances": [
                {"speaker": "SPEAKER_00", "start": 0, "end": 1, "text": "hi"},
            ],
            "raw_text": "hi", "language": "en",
        }
        transcript_path(audio).write_text(json.dumps(legacy))

        resp = await client.get(
            "/api/meetings/rec/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["speakers"] == [{"speaker_id": "SPEAKER_00", "display": "SPEAKER_00"}]

    async def test_returns_empty_list_for_zero_utterances(self, daemon_client):
        client, daemon = daemon_client
        audio = daemon.config.recordings_path / "rec.flac"
        audio.touch()
        from recap.artifacts import save_transcript
        from recap.models import TranscriptResult
        save_transcript(audio, TranscriptResult(
            utterances=[], raw_text="", language="en",
        ))
        resp = await client.get(
            "/api/meetings/rec/speakers",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["speakers"] == []
```

**Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python -m pytest tests/test_daemon_server.py::TestApiMeetingSpeakersGet -v --override-ini="addopts="
```

**Step 3: Implement handler in `recap/daemon/server.py`**

Response shape includes both `speakers` (from transcript) AND `participants` (from recording metadata sidecar), so the plugin gets emails for calendar-sourced participants in one round-trip. Client-side email-first resolution depends on this data.

```python
async def _api_meeting_speakers_get(request: web.Request) -> web.Response:
    """Return speaker list + participants (with emails) for a meeting."""
    stem = request.match_info["stem"]
    daemon: Daemon = request.app["daemon"]

    from recap.artifacts import (
        load_recording_metadata, resolve_recording_path, transcript_path,
    )
    audio_path = resolve_recording_path(daemon.config.recordings_path, stem)
    if audio_path is None:
        return web.json_response({"error": "recording not found"}, status=404)

    tpath = transcript_path(audio_path)
    if not tpath.exists():
        return web.json_response({"error": "transcript not found"}, status=404)

    try:
        data = json.loads(tpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return web.json_response({"error": f"transcript read: {e}"}, status=500)

    # Distinct (speaker_id, display) pairs in first-seen order.
    seen: dict[str, str] = {}
    for u in data.get("utterances", []):
        sid = u.get("speaker_id") or u["speaker"]  # backfill on the fly
        if sid not in seen:
            seen[sid] = u["speaker"]
    speakers = [{"speaker_id": sid, "display": disp} for sid, disp in seen.items()]

    # Participants from the recording metadata sidecar. Provides emails
    # for calendar-sourced participants so client-side email-first resolution
    # can fire. Missing sidecar → empty list (older/manual recordings).
    participants: list[dict] = []
    rm = load_recording_metadata(audio_path)
    if rm is not None:
        for p in rm.participants:
            participants.append({"name": p.name, "email": p.email})

    return web.json_response({"speakers": speakers, "participants": participants})
```

Register the route near other `/api/meetings/*` routes (around [server.py:1223](recap/daemon/server.py:1223)):

```python
app.router.add_get("/api/meetings/{stem}/speakers", _api_meeting_speakers_get)
```

**Additional test:** extend `TestApiMeetingSpeakersGet` with a scenario that writes a `RecordingMetadata` sidecar with a participant carrying an email, asserts the response `participants` array includes that entry with the email intact. Another scenario: missing sidecar → `participants: []`, still returns 200.

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_daemon_server.py::TestApiMeetingSpeakersGet -v --override-ini="addopts="
```

**Step 5: Commit**

```bash
git add recap/daemon/server.py tests/test_daemon_server.py
git commit -m "feat(#28): GET /api/meetings/{stem}/speakers endpoint"
```

---

## Task 8: `_maybe_apply_first_pass_relabel`

**Files:**
- Modify: `recap/pipeline/__init__.py` (add function + wire between diarize and analyze)
- Create: `tests/test_pipeline_first_pass_relabel.py`

**Step 1: Write failing tests**

```python
"""Tests for first-pass auto-relabel (#28)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from recap.artifacts import speakers_path
from recap.models import MeetingMetadata, Participant, TranscriptResult, Utterance
from recap.pipeline import _maybe_apply_first_pass_relabel


def _md(participants: list[str]) -> MeetingMetadata:
    from datetime import date
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
```

**Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python -m pytest tests/test_pipeline_first_pass_relabel.py -v --override-ini="addopts="
```

**Step 3: Implement in `recap/pipeline/__init__.py`**

Add near `_apply_speaker_mapping`:

```python
from recap.identity import _is_eligible_person_label


def _maybe_apply_first_pass_relabel(
    audio_path: Path,
    transcript: TranscriptResult,
    metadata: MeetingMetadata,
) -> None:
    """Write .speakers.json with a first-pass auto-mapping IF AND ONLY IF:
      - exactly one distinct speaker_id in the transcript, AND
      - exactly one eligible participant in metadata.participants.

    Writes keyed by speaker_id. Does not write if the file already exists
    (respects user corrections on subsequent reprocesses). Called between
    diarize and analyze stages on a new meeting.

    Failure to write is logged and non-blocking — pipeline proceeds with
    diarized IDs and user correction fills in later.
    """
    sp_path = speakers_path(audio_path)
    if sp_path.exists():
        return

    distinct_ids = {u.speaker_id for u in transcript.utterances}
    if len(distinct_ids) != 1:
        return

    eligible = [
        p for p in metadata.participants
        if _is_eligible_person_label(p.name)
    ]
    if len(eligible) != 1:
        return

    (sid,) = distinct_ids
    try:
        sp_path.write_text(json.dumps({sid: eligible[0].name}, indent=2))
    except OSError:
        logger.warning("first-pass relabel disk write failed", exc_info=True)
```

Wire into the pipeline between diarize stage and analyze stage. Find where diarize stage completes (look for `save_transcript(audio_path, transcript)` after diarization) and add a call to `_maybe_apply_first_pass_relabel(audio_path, transcript, metadata)` before analyze runs.

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_pipeline_first_pass_relabel.py tests/test_pipeline_*.py -v --override-ini="addopts="
```

**Step 5: Commit**

```bash
git add recap/pipeline/__init__.py tests/test_pipeline_first_pass_relabel.py
git commit -m "feat(#28): _maybe_apply_first_pass_relabel for unambiguous case"
```

---

## Task 9: Clip endpoint `speaker_id` migration

**Files:**
- Modify: `recap/daemon/server.py` (clip endpoint around lines 277-350)
- Modify: `tests/test_clip_endpoint.py` (extend)

**Step 1: Write failing tests**

Add to `tests/test_clip_endpoint.py`:

```python
class TestClipEndpointSpeakerId:
    """Clip lookup + cache filename key on speaker_id, not display label (#28)."""

    async def test_query_uses_speaker_id(self, daemon_client):
        """Request with ?speaker_id=SPEAKER_00 matches the utterance."""
        # Seed a transcript with speaker_id distinct from display label.
        # Hit /api/recordings/{stem}/clip?speaker_id=SPEAKER_00.
        # Assert 200 (or 404 if clip generation not available in test env).
        pass  # Implementer: mirror existing clip endpoint test patterns.

    async def test_cache_filename_uses_speaker_id(self, daemon_client):
        """Cached clip file on disk is named <speaker_id>_<duration>s.mp3,
        not <display_label>_..."""
        pass  # Implementer: assert cache file path shape.

    async def test_backfill_for_legacy_transcript(self, daemon_client):
        """Legacy transcript with only `speaker` field works (speaker_id
        backfills to speaker, clip query can still resolve)."""
        pass  # Implementer.
```

**Note to implementer:** Follow patterns already in `tests/test_clip_endpoint.py`. Don't break the existing `speaker=` query-param contract in one atomic step — the plugin's DaemonClient needs to switch first (Task 16). Strategy: accept BOTH `speaker_id` (new) and `speaker` (old) during the transition. Later, after the plugin ships, drop `speaker` support in a follow-up issue if desired. For #28 scope: make `speaker_id` work and keep `speaker` working as fallback.

**Step 2: Run tests (new ones fail)**

```bash
.venv/Scripts/python -m pytest tests/test_clip_endpoint.py -v --override-ini="addopts="
```

**Step 3: Modify the clip endpoint**

Around `recap/daemon/server.py:277-350`. Accept both query params:

```python
speaker_id = request.rel_url.query.get("speaker_id")
speaker = request.rel_url.query.get("speaker")
if not speaker_id and not speaker:
    return web.json_response({"error": "missing speaker_id"}, status=400)

# ... (existing transcript load, already in the code) ...

# Match by speaker_id first (new); fall back to speaker (legacy).
def _matches(u: dict) -> bool:
    u_sid = u.get("speaker_id") or u.get("speaker")
    if speaker_id and u_sid == speaker_id:
        return True
    if speaker and u.get("speaker") == speaker:
        return True
    return False

match = next((u for u in utterances if _matches(u)), None)
if match is None:
    return web.json_response({"error": "speaker not found"}, status=404)

# Cache filename uses speaker_id (or speaker for legacy fallback).
cache_key = speaker_id or speaker
cache_file = cache_dir / f"{cache_key}_{duration}s.mp3"
```

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_clip_endpoint.py -v --override-ini="addopts="
```

**Step 5: Commit**

```bash
git add recap/daemon/server.py tests/test_clip_endpoint.py
git commit -m "feat(#28): clip endpoint speaker_id + legacy speaker fallback"
```

---

## Task 10: `_apply_contact_mutations` atomic ruamel write

**Files:**
- Modify: `recap/daemon/api_config.py` (or wherever ruamel PATCH lives)
- Create: `tests/test_daemon_config_mutations.py`

**Step 1: Write failing tests**

```python
"""Tests for contact mutations (create + add_alias) via ruamel round-trip."""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path

from recap.daemon.api_config import _apply_contact_mutations  # new export


def _write_config(tmp_path: Path, contacts: list[dict]) -> Path:
    """Write a minimal config.yaml with known-contacts for testing."""
    path = tmp_path / "config.yaml"
    doc = {
        "vault-path": str(tmp_path / "vault"),
        "recordings-path": str(tmp_path / "recordings"),
        "orgs": {"test": {"slug": "test"}},
        "default-org": "test",
        "known-contacts": contacts,
    }
    path.write_text(yaml.safe_dump(doc))
    return path


def test_create_appends_new_contact(tmp_path, monkeypatch):
    path = _write_config(tmp_path, [])
    daemon = _fake_daemon(config_path=path)  # implementer: construct per existing patterns
    _apply_contact_mutations(daemon, [
        {"action": "create", "name": "Alice", "display_name": "Alice",
         "email": "alice@x.com"},
    ])
    doc = yaml.safe_load(path.read_text())
    assert doc["known-contacts"] == [
        {"name": "Alice", "display-name": "Alice", "email": "alice@x.com"},
    ]


def test_add_alias_extends_list(tmp_path):
    path = _write_config(tmp_path, [
        {"name": "Sean Mooney", "display-name": "Sean Mooney"},
    ])
    daemon = _fake_daemon(config_path=path)
    _apply_contact_mutations(daemon, [
        {"action": "add_alias", "name": "Sean Mooney", "alias": "Sean M."},
    ])
    doc = yaml.safe_load(path.read_text())
    assert doc["known-contacts"][0].get("aliases") == ["Sean M."]


def test_add_alias_idempotent(tmp_path):
    path = _write_config(tmp_path, [
        {"name": "Sean Mooney", "display-name": "Sean Mooney",
         "aliases": ["Sean M."]},
    ])
    daemon = _fake_daemon(config_path=path)
    _apply_contact_mutations(daemon, [
        {"action": "add_alias", "name": "Sean Mooney", "alias": "Sean M."},
    ])
    doc = yaml.safe_load(path.read_text())
    assert doc["known-contacts"][0]["aliases"] == ["Sean M."]  # no duplicate


def test_invalid_mutation_shape_raises_disk_unchanged(tmp_path):
    path = _write_config(tmp_path, [])
    before = path.read_text()
    daemon = _fake_daemon(config_path=path)
    with pytest.raises(Exception):
        _apply_contact_mutations(daemon, [{"action": "nonexistent"}])
    assert path.read_text() == before


def test_preserves_user_custom_blocks(tmp_path):
    """ruamel round-trip preserves comments and custom fields."""
    path = tmp_path / "config.yaml"
    path.write_text("""
# User's custom block
vault-path: /vault
known-contacts:
  - name: Alice
    display-name: Alice
    custom-field: value  # preserved
""")
    daemon = _fake_daemon(config_path=path)
    _apply_contact_mutations(daemon, [
        {"action": "create", "name": "Bob", "display_name": "Bob"},
    ])
    text = path.read_text()
    assert "# User's custom block" in text
    assert "custom-field: value" in text
    assert "Bob" in text
```

**Note to implementer:** `_fake_daemon` is a test harness. Mirror how `test_api_config.py` or similar existing files construct fake Daemon objects for config PATCH tests.

**Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python -m pytest tests/test_daemon_config_mutations.py -v --override-ini="addopts="
```

**Step 3: Implement `_apply_contact_mutations` in `recap/daemon/api_config.py`** (or wherever the existing PATCH/ruamel machinery lives — grep for `ruamel` and `config_lock`):

```python
def _apply_contact_mutations(daemon, mutations: list[dict]) -> None:
    """Apply contact mutations atomically then refresh live config.

    Guarantees:
      - File write is atomic (temp + rename).
      - End-to-end apply+refresh is NOT atomic: if file write succeeds
        but refresh_config() fails, disk is correct but memory stale.
      - Steps 1-3 (load, stage, validate) never touch disk if they raise.
    """
    with daemon.config_lock:
        # 1. Load via ruamel (preserves comments + custom fields).
        yaml_doc = _load_ruamel(daemon.config_path)

        # 2. Stage mutations.
        contacts = yaml_doc.get("known-contacts") or []
        for m in mutations:
            action = m.get("action")
            if action == "create":
                if "name" not in m or "display_name" not in m:
                    raise ValueError(f"create mutation missing name/display_name: {m}")
                entry = {"name": m["name"], "display-name": m["display_name"]}
                if m.get("email"):
                    entry["email"] = m["email"]
                contacts.append(entry)
            elif action == "add_alias":
                if "name" not in m or "alias" not in m:
                    raise ValueError(f"add_alias mutation missing fields: {m}")
                target = next((c for c in contacts if c.get("name") == m["name"]), None)
                if target is None:
                    raise ValueError(f"add_alias target not found: {m['name']}")
                aliases = target.get("aliases") or []
                if m["alias"] not in aliases:
                    aliases.append(m["alias"])
                    target["aliases"] = aliases
            else:
                raise ValueError(f"unknown mutation action: {action}")
        yaml_doc["known-contacts"] = contacts

        # 3. Validate via existing config validator.
        # Implementer: find the exact call site used by /api/config PATCH;
        # it may be parse_daemon_config_dict(dict(yaml_doc)) or a round-trip
        # through save/load. The validator must handle ruamel's CommentedMap
        # structure correctly.
        _validate_mutated_config(yaml_doc)

        # 4. Atomic write (temp + rename).
        _atomic_write_ruamel(daemon.config_path, yaml_doc)

        # 5. Refresh live config. (Task 11 implements daemon.refresh_config.)
        daemon.refresh_config()
```

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_daemon_config_mutations.py -v --override-ini="addopts="
```

**Step 5: Commit**

```bash
git add recap/daemon/api_config.py tests/test_daemon_config_mutations.py
git commit -m "feat(#28): _apply_contact_mutations atomic ruamel round-trip"
```

---

## Task 11: `daemon.refresh_config()` + subservice propagation

**Files:**
- Modify: `recap/daemon/service.py` (Daemon class) — add `refresh_config()` method
- Modify: `recap/daemon/recorder/detector.py` — add `on_config_reloaded(new_config)` method
- Create or extend: `tests/test_daemon_service.py`

**Step 1: Write failing tests**

```python
class TestDaemonRefreshConfig:
    """Daemon.refresh_config reloads + propagates to subservices (#28)."""

    def test_refresh_updates_self_config(self, tmp_path):
        """daemon.config reflects on-disk changes after refresh."""
        # Implementer: construct a Daemon with minimal config, write new
        # config to disk, call daemon.refresh_config(), assert new value.
        pass

    def test_refresh_propagates_to_detector(self, tmp_path):
        """MeetingDetector.self._config updated after refresh."""
        pass

    def test_refresh_when_detector_is_none_does_not_raise(self, tmp_path):
        """Before detector is constructed (startup), refresh still works."""
        pass
```

**Step 2: Run tests (fail)**

**Step 3: Implement**

`recap/daemon/service.py` — add to `Daemon` class:

```python
def refresh_config(self) -> None:
    """Reload config from disk and propagate to known subservices.

    Called by _apply_contact_mutations after a successful write.
    Reloads daemon.config from disk and updates any subservice that
    caches a config reference. Explicit known-consumers list (not a
    registry) — add new subservices here when they start caching config.
    """
    from recap.daemon.config import load_daemon_config
    new_config = load_daemon_config(self.config_path)
    self.config = new_config
    if self.detector is not None:
        self.detector.on_config_reloaded(new_config)
    # Add other consumers here as they emerge (CalendarSyncScheduler, etc.).
```

`recap/daemon/recorder/detector.py` — add to `MeetingDetector` class:

```python
def on_config_reloaded(self, new_config: "DaemonConfig") -> None:
    """Update cached config reference after daemon.refresh_config().
    Called by Daemon.refresh_config() when known_contacts or other
    live-editable config changes."""
    self._config = new_config
```

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_daemon_service.py tests/test_detector.py -v --override-ini="addopts="
```

**Step 5: Audit other cached-config holders**

Grep for `self._config = ` and `self.config = ` outside Daemon and MeetingDetector. Candidates:
- `CalendarSyncScheduler` (if it caches)
- Any subservice in `daemon/calendar/` with cached config
- Any subservice in `daemon/recorder/` with cached config

For each, decide: does it need `on_config_reloaded`? If yes, add it. If it always reads fresh from `daemon.config`, leave alone.

Document audit results as a brief comment near `Daemon.refresh_config`.

**Step 6: Commit**

```bash
git add recap/daemon/service.py recap/daemon/recorder/detector.py tests/test_daemon_service.py
git commit -m "feat(#28): daemon.refresh_config + subservice propagation"
```

---

## Task 12: `_ensure_people_stub`

**Files:**
- Modify: `recap/daemon/server.py` (or a shared helper module — pick one)
- Create: `tests/test_vault_people_stub.py`

**Step 1: Write failing tests**

```python
"""Tests for _ensure_people_stub daemon helper (#28)."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_creates_stub_using_canonical_template(tmp_path):
    """Calls existing _generate_person_stub from recap.vault."""
    from recap.daemon.server import _ensure_people_stub
    daemon = _fake_daemon_with_org(tmp_path, org="test", subfolder="Test")
    _ensure_people_stub(daemon, "test", "Alice")
    stub = tmp_path / "Test" / "People" / "Alice.md"
    assert stub.exists()
    # Canonical template produces more than a bare title.
    content = stub.read_text()
    assert len(content) > len("# Alice\n")


def test_idempotent_no_clobber(tmp_path):
    from recap.daemon.server import _ensure_people_stub
    daemon = _fake_daemon_with_org(tmp_path, org="test", subfolder="Test")
    stub_path = tmp_path / "Test" / "People" / "Alice.md"
    stub_path.parent.mkdir(parents=True)
    stub_path.write_text("# Alice\n\nUser-edited content that must survive.\n")
    _ensure_people_stub(daemon, "test", "Alice")
    assert "User-edited content" in stub_path.read_text()


def test_creates_people_dir_if_missing(tmp_path):
    from recap.daemon.server import _ensure_people_stub
    daemon = _fake_daemon_with_org(tmp_path, org="test", subfolder="Test")
    _ensure_people_stub(daemon, "test", "Alice")
    assert (tmp_path / "Test" / "People" / "Alice.md").exists()


def test_unknown_org_raises(tmp_path):
    from recap.daemon.server import _ensure_people_stub
    daemon = _fake_daemon_with_org(tmp_path, org="test", subfolder="Test")
    with pytest.raises(ValueError):
        _ensure_people_stub(daemon, "bogus-org", "Alice")


def test_sanitizes_filename(tmp_path):
    """Names with slashes/colons get safe_note_title treatment."""
    from recap.daemon.server import _ensure_people_stub
    daemon = _fake_daemon_with_org(tmp_path, org="test", subfolder="Test")
    _ensure_people_stub(daemon, "test", "A/B")
    # safe_note_title should replace the slash. Exact sanitization depends on
    # the existing safe_note_title in recap.artifacts.
    files = list((tmp_path / "Test" / "People").glob("*.md"))
    assert len(files) == 1
    assert "/" not in files[0].name
```

**Step 2: Run tests (fail)**

**Step 3: Implement `_ensure_people_stub`** (in `recap/daemon/server.py` near other helpers, or factor into `recap/daemon/stub_helpers.py`):

```python
from pathlib import Path

from recap.artifacts import safe_note_title
from recap.models import ProfileStub
from recap.vault import _generate_person_stub


def _ensure_people_stub(daemon, org: str, name: str) -> None:
    """Create a People note stub if it doesn't exist.

    Uses the same _generate_person_stub template that the pipeline emits
    via write_profile_stubs. Idempotent: skips if already present.
    """
    org_config = daemon.config.org_by_slug(org)
    if org_config is None:
        raise ValueError(f"unknown org: {org}")
    vault_path = Path(daemon.config.vault_path)
    org_subfolder = org_config.resolve_subfolder(vault_path)
    people_dir = org_subfolder / "People"
    stub_path = people_dir / f"{safe_note_title(name)}.md"
    if stub_path.exists():
        return
    people_dir.mkdir(parents=True, exist_ok=True)
    content = _generate_person_stub(ProfileStub(name=name))
    stub_path.write_text(content, encoding="utf-8")
```

Verify import paths against actual module locations — grep for `_generate_person_stub` and `ProfileStub` and `safe_note_title` before running tests.

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_vault_people_stub.py -v --override-ini="addopts="
```

**Step 5: Commit**

```bash
git add recap/daemon/server.py tests/test_vault_people_stub.py
git commit -m "feat(#28): _ensure_people_stub idempotent canonical-template writer"
```

---

## Task 13: Reprocess pipeline — `effective_participants` ephemeral metadata

**Files:**
- Modify: `recap/pipeline/__init__.py` (reprocess-from-analyze path)
- Create: `tests/test_pipeline_reprocess_participants.py`

**Step 1: Write failing tests**

```python
"""Tests for effective_participants union in reprocess flow (#28)."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from recap.daemon.config import KnownContact
from recap.models import MeetingMetadata, Participant, TranscriptResult, Utterance
from recap.pipeline import _build_effective_participants


def test_union_enrichment_then_correction():
    metadata = MeetingMetadata(
        title="T", date=date(2026, 4, 24),
        participants=[Participant(name="Alice", email="alice@x.com")],
        platform="test",
    )
    transcript = TranscriptResult(utterances=[
        Utterance(speaker_id="SPEAKER_00", speaker="Alice", start=0, end=1, text="x"),
        Utterance(speaker_id="SPEAKER_01", speaker="Bob", start=1, end=2, text="y"),
    ], raw_text="", language="en")
    result = _build_effective_participants(metadata, transcript, known_contacts=[])
    assert [p.name for p in result] == ["Alice", "Bob"]


def test_enrichment_only_when_transcript_has_no_eligible_speakers():
    metadata = MeetingMetadata(
        title="T", date=date(2026, 4, 24),
        participants=[Participant(name="Alice")],
        platform="test",
    )
    transcript = TranscriptResult(utterances=[
        Utterance(speaker_id="SPEAKER_00", speaker="SPEAKER_00", start=0, end=1, text="x"),
    ], raw_text="", language="en")
    result = _build_effective_participants(metadata, transcript, known_contacts=[])
    assert [p.name for p in result] == ["Alice"]


def test_correction_adds_names_not_in_enrichment():
    metadata = MeetingMetadata(
        title="T", date=date(2026, 4, 24),
        participants=[],
        platform="test",
    )
    transcript = TranscriptResult(utterances=[
        Utterance(speaker_id="SPEAKER_00", speaker="Alice", start=0, end=1, text="x"),
    ], raw_text="", language="en")
    result = _build_effective_participants(metadata, transcript, known_contacts=[])
    assert [p.name for p in result] == ["Alice"]


def test_stale_enrichment_stays_alongside_correction():
    """Documented limitation: enrichment's Bob (stale) stays with Alice (corrected)."""
    metadata = MeetingMetadata(
        title="T", date=date(2026, 4, 24),
        participants=[Participant(name="Bob")],
        platform="test",
    )
    transcript = TranscriptResult(utterances=[
        Utterance(speaker_id="SPEAKER_00", speaker="Alice", start=0, end=1, text="x"),
    ], raw_text="", language="en")
    result = _build_effective_participants(metadata, transcript, known_contacts=[])
    assert [p.name for p in result] == ["Bob", "Alice"]


def test_re_canonicalizes_via_aliases():
    """Enrichment has 'Sean M.', known_contacts has Sean Mooney with that alias."""
    metadata = MeetingMetadata(
        title="T", date=date(2026, 4, 24),
        participants=[Participant(name="Sean M.")],
        platform="test",
    )
    transcript = TranscriptResult(utterances=[], raw_text="", language="en")
    result = _build_effective_participants(
        metadata, transcript,
        known_contacts=[KnownContact(
            name="Sean Mooney", display_name="Sean Mooney",
            aliases=["Sean M."],
        )],
    )
    assert [p.name for p in result] == ["Sean Mooney"]


def test_re_canonicalizes_via_email():
    metadata = MeetingMetadata(
        title="T", date=date(2026, 4, 24),
        participants=[Participant(name="Nickname", email="sean@x.com")],
        platform="test",
    )
    transcript = TranscriptResult(utterances=[], raw_text="", language="en")
    result = _build_effective_participants(
        metadata, transcript,
        known_contacts=[KnownContact(
            name="Sean Mooney", display_name="Sean Mooney",
            email="sean@x.com",
        )],
    )
    assert [p.name for p in result] == ["Sean Mooney"]


def test_duplicates_removed_by_name():
    metadata = MeetingMetadata(
        title="T", date=date(2026, 4, 24),
        participants=[Participant(name="Alice"), Participant(name="Alice")],
        platform="test",
    )
    transcript = TranscriptResult(utterances=[
        Utterance(speaker_id="SPEAKER_00", speaker="Alice", start=0, end=1, text="x"),
    ], raw_text="", language="en")
    result = _build_effective_participants(metadata, transcript, known_contacts=[])
    assert [p.name for p in result] == ["Alice"]
```

**Step 2: Run tests (fail)**

**Step 3: Implement in `recap/pipeline/__init__.py`**

```python
from dataclasses import replace

from recap.daemon.recorder.enrichment import match_known_contacts
from recap.identity import _is_eligible_person_label


def _build_effective_participants(
    metadata: MeetingMetadata,
    transcript: TranscriptResult,
    known_contacts: list,
) -> list[Participant]:
    """Return union of re-canonicalized enrichment participants + correction-
    derived display labels from transcript. First-seen order preserved."""
    canonical = match_known_contacts(metadata.participants, known_contacts)

    result: list[Participant] = []
    seen: set[str] = set()
    for p in canonical:
        if p.name not in seen:
            result.append(p)
            seen.add(p.name)
    for u in transcript.utterances:
        if u.speaker in seen:
            continue
        if not _is_eligible_person_label(u.speaker):
            continue
        result.append(Participant(name=u.speaker, email=None))
        seen.add(u.speaker)
    return result
```

Find the reprocess-from-analyze path in `run_pipeline`. After `save_transcript(audio_path, transcript)` (post-mapping application), insert:

```python
# #28: build ephemeral MeetingMetadata with merged effective_participants.
# Sidecar untouched; analyze + export both see corrected identities.
effective_participants = _build_effective_participants(
    metadata, transcript, daemon.config.known_contacts,
)
effective_metadata = replace(metadata, participants=effective_participants)

# Pass effective_metadata into analyze AND write_meeting_note.
```

Update the call sites to pass `effective_metadata` instead of `metadata` to `analyze(...)` and `write_meeting_note(...)`.

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_pipeline_reprocess_participants.py tests/test_pipeline_*.py -v --override-ini="addopts="
```

**Step 5: Commit**

```bash
git add recap/pipeline/__init__.py tests/test_pipeline_reprocess_participants.py
git commit -m "feat(#28): effective_participants ephemeral metadata on reprocess"
```

---

## Task 14: `POST /api/meetings/speakers` amendment

**Files:**
- Modify: `recap/daemon/server.py` (endpoint at [server.py:573-623](recap/daemon/server.py:573))
- Modify: `tests/test_daemon_server.py` (extend)

**Step 1: Write failing tests**

Add `TestApiMeetingSpeakersPost` class to `tests/test_daemon_server.py`:

```python
@pytest.mark.asyncio
class TestApiMeetingSpeakersPost:
    """POST /api/meetings/speakers with stem, legacy recording_path,
    contact_mutations, and stub creation (#28)."""

    async def test_401_without_auth(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post("/api/meetings/speakers", json={})
        assert resp.status == 401

    async def test_400_missing_stem_and_recording_path(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/meetings/speakers",
            json={"mapping": {}},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_404_stem_unresolved(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/meetings/speakers",
            json={"stem": "nonexistent", "mapping": {"SPEAKER_00": "Alice"}},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_200_stem_path_writes_speakers_json(self, daemon_client):
        """New stem-based contract: daemon resolves + writes mapping."""
        # Implementer: seed a recording with a transcript so validate_from_stage passes.
        pass

    async def test_200_legacy_recording_path_still_works(self, daemon_client):
        """Old full-path clients keep working."""
        pass

    async def test_contact_mutations_applied_before_reprocess(self, daemon_client):
        """Contact mutations land in config; refresh happens before trigger."""
        pass

    async def test_stub_created_for_new_contact(self, daemon_client):
        """Create mutation triggers _ensure_people_stub."""
        pass

    async def test_500_on_mutation_validation_error(self, daemon_client):
        """Bad mutation → 500, disk unchanged."""
        pass

    async def test_500_on_stub_creation_failure_contacts_persist(self, daemon_client):
        """Stub create fails after contacts applied: 500, config committed."""
        pass
```

**Note to implementer:** Flesh out each test following existing `test_daemon_server.py` patterns. Use `daemon_client` fixture + `AUTH_TOKEN`. Assert response status, response body, on-disk state.

**Step 2: Run tests (fail)**

**Step 3: Modify the handler in `recap/daemon/server.py:573-623`**

```python
async def _speakers(request: web.Request) -> web.Response:
    """POST /api/meetings/speakers — write .speakers.json, apply contact
    mutations, create People stubs, trigger reprocess from analyze stage.
    """
    daemon: Daemon = request.app["daemon"]
    pipeline_runner = request.app.get(_PIPELINE_KEY)
    if pipeline_runner is None:
        return web.json_response({"error": "pipeline not configured"}, status=503)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return web.json_response({"error": "body must be an object"}, status=400)

    mapping = body.get("mapping")
    if not isinstance(mapping, dict):
        return web.json_response({"error": "missing or invalid 'mapping' field"}, status=400)

    # Resolve audio path: prefer stem, fall back to legacy recording_path.
    from recap.artifacts import resolve_recording_path, speakers_path
    from recap.pipeline import validate_from_stage
    stem = body.get("stem")
    legacy_path = body.get("recording_path")
    if stem:
        audio_path = resolve_recording_path(daemon.config.recordings_path, stem)
        if audio_path is None:
            return web.json_response({"error": "recording not found"}, status=404)
    elif legacy_path:
        audio_path = Path(legacy_path)
    else:
        return web.json_response(
            {"error": "missing 'stem' or 'recording_path'"}, status=400,
        )

    validation_error = validate_from_stage(audio_path, "analyze")
    if validation_error is not None:
        return web.json_response({"error": validation_error}, status=400)

    # Apply contact mutations atomically BEFORE writing speakers.json,
    # so refresh_config runs with the same lock.
    contact_mutations = body.get("contact_mutations") or []
    if not isinstance(contact_mutations, list):
        return web.json_response(
            {"error": "contact_mutations must be a list"}, status=400,
        )
    if contact_mutations:
        try:
            _apply_contact_mutations(daemon, contact_mutations)
        except Exception as e:
            logger.exception("contact mutation failed")
            return web.json_response(
                {"error": f"contact mutation failed: {e}"}, status=500,
            )

    # Create People stubs for any `create` mutations.
    org = body.get("org", "")
    for m in contact_mutations:
        if m.get("action") == "create":
            try:
                _ensure_people_stub(daemon, org, m["name"])
            except Exception as e:
                logger.exception("stub creation failed")
                return web.json_response(
                    {"error": f"stub creation failed: {e}"}, status=500,
                )

    # Write .speakers.json keyed by speaker_id.
    speakers_file = speakers_path(audio_path)
    speakers_file.write_text(json.dumps(mapping, indent=2))
    logger.info("Speaker mapping saved: %s", speakers_file)

    # Trigger reprocess from analyze stage. (Docstring at server.py:576
    # previously said "export"; actual stage is analyze. Fix docstring.)
    asyncio.create_task(trigger(audio_path, org, "analyze"))
    return web.json_response({"status": "processing"})
```

Also fix the function's docstring to say "reprocess from analyze" (not "export").

**Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_daemon_server.py::TestApiMeetingSpeakersPost -v --override-ini="addopts="
```

**Step 5: Commit**

```bash
git add recap/daemon/server.py tests/test_daemon_server.py
git commit -m "feat(#28): POST /api/meetings/speakers with stem + contact mutations + stub"
```

---

## Task 15: Plugin `normalize` + `resolve` pure functions

**Files:**
- Create: `obsidian-recap/src/correction/normalize.ts`
- Create: `obsidian-recap/src/correction/normalize.test.ts`
- Create: `obsidian-recap/src/correction/resolve.ts`
- Create: `obsidian-recap/src/correction/resolve.test.ts`

**Step 1: Implement normalize.ts**

```typescript
// obsidian-recap/src/correction/normalize.ts
// Must match recap/identity.py _normalize() exactly.

const MULTI_WS = /\s+/g;
const STRIP_PUNCT = /[.,]/g;

export function normalize(text: string): string {
    let s = text.trim();
    if (!s) return "";
    s = s.replace(STRIP_PUNCT, "");
    s = s.replace(MULTI_WS, " ");
    return s.toLowerCase().trim();
}
```

**Step 2: Write normalize.test.ts**

```typescript
import {describe, it, expect} from "vitest";
import {normalize} from "./normalize";

describe("normalize", () => {
    it("casefolds", () => expect(normalize("Alice")).toBe("alice"));
    it("strips whitespace", () => expect(normalize("  Alice  ")).toBe("alice"));
    it("collapses internal whitespace",
       () => expect(normalize("Sean  Mooney")).toBe("sean mooney"));
    it("strips periods and commas", () => {
        expect(normalize("Sean M.")).toBe("sean m");
        expect(normalize("J.D.")).toBe("jd");
    });
    it("empty returns empty", () => {
        expect(normalize("")).toBe("");
        expect(normalize("   ")).toBe("");
    });
});
```

**Step 3: Implement resolve.ts**

```typescript
// obsidian-recap/src/correction/resolve.ts
import {normalize} from "./normalize";

export interface KnownContact {
    name: string;
    display_name: string;
    aliases?: string[];
    email?: string | null;
}

export interface Participant {
    name: string;
    email?: string | null;
}

export interface ResolutionContext {
    knownContacts: KnownContact[];
    peopleNames: string[];
    companyNames: string[];
    meetingParticipants: Participant[];
}

export type ResolutionPlan =
    | {kind: "link_to_existing"; canonical_name: string; requires_contact_create: boolean; email?: string}
    | {kind: "create_new_contact"; name: string; email?: string}
    | {kind: "near_match_ambiguous"; suggestion: string; typed: string}
    | {kind: "ineligible"; reason: string; typed: string};

const SPEAKER_ID_RE = /^SPEAKER_\d+$/;
const UNKNOWN_RE = /^(UNKNOWN|Unknown Speaker.*)$/i;
const PARENTHETICAL_RE = /\([^)]+\)/;

export function resolve(typed: string, ctx: ResolutionContext): ResolutionPlan {
    const normalized = normalize(typed);
    if (!normalized) return {kind: "ineligible", reason: "empty", typed};

    const linked = tryMatches(typed, normalized, ctx);
    if (linked) return linked;

    const stripped = typed.replace(PARENTHETICAL_RE, "").trim();
    if (stripped !== typed && normalize(stripped)) {
        const retried = tryMatches(stripped, normalize(stripped), ctx);
        if (retried) return retried;
    }

    const near = findNearMatch(normalized, ctx);
    if (near) return {kind: "near_match_ambiguous", suggestion: near, typed};

    const ineligibility = checkIneligibility(typed, normalized, ctx);
    if (ineligibility) return ineligibility;

    const participant = ctx.meetingParticipants.find(
        p => normalize(p.name) === normalized && p.email,
    );
    return {kind: "create_new_contact", name: typed, email: participant?.email ?? undefined};
}

function tryMatches(typed: string, normalized: string, ctx: ResolutionContext): ResolutionPlan | null {
    // (a) Email-first
    const participant = ctx.meetingParticipants.find(
        p => normalize(p.name) === normalized && p.email,
    );
    if (participant?.email) {
        const byEmail = ctx.knownContacts.find(
            c => c.email?.toLowerCase() === participant.email!.toLowerCase(),
        );
        if (byEmail) return {
            kind: "link_to_existing",
            canonical_name: byEmail.name,
            requires_contact_create: false,
        };
    }

    // (b) Exact known_contact match
    for (const c of ctx.knownContacts) {
        const candidates = [c.name, c.display_name, ...(c.aliases || [])];
        for (const cand of candidates) {
            if (cand && normalize(cand) === normalized) {
                return {
                    kind: "link_to_existing",
                    canonical_name: c.name,
                    requires_contact_create: false,
                };
            }
        }
    }

    // (c) Exact People note basename match
    const peopleMatch = ctx.peopleNames.find(n => normalize(n) === normalized);
    if (peopleMatch) {
        return {
            kind: "link_to_existing",
            canonical_name: peopleMatch,
            requires_contact_create: true,
            email: participant?.email ?? undefined,
        };
    }
    return null;
}

function findNearMatch(normalizedTyped: string, ctx: ResolutionContext): string | null {
    const typedTokens = normalizedTyped.split(" ").filter(Boolean);
    if (typedTokens.length === 0) return null;

    const candidates: Array<{canonical: string; names: string[]}> = [
        ...ctx.knownContacts.map(c => ({
            canonical: c.name,
            names: [c.name, c.display_name, ...(c.aliases || [])].filter(Boolean) as string[],
        })),
        ...ctx.peopleNames.map(n => ({canonical: n, names: [n]})),
    ];

    for (const cand of candidates) {
        for (const candName of cand.names) {
            if (initialAwareMatch(typedTokens, normalize(candName).split(" ").filter(Boolean))) {
                return cand.canonical;
            }
        }
    }
    return null;
}

function initialAwareMatch(typed: string[], candidate: string[]): boolean {
    if (typed.length === 0 || candidate.length === 0) return false;
    if (typed[0] !== candidate[0]) return false;  // first token must match exactly
    if (typed.length > candidate.length) return false;  // typed can't have more tokens
    if (typed.length === candidate.length && typed.every((t, i) => t === candidate[i])) {
        return false;  // exact match is handled upstream; don't suggest it as near
    }
    for (let i = 1; i < typed.length; i++) {
        const t = typed[i];
        const c = candidate[i];
        if (t === c) continue;
        if (t.length === 1 && c.startsWith(t)) continue;  // initial match
        return false;
    }
    return true;
}

function checkIneligibility(typed: string, normalized: string, ctx: ResolutionContext): ResolutionPlan | null {
    const s = typed.trim();
    if (!s) return {kind: "ineligible", reason: "empty", typed};
    if (SPEAKER_ID_RE.test(s)) return {kind: "ineligible", reason: "SPEAKER_XX", typed};
    if (UNKNOWN_RE.test(s)) return {kind: "ineligible", reason: "Unknown Speaker", typed};
    if (PARENTHETICAL_RE.test(s)) return {kind: "ineligible", reason: "parenthetical", typed};
    if (s.includes("/")) return {kind: "ineligible", reason: "multi-person (contains /)", typed};
    if (ctx.companyNames.some(c => normalize(c) === normalized)) {
        return {kind: "ineligible", reason: "matches Company note", typed};
    }
    return null;
}
```

**Step 4: Write resolve.test.ts**

```typescript
import {describe, it, expect} from "vitest";
import {resolve, ResolutionContext} from "./resolve";

const emptyCtx: ResolutionContext = {
    knownContacts: [], peopleNames: [], companyNames: [], meetingParticipants: [],
};

describe("resolve", () => {
    it("empty typed → ineligible", () => {
        expect(resolve("", emptyCtx).kind).toBe("ineligible");
    });

    it("exact match on known_contact name", () => {
        const r = resolve("Alice", {
            ...emptyCtx,
            knownContacts: [{name: "Alice", display_name: "Alice"}],
        });
        expect(r).toEqual({kind: "link_to_existing", canonical_name: "Alice", requires_contact_create: false});
    });

    it("exact match on alias returns canonical name", () => {
        const r = resolve("Sean M.", {
            ...emptyCtx,
            knownContacts: [{
                name: "Sean Mooney", display_name: "Sean Mooney",
                aliases: ["Sean M."],
            }],
        });
        expect(r).toMatchObject({kind: "link_to_existing", canonical_name: "Sean Mooney"});
    });

    it("near-match initial-aware: 'Sean M.' → Sean Mooney suggestion", () => {
        const r = resolve("Sean M.", {
            ...emptyCtx,
            knownContacts: [{name: "Sean Mooney", display_name: "Sean Mooney"}],
        });
        expect(r.kind).toBe("near_match_ambiguous");
        if (r.kind === "near_match_ambiguous") {
            expect(r.suggestion).toBe("Sean Mooney");
        }
    });

    it("different first token rejects near-match", () => {
        const r = resolve("Sena", {
            ...emptyCtx,
            knownContacts: [{name: "Sean Mooney", display_name: "Sean Mooney"}],
        });
        expect(r.kind).not.toBe("near_match_ambiguous");
    });

    it("parenthetical strip-and-retry links to Sean", () => {
        const r = resolve("Sean (dev team)", {
            ...emptyCtx,
            knownContacts: [{name: "Sean", display_name: "Sean"}],
        });
        expect(r).toMatchObject({kind: "link_to_existing", canonical_name: "Sean"});
    });

    it("ineligible: SPEAKER_00", () => {
        expect(resolve("SPEAKER_00", emptyCtx).kind).toBe("ineligible");
    });

    it("ineligible: Unknown Speaker 1", () => {
        expect(resolve("Unknown Speaker 1", emptyCtx).kind).toBe("ineligible");
    });

    it("ineligible: company collision", () => {
        const r = resolve("DisburseCloud", {
            ...emptyCtx,
            companyNames: ["DisburseCloud"],
        });
        expect(r.kind).toBe("ineligible");
    });

    it("ineligible: multi-person form", () => {
        expect(resolve("Ed/Ellen", emptyCtx).kind).toBe("ineligible");
    });

    it("People-note-only match: requires_contact_create=true", () => {
        const r = resolve("Alice", {
            ...emptyCtx,
            peopleNames: ["Alice"],
        });
        expect(r).toEqual({
            kind: "link_to_existing",
            canonical_name: "Alice",
            requires_contact_create: true,
            email: undefined,
        });
    });

    it("email-first precedence", () => {
        const r = resolve("Nickname", {
            ...emptyCtx,
            knownContacts: [{name: "Sean Mooney", display_name: "Sean Mooney", email: "sean@x.com"}],
            meetingParticipants: [{name: "Nickname", email: "sean@x.com"}],
        });
        expect(r).toMatchObject({kind: "link_to_existing", canonical_name: "Sean Mooney"});
    });

    it("create new when nothing matches and eligible", () => {
        const r = resolve("Brand New Person", emptyCtx);
        expect(r.kind).toBe("create_new_contact");
    });
});
```

**Step 5: Run tests**

```bash
cd obsidian-recap && npm test
```

Expected: all normalize + resolve tests pass.

**Step 6: Commit**

```bash
cd C:\Users\tim\OneDrive\Documents\Projects\recap
git add obsidian-recap/src/correction/
git commit -m "feat(#28): client-side normalize + resolve pure functions + Vitest tests"
```

---

## Task 16: Plugin `DaemonClient` additions

**Files:**
- Modify: `obsidian-recap/src/api.ts` (`DaemonClient` at [api.ts:89](obsidian-recap/src/api.ts:89))

**Context:** `DaemonClient` already exposes `get<T>(path)`, `post<T>(path, body?)`, and `delete(path)` ([api.ts:103-136](obsidian-recap/src/api.ts:103)). Each handles auth headers + error wrapping. New methods use those — **do not introduce a new `fetch` helper**.

**Step 1: Add methods to DaemonClient**

```typescript
async getMeetingSpeakers(stem: string): Promise<{
    speakers: Array<{speaker_id: string; display: string}>;
    participants: Array<{name: string; email: string | null}>;
}> {
    return this.get(`/api/meetings/${encodeURIComponent(stem)}/speakers`);
}

async saveSpeakerCorrections(params: {
    stem: string;
    mapping: Record<string, string>;
    contact_mutations: Array<
        | {action: "create"; name: string; display_name: string; email?: string}
        | {action: "add_alias"; name: string; alias: string}
    >;
    org: string;
}): Promise<{status: string}> {
    return this.post("/api/meetings/speakers", params);
}
```

**Note:** the GET response shape now includes `participants` with optional emails — this is a Task 7 contract extension (see Task 7 patch below). The extended response gives the client what it needs for email-first resolution without a separate endpoint.

**Step 2: Update clip fetch**

Grep for `/api/recordings/` in plugin code (likely `SpeakerCorrectionModal.ts::loadClipInto` or similar). Change query param from `speaker=...` to `speaker_id=...`. The daemon accepts both during the transition (Task 9), so this change is non-breaking.

**Step 3: Verify build**

```bash
cd obsidian-recap && npm run build && npm test
```

Expected: clean build, all Vitest tests pass.

**Step 4: Commit**

```bash
git add obsidian-recap/src/
git commit -m "feat(#28): DaemonClient getMeetingSpeakers + saveSpeakerCorrections + clip speaker_id"
```

---

## Task 17: Plugin modal rewrite

**Files:**
- Modify: `obsidian-recap/src/main.ts` (openSpeakerCorrection at line 295+)
- Modify: `obsidian-recap/src/views/SpeakerCorrectionModal.ts` (widen constructor + integrate resolve)

**Step 1: Modify `openSpeakerCorrection`** — replace note-body regex scan with daemon fetch. Frontmatter's `recording` field is a basename WITH extension (e.g., `2026-04-22-120530-disbursecloud.m4a` from [vault.py:119](recap/vault.py:119)'s `recording_path.name`). Strip the audio extension to get a bare stem for the daemon's path resolver.

```typescript
private async openSpeakerCorrection(file: TFile): Promise<void> {
    if (!this.client) { new Notice("Daemon not connected"); return; }

    const cache = this.app.metadataCache.getFileCache(file);
    const fm = cache?.frontmatter;
    const recording = (fm?.recording ?? "").toString().replace(/\[\[|\]\]/g, "");
    // Daemon's resolve_recording_path takes a bare stem, not a filename;
    // strip the .flac/.m4a extension. Matches the FLAC->M4A ladder in
    // recap/artifacts.py::resolve_recording_path.
    const stem = recording.replace(/\.(flac|m4a)$/i, "");
    const org = fm?.org || "";
    const orgSubfolder = fm?.["org-subfolder"] || "";
    if (!stem) { new Notice("No recording in frontmatter"); return; }
    if (!orgSubfolder) { new Notice("Missing org-subfolder in frontmatter"); return; }

    // Daemon returns BOTH speakers (from transcript) AND participants
    // (from recording metadata sidecar, with emails for calendar-sourced entries).
    let resp: {speakers: Array<{speaker_id: string; display: string}>; participants: Array<{name: string; email: string | null}>};
    try {
        resp = await this.client.getMeetingSpeakers(stem);
    } catch (e) {
        new Notice(`Could not load speakers: ${e}`);
        return;
    }
    if (resp.speakers.length === 0) {
        new Notice("No speakers in transcript");
        return;
    }

    const peopleNames = this.scanNotesByFolder(`${orgSubfolder}/People`);
    const companyNames = this.scanNotesByFolder(`${orgSubfolder}/Companies`);
    let knownContacts: any[] = [];
    try {
        const cfg = await this.client.getConfig();
        knownContacts = cfg.known_contacts || [];
    } catch (e) {
        console.warn("Could not load known contacts", e);
    }

    // Participants come from daemon (with emails), not frontmatter.
    // Frontmatter's participants field only has wikilinked names.
    const meetingParticipants = resp.participants.map(p => ({
        name: p.name,
        email: p.email ?? undefined,
    }));

    new SpeakerCorrectionModal(
        this.app, resp.speakers, peopleNames, companyNames, knownContacts,
        meetingParticipants, stem, org, orgSubfolder, this.client,
    ).open();
}

private scanNotesByFolder(folderPath: string): string[] {
    const prefix = folderPath.endsWith("/") ? folderPath : `${folderPath}/`;
    return this.app.vault.getMarkdownFiles()
        .filter(f => f.path.startsWith(prefix))
        .map(f => f.basename);
}
```

The `loadParticipantsFromFrontmatter` helper from the earlier draft is deleted — daemon-provided participants supersede it, and it couldn't carry emails anyway.

**Step 2: Widen `SpeakerCorrectionModal`**

Update constructor signature to accept the new inputs. Replace the existing speaker-list rendering with one row per speaker from the `speakers` array. Integrate `resolve()` into per-row input-change handlers. Compute resolution plan on input/blur; update inline hint UI accordingly.

Implementer: follow the existing modal's code organization. Key additions:
- Per-row state: `typedName`, `currentPlan: ResolutionPlan`
- Per-row hint element that re-renders based on `plan.kind`
- Near-match `[Use existing] [Create new anyway]` buttons that rewrite the row's plan on click
- Save button disabled if any row's plan is `ineligible` or `near_match_ambiguous`
- Save submit: build mapping + contact_mutations per the design doc's Section 4.5

Save handler:

```typescript
async onSubmit(): Promise<void> {
    const plans: ResolutionPlan[] = this.rows.map(r => r.currentPlan);
    if (plans.some(p => p.kind === "ineligible" || p.kind === "near_match_ambiguous")) {
        new Notice("Some rows need resolution before save");
        return;
    }

    const mapping: Record<string, string> = {};
    const contact_mutations: any[] = [];
    for (let i = 0; i < this.rows.length; i++) {
        const row = this.rows[i];
        const plan = plans[i];
        if (plan.kind === "link_to_existing") {
            mapping[row.speaker_id] = plan.canonical_name;
            if (plan.requires_contact_create) {
                contact_mutations.push({
                    action: "create",
                    name: plan.canonical_name,
                    display_name: plan.canonical_name,
                    email: plan.email,
                });
            } else if (normalize(row.typedName) !== normalize(plan.canonical_name)) {
                contact_mutations.push({
                    action: "add_alias",
                    name: plan.canonical_name,
                    alias: row.typedName,
                });
            }
        } else if (plan.kind === "create_new_contact") {
            mapping[row.speaker_id] = plan.name;
            contact_mutations.push({
                action: "create",
                name: plan.name,
                display_name: plan.name,
                email: plan.email,
            });
        }
    }

    try {
        await this.client.saveSpeakerCorrections({
            stem: this.stem, mapping, contact_mutations, org: this.org,
        });
    } catch (e) {
        new Notice(`Recap: submit failed — ${e}`);
        return;
    }
    new Notice("Speaker corrections submitted — reprocessing...");
    this.close();
}
```

**Step 3: Verify build + vitest**

```bash
cd obsidian-recap && npm run build && npm test
```

Expected: clean build, all tests pass.

**Step 4: Commit**

```bash
cd C:\Users\tim\OneDrive\Documents\Projects\recap
git add obsidian-recap/src/
git commit -m "feat(#28): plugin modal rewrite — any-speaker, resolution engine, save"
```

---

## Task 18: Integration E2E test

**Files:**
- Create: `tests/test_speaker_correction_integration.py`

**Step 1: Write E2E scenarios**

```python
"""End-to-end #28 scenarios.

Combines: plugin POST (simulated) → daemon write → reprocess stub →
frontmatter refresh (simulated). Stubs the LLM / Claude CLI calls.
"""
from __future__ import annotations

import pytest

# Implementer: study tests/test_unscheduled_enrichment_integration.py for the
# harness pattern. Key fixtures: real detector + real recorder + stubbed
# audio capture. For reprocess: stub analyze (no Claude call) but let
# _apply_speaker_mapping + _build_effective_participants run for real.


@pytest.mark.asyncio
async def test_correct_unresolved_speaker_creates_contact_and_refreshes(
    tmp_path, monkeypatch,
):
    """AC #1, #3, #4: unresolved SPEAKER_00 → Alice with new contact +
    People stub + frontmatter reflects Alice after reprocess."""
    # 1. Seed a meeting with transcript containing SPEAKER_00.
    # 2. Simulate POST /api/meetings/speakers with create mutation.
    # 3. Verify .speakers.json written.
    # 4. Verify known_contacts updated.
    # 5. Verify People stub created.
    # 6. Run reprocess (stubbed analyze).
    # 7. Assert participants frontmatter contains Alice.


@pytest.mark.asyncio
async def test_already_named_speaker_corrected_still_clips_playable(tmp_path):
    """AC #6: correct a named speaker to a different name; clip still
    resolves via speaker_id."""
    pass


@pytest.mark.asyncio
async def test_near_match_accept_adds_alias(tmp_path):
    """Sean M. → Sean Mooney near-match accepted; alias persists."""
    pass


@pytest.mark.asyncio
async def test_legacy_speakers_json_replayed_as_no_op(tmp_path):
    """Pre-#28 .speakers.json keyed by display label silently no-ops.
    First post-#28 correction rewrites keyed by speaker_id."""
    pass
```

**Note to implementer:** each test body is substantial (~30-50 lines). Factor shared setup into helper functions. Model on `tests/test_unscheduled_enrichment_integration.py` — same harness pattern.

**Step 2: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_speaker_correction_integration.py -v --override-ini="addopts="
```

**Step 3: Commit**

```bash
git add tests/test_speaker_correction_integration.py
git commit -m "test(#28): integration E2E — correction round-trip scenarios"
```

---

## Task 19: MANIFEST + acceptance checklist + docstring fix

**Files:**
- Modify: `MANIFEST.md` (add Key Relationships bullet for #28)
- Create: `docs/handoffs/2026-04-24-28-acceptance.md`
- Modify: `recap/daemon/server.py:576` docstring (already fixed in Task 14; verify)

**Step 1: MANIFEST.md update**

Add after the #29 bullet:

```markdown
- **Speaker correction + identity model (#28):** `Utterance.speaker_id` is
  immutable (diarized identity); `Utterance.speaker` is the mutable display
  label rewritten by `_apply_speaker_mapping` keyed on `speaker_id`. Clip
  lookup + cache filename key on `speaker_id` so rewrites don't break playback.
  `KnownContact` gains `aliases: list[str]` + `email: str | None`;
  `match_known_contacts` matches email-first, then alias-aware normalized name.
  `resolve_recording_path(stem) -> Path | None` shared helper (FLAC→M4A
  precedence) used by both `/api/meetings/{stem}/speakers` (new) and clip
  endpoint. Correction save (`POST /api/meetings/speakers`) atomically
  writes `.speakers.json`, applies contact mutations via ruamel round-trip,
  calls `daemon.refresh_config()` to propagate to subservices, creates
  People stubs via existing `_generate_person_stub`, and triggers reprocess.
  Reprocess builds ephemeral `effective_participants` (re-canonicalized
  enrichment ∪ correction-derived speakers, eligibility-filtered) and
  feeds both analyze + export. First-pass auto-relabel runs between
  diarize and analyze on Case A only (1 speaker_id + 1 eligible participant).
  Client-side resolution engine (8-step precedence) lives at
  `obsidian-recap/src/correction/resolve.ts` with Vitest coverage.
  Duplicate merge/remediation deferred to #37.
```

**Step 2: Write acceptance checklist**

Create `docs/handoffs/2026-04-24-28-acceptance.md` (ASCII-only, 15 scenarios).

Use plain `--`, `->`, no em-dashes. Scenarios per design Section 7.2:
1. Fresh test vault reset
2. First-pass auto-relabel happy path
3. Case A doesn't hold
4. Correct unresolved SPEAKER
5. Correct already-named
6. Near-match accept
7. Near-match decline + create
8. Ineligible: SPEAKER_00
9. Ineligible: company collision
10. Parenthetical strip-and-retry
11. Daemon creates canonical stub
12. Contact mutation persists
13. Daemon restart survival
14. Live config refresh (no restart)
15. Legacy transcript migration

**Step 3: Verify server docstring fix**

Grep for "reprocess from export" in `recap/daemon/server.py`. If still present, change to "reprocess from analyze".

**Step 4: Commit**

```bash
git add MANIFEST.md docs/handoffs/2026-04-24-28-acceptance.md recap/daemon/server.py
git commit -m "docs(#28): MANIFEST + acceptance checklist + server docstring typo fix"
```

---

## Task 20: Final verification

**Step 1: Full test suite**

```bash
.venv/Scripts/python -m pytest tests/ --override-ini="addopts=" 2>&1 | tail -10
```

Expected: all #28-touched tests pass; no new regressions. The 1 pre-existing `tests/integration/test_ml_pipeline.py` failure from #29 may still be present — verify it's unchanged.

**Step 2: Plugin build + test**

```bash
cd obsidian-recap && npm run build && npm test && cd ..
```

Expected: clean build, all Vitest tests pass.

**Step 3: Commit counts verification**

```bash
git log --oneline master..HEAD | wc -l
```

Expected: ~20-22 commits (one per task, plus design + plan).

**Step 4: Lint / type check**

```bash
# If configured:
.venv/Scripts/python -m ruff check recap/ tests/  # or whatever lint is set up
cd obsidian-recap && npx tsc --noEmit  # type check
```

**Step 5: Manual acceptance spot-check**

Run scenarios 2 + 4 + 11 from `docs/handoffs/2026-04-24-28-acceptance.md` against a real test vault. Other scenarios can happen in PR review.

**Step 6: Handoff**

Use `superpowers:finishing-a-development-branch` to pick: merge locally / push + PR / keep as-is / discard.

---

## Implementation notes

- **TDD throughout**: every task starts red, goes green, commits.
- **YAGNI**: no `chrome.scripting` dynamic registration, no proposal data type, no company alias learning (all deferred).
- **Client/daemon eligibility split**: daemon-level `_is_eligible_person_label` is narrow (SPEAKER_*, UNKNOWN*, parenthetical, empty); plugin adds Company-collision + multi-person guards that need vault scan.
- **Merge-friendly invariants (for #37)**: correction always writes canonical name, never alias. No identity from note body text. Aliases don't leak into note bodies.
- **Test vault prep** before manual acceptance: reset from fresh copy, clear `*.speakers.json`, regenerate transcripts for retested meetings, remove junk People stubs.
- **Codex review recommended between Tasks 5, 10, 13, 14** — these have the highest potential for subtle regression (enrichment signature change, ruamel atomicity, reprocess flow, POST contract).
- **Skip Task 17's UI testing** beyond type checks — cover via manual acceptance.

## References

- Design: [docs/plans/2026-04-24-28-speaker-correction-design.md](docs/plans/2026-04-24-28-speaker-correction-design.md)
- Issue: [#28](https://github.com/TimSimpsonJr/recap/issues/28)
- Follow-up: [#37](https://github.com/TimSimpsonJr/recap/issues/37) (duplicate merge)
- Prerequisite (merged): #29 / PR #36 (enrichment pipeline)
