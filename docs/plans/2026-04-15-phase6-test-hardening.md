# Phase 6: Test Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace mock-only tests that prove "the mock is wired up" with real integration tests that prove "the contract holds end-to-end" — pipeline outputs land in the vault, Signal backend routing actually invokes the right subprocess, EventIndex survives corruption, extension auth is enforced on the post-Phase-4 protocol — and gate the suite at ≥70% coverage over `recap/`.

**Architecture:** Two-stage approach. (1) Add new high-value integration tests against real tmp vaults / real EventIndex / real auth middleware so coverage rises before any cuts. (2) Audit existing over-mocked tests and either rewrite to use real outputs or delete; then enable the coverage gate. ML stages (transcribe/diarize/analyze) stay mocked because running them needs a GPU — but everything around them runs against the real implementations.

**Tech Stack:** Python 3.10+, pytest, pytest-asyncio, pytest-aiohttp (existing), `pytest-cov` (new), aiohttp test client, ffmpeg (already used by Phase 4 clip endpoint test for fixture-audio generation; reuse).

**Read before starting:**
- `docs/plans/2026-04-14-fix-everything-design.md` §Phase 6 (lines 385-413) — parent design; acceptance criteria are load-bearing.
- `docs/plans/2026-04-15-phase5-honesty-pass.md` — Phase 5 ended at commit `7b1c49c` with 552 passed + 3 skipped, plugin build clean.
- `tests/test_pipeline.py` — note the comment around line 106: "ML stages (transcribe/diarize/analyze) stay mocked because running them needs a GPU." That's correct and stays. The over-mocking concern is on the WRITE side (vault, artifacts, index) and on `subprocess` dispatch.

**Baseline commit:** `7b1c49c`. Test suite at 552 passing + 3 skipped.

---

## Conventions for every task

- Commit style: Conventional Commits (`test:`, `feat:`, `chore:`, `refactor:`, `docs:`).
- Never stage `uv.lock` or `docs/reviews/`.
- Run `uv run pytest -q` at the end of every task. Net pass/fail count must be reported.
- Plugin TS changes are NOT expected in Phase 6. If you touch `obsidian-recap/`, pause and ask.
- Tests for new Python modules live in `tests/` mirroring the source path (`tests/test_e2e_pipeline.py`, `tests/test_signal_backend_routing.py`, `tests/test_extension_auth.py`).
- Mock at the system boundary (subprocess, ML model load), not at the integration boundary (vault writer, EventIndex, EventJournal). If a test patches `write_meeting_note` / `upsert_note` / `save_*` / `EventIndex.add`, that's the exact pattern Phase 6 targets.
- Coverage measurement uses `pytest-cov`. Do not fail the suite on coverage until Task 8 explicitly enables the gate.

---

## Task 1: Add `pytest-cov`; record coverage baseline; reserve threshold for Task 8

**Context:** Phase 6 ends with `--cov-fail-under=70` gating the suite. We need to know the current coverage number before deciding whether tasks 2-5 close the gap or whether tasks 6-7's deletions tighten it. Adding the dep and a non-failing baseline measurement now keeps the rest of the phase honest.

**Files:**
- Modify: `pyproject.toml` (add `pytest-cov` to `[project.optional-dependencies.dev]`)
- Modify: `pyproject.toml` (`[tool.pytest.ini_options]` — leave existing `testpaths`; do NOT add `addopts` for coverage yet)
- Create: `docs/handoffs/2026-04-15-phase6-coverage-baseline.md` (one-paragraph note recording the baseline percentage and per-module breakdown)

**Step 1: Add the dep**

In `pyproject.toml`, under `[project.optional-dependencies].dev`, append `"pytest-cov>=5.0"`.

```bash
uv sync --extra dev
uv run python -c "import pytest_cov; print(pytest_cov.__version__)"
```

Expected: prints a version ≥ 5.0.

**Step 2: Measure baseline (don't gate yet)**

Run:

```bash
uv run pytest --cov=recap --cov-report=term-missing --cov-report=html -q 2>&1 | tail -40
```

Capture the total `TOTAL` line and the per-module table. Save the summary to `docs/handoffs/2026-04-15-phase6-coverage-baseline.md`:

```markdown
# Phase 6 coverage baseline

**Date:** 2026-04-15
**Branch:** obsidian-pivot
**Commit at measurement:** <git rev-parse HEAD>

**Total coverage over `recap/`:** XX.X%

**Per-module breakdown** (top 10 lowest):
- `recap/daemon/...` -- XX%
- ...

**Notes:**
- Phase 6 target: 70%. Gap: <delta>.
- Modules likely raised by Tasks 2-5: <list>.
- Modules where coverage may drop after Tasks 6-7 deletions: <list>.
```

The HTML report ends up in `htmlcov/`; add that directory to `.gitignore` if not already present.

**Step 3: `.gitignore` housekeeping**

```bash
grep -n "htmlcov\|\.coverage" .gitignore
```

If missing, append:

```
htmlcov/
.coverage
.coverage.*
```

**Step 4: Run pytest one more time to confirm no regression**

```bash
uv run pytest -q
```

Expected: 552 passed, 3 skipped (baseline match — `pytest-cov` adds a flag, not behavior).

**Step 5: Commit**

Do NOT stage `uv.lock`. Do stage `pyproject.toml`, `.gitignore` (if changed), and the new handoff doc.

```bash
git add pyproject.toml .gitignore docs/handoffs/2026-04-15-phase6-coverage-baseline.md
git commit -m "chore: add pytest-cov; record Phase 6 coverage baseline"
```

---

## Task 2: New `tests/test_e2e_pipeline.py` — real vault, real file outputs

**Context:** This is the load-bearing E2E test the parent design specifies (`§397`): "fixture-audio → run_pipeline → assert canonical frontmatter fully present, body has summary/key-points/action-items, recording-index updated, event-journal has `pipeline_completed` entry." ML stages stay mocked (no GPU); everything else runs for real.

**Files:**
- Create: `tests/test_e2e_pipeline.py`

**Step 1: Identify the real `run_pipeline` entry point + canonical frontmatter shape**

Skim `recap/pipeline/__init__.py` for the public `run_pipeline` (or whichever async function the daemon calls into post-recording). Identify:
- Inputs: audio path, metadata, runtime config.
- Outputs: note path, status side effects.
- The exact set of frontmatter keys `vault.build_canonical_frontmatter` emits (search `recap/vault.py` for the canonical key list).

If the `pipeline_completed` event name differs (some Phase 3 code uses `pipeline_complete` or similar), use what the journal actually emits — read `recap/pipeline/__init__.py` for the `emit_event` calls.

**Step 2: Write the test scaffolding**

```python
"""End-to-end pipeline test (Phase 6 Task 2).

Mocks ML stages only (transcribe / diarize / analyze) — everything
between them runs for real: the vault writer, artifacts sidecars,
EventIndex updates, and EventJournal events. Validates the contract
the daemon depends on after a recording finishes.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
from unittest.mock import patch

import pytest


def _make_silent_flac(path: pathlib.Path, seconds: int = 10) -> None:
    """Generate a 10s silent FLAC via ffmpeg so the pipeline has a real audio file."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=mono:sample_rate=16000",
            "-t", str(seconds),
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def vault_path(tmp_path: pathlib.Path) -> pathlib.Path:
    """Fresh tmp vault with the Recap subfolder skeleton the pipeline expects."""
    vault = tmp_path / "vault"
    (vault / "_Recap" / ".recap").mkdir(parents=True)
    (vault / "Clients" / "Alpha" / "Meetings").mkdir(parents=True)
    (vault / "Clients" / "Alpha" / "People").mkdir(parents=True)
    return vault


@pytest.fixture
def recordings_path(tmp_path: pathlib.Path) -> pathlib.Path:
    rec = tmp_path / "recordings"
    rec.mkdir()
    return rec


# ... continued in Step 3
```

**Step 3: Write the actual end-to-end test**

```python
@pytest.mark.skipif(
    __import__("shutil").which("ffmpeg") is None, reason="ffmpeg required",
)
def test_run_pipeline_writes_full_meeting_note(
    vault_path, recordings_path,
):
    from recap.models import (
        AnalysisResult, MeetingMetadata, TranscriptResult,
    )
    from recap.artifacts import RecordingMetadata, write_recording_metadata
    from recap.pipeline import run_pipeline  # adjust if the entry is named differently
    from recap.daemon.runtime_config import build_runtime_config_for_test  # if it exists; otherwise build inline
    # If build_runtime_config_for_test does not exist, build a PipelineRuntimeConfig
    # by hand using the same shape recap/daemon/runtime_config.py uses.

    audio_path = recordings_path / "2026-04-15-100000-alpha.flac"
    _make_silent_flac(audio_path)

    rec_meta = RecordingMetadata(
        recording_id="2026-04-15-100000-alpha",
        org="alpha",
        platform="meet",
        title="Sprint planning",
        participants=[],
        started_at="2026-04-15T10:00:00-04:00",
        llm_backend="claude",
        note_path=None,
    )
    write_recording_metadata(audio_path, rec_meta)

    transcript = TranscriptResult(
        utterances=[
            {"speaker": "Alex", "start": 1.0, "end": 4.0,
             "text": "Welcome to sprint planning."},
            {"speaker": "Bri", "start": 4.5, "end": 7.0,
             "text": "Let's start with the priorities."},
        ],
        segments=[],
    )
    analysis = AnalysisResult(
        summary="Sprint planning kicked off; Alex and Bri aligned on priorities.",
        key_points=["Aligned on priorities"],
        action_items=[{"who": "Alex", "what": "draft priorities doc"}],
        decisions=[],
        questions=[],
    )

    # Mock at system boundaries: ML inference + ffmpeg conversion.
    # Vault writer, artifacts, EventIndex, EventJournal all run for real.
    with (
        patch("recap.pipeline.transcribe.run", return_value=transcript),
        patch("recap.pipeline.diarize.run", return_value=[
            {"speaker": "Alex", "start": 1.0, "end": 4.0},
            {"speaker": "Bri", "start": 4.5, "end": 7.0},
        ]),
        patch("recap.analyze.analyze_meeting", return_value=analysis),
        patch(
            "recap.pipeline.audio_convert.convert_flac_to_aac",
            return_value=audio_path.with_suffix(".m4a"),
        ),
        # If the pipeline emits to a journal, wire one up; otherwise let it no-op.
    ):
        # Build a minimal PipelineRuntimeConfig that points at vault_path
        # and uses Claude backend. The exact constructor lives in
        # recap/daemon/runtime_config.py — read it once and replicate
        # the field set here.
        config = ...  # see runtime_config.py
        note_path = run_pipeline(
            audio_path=audio_path,
            metadata=rec_meta,
            config=config,
        )

    # ---- Frontmatter contract ----
    text = note_path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    fm_block = text.split("---\n", 2)[1]
    import yaml
    fm = yaml.safe_load(fm_block)
    expected_keys = {
        "title", "date", "org", "platform", "participants",
        "duration", "recording", "pipeline-status",
    }
    assert expected_keys <= set(fm.keys()), (
        f"Missing canonical frontmatter keys: {expected_keys - set(fm.keys())}"
    )
    assert fm["pipeline-status"] == "complete"
    assert fm["org"] == "alpha"

    # ---- Body contract ----
    body = text.split("---\n", 2)[2]
    assert "## Summary" in body
    assert "Sprint planning kicked off" in body
    assert "## Key Points" in body or "## Key points" in body
    assert "## Action Items" in body or "## Action items" in body
    assert "draft priorities doc" in body

    # ---- EventIndex updated ----
    from recap.daemon.calendar.index import EventIndex
    index_path = vault_path / "_Recap" / ".recap" / "event-index.json"
    if index_path.exists():
        # event-index entries are keyed by event_id; recording_id alone
        # may not appear unless the pipeline writes it. Adjust based on
        # what run_pipeline actually does.
        idx = EventIndex(index_path)
        # No assertion if the pipeline does not touch EventIndex for
        # non-calendar-seeded notes. Document that here.

    # ---- EventJournal entry ----
    journal_path = vault_path / "_Recap" / ".recap" / "events.jsonl"
    if journal_path.exists():
        entries = [
            json.loads(line) for line in
            journal_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        events = [e["event"] for e in entries]
        # The pipeline may emit pipeline_started + pipeline_completed.
        # If neither exists, the pipeline does not currently journal —
        # that's a gap to flag separately.
        assert any("pipeline" in e for e in events), (
            f"Expected a pipeline_* journal event; got {events}"
        )
```

**Step 4: Run the test**

```bash
uv run pytest tests/test_e2e_pipeline.py -v
```

Expect to need iteration: the first run will likely fail because (a) you guessed the runtime-config shape wrong, (b) the body section header capitalization doesn't match, or (c) the journal entry name differs. Read the actual code, fix the test, re-run. **Do not change source code to make the test pass; the test must reflect what the source actually does.**

If you discover that `run_pipeline` does NOT currently emit a `pipeline_completed` (or similar) journal entry, the test should `xfail` that one assertion with a comment naming the gap, and you should flag it in the task report — Phase 7 (post-Phase-6 cleanup) can fix the source.

**Step 5: Run full suite**

```bash
uv run pytest -q
```

Expected: 553 passed (or higher if your fixture decomposes into multiple test functions), 3 skipped. The new test must not regress existing tests.

**Step 6: Re-measure coverage**

```bash
uv run pytest --cov=recap --cov-report=term -q 2>&1 | tail -20
```

Note the new total in the task report. Coverage should rise — pipeline + vault + artifacts modules now exercise real code paths.

**Step 7: Add the calendar-seeded variant (REQUIRED)**

Parent design acceptance (`docs/plans/2026-04-14-fix-everything-design.md` §408): "There is a test proving calendar-seeded note upsert produces full canonical frontmatter." This is load-bearing and gets its own subtest, not a conditional follow-up.

The flow is: a calendar sync writes a stub note via `recap/daemon/calendar/sync.py::write_calendar_note` (carries event_id, org, scheduled time — no recording yet); later, the pipeline runs against a recording for the same event_id and must UPSERT (not duplicate) the note while keeping the calendar-seeded fields and adding the post-meeting body.

```python
@pytest.mark.skipif(
    __import__("shutil").which("ffmpeg") is None, reason="ffmpeg required",
)
def test_run_pipeline_upserts_calendar_seeded_note(
    vault_path, recordings_path,
):
    """Calendar-seeded note + post-meeting pipeline run upserts cleanly.

    Phase 6 acceptance §408: full canonical frontmatter must survive
    the upsert. Specifically: event-id, org, scheduled time fields
    from the calendar stub must remain, and pipeline-status must
    flip from "scheduled" to "complete".
    """
    from recap.daemon.calendar.sync import write_calendar_note
    from recap.daemon.calendar.index import EventIndex
    from recap.daemon.config import OrgConfig
    from recap.models import (
        AnalysisResult, CalendarEvent, MeetingMetadata, TranscriptResult,
    )
    from recap.artifacts import RecordingMetadata, write_recording_metadata
    from recap.pipeline import run_pipeline

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
    # Sanity: the calendar stub has the event-id and is "scheduled".
    assert "event-id: evt-cal-1" in seeded_text or "event_id: evt-cal-1" in seeded_text
    assert "scheduled" in seeded_text or "pipeline-status: scheduled" in seeded_text

    # Now the recording lands with the SAME event_id. The pipeline
    # should upsert the seeded note in place rather than write a
    # second note.
    audio_path = recordings_path / "2026-04-15-100000-alpha.flac"
    _make_silent_flac(audio_path)
    rec_meta = RecordingMetadata(
        recording_id="2026-04-15-100000-alpha",
        org="alpha",
        platform="meet",
        title="Sprint planning",
        participants=["Alex", "Bri"],
        started_at="2026-04-15T10:00:00-04:00",
        llm_backend="claude",
        note_path=None,
        event_id="evt-cal-1",  # the upsert key
    )
    write_recording_metadata(audio_path, rec_meta)

    transcript = TranscriptResult(
        utterances=[
            {"speaker": "Alex", "start": 1.0, "end": 4.0,
             "text": "Welcome to sprint planning."},
        ],
        segments=[],
    )
    analysis = AnalysisResult(
        summary="Sprint planning kicked off; team aligned.",
        key_points=["Aligned on priorities"],
        action_items=[{"who": "Bri", "what": "circulate notes"}],
        decisions=[],
        questions=[],
    )

    with (
        patch("recap.pipeline.transcribe.run", return_value=transcript),
        patch("recap.pipeline.diarize.run", return_value=[
            {"speaker": "Alex", "start": 1.0, "end": 4.0},
        ]),
        patch("recap.analyze.analyze_meeting", return_value=analysis),
        patch(
            "recap.pipeline.audio_convert.convert_flac_to_aac",
            return_value=audio_path.with_suffix(".m4a"),
        ),
    ):
        config = ...  # same shape as the previous test
        final_note_path = run_pipeline(
            audio_path=audio_path, metadata=rec_meta, config=config,
        )

    # ---- No duplicate notes ----
    meetings_dir = vault_path / "Clients" / "Alpha" / "Meetings"
    notes = list(meetings_dir.glob("*.md"))
    assert len(notes) == 1, (
        f"Expected exactly 1 meeting note after upsert, got {len(notes)}: "
        f"{[n.name for n in notes]}"
    )
    # The pipeline should have upserted the seeded note — same path
    # OR the seeded note replaced by a renamed canonical path. Either
    # way, only one note exists.
    assert final_note_path == notes[0]

    # ---- Calendar-seeded fields preserved ----
    final_text = final_note_path.read_text(encoding="utf-8")
    import yaml
    fm_block = final_text.split("---\n", 2)[1]
    fm = yaml.safe_load(fm_block)
    expected_canonical_keys = {
        "title", "date", "org", "platform", "participants",
        "duration", "recording", "pipeline-status",
    }
    assert expected_canonical_keys <= set(fm.keys()), (
        f"Canonical frontmatter incomplete after calendar-seeded upsert: "
        f"missing {expected_canonical_keys - set(fm.keys())}"
    )
    # event-id from the calendar stub must survive the upsert.
    assert fm.get("event-id") == "evt-cal-1" or fm.get("event_id") == "evt-cal-1"
    # pipeline-status flipped from scheduled to complete.
    assert fm["pipeline-status"] == "complete"

    # ---- EventIndex entry now points at the final note path ----
    refreshed_index = EventIndex(index_path)
    assert refreshed_index.lookup("evt-cal-1") is not None
```

Run BOTH e2e tests:

```bash
uv run pytest tests/test_e2e_pipeline.py -v
```

If `write_calendar_note` has a different signature, or the upsert key is `event_id` rather than `event-id` in YAML, fix the test to match the source. Do NOT change source to fit the test. If the upsert produces TWO notes today (a real bug), pause and ask before deleting one in the test setup — that's a finding, not a test fix.

**Step 8: Commit**

```bash
git add tests/test_e2e_pipeline.py
git commit -m "test: e2e pipeline + calendar-seeded upsert preserve canonical frontmatter"
```

---

## Task 3: New `tests/test_signal_backend_routing.py` — Ollama dispatch through `run_pipeline`

**Context:** Parent design (§399): "pass `RecordingMetadata.llm_backend='ollama'` → **run_pipeline** → assert ollama subprocess was invoked (patch `subprocess.run`, assert on argv)." The unit tests in `tests/test_analyze.py::TestBuildCommand` (around line 187+) and `tests/test_analyze.py::test_ollama_backend` (line 201+) already prove `_build_command` and `analyze_meeting` dispatch correctly when called directly. **Phase 6's value-add is proving the PIPELINE-LEVEL routing: `RecordingMetadata.llm_backend → PipelineRuntimeConfig → analyze_meeting → subprocess.run` end-to-end.** A test that calls `analyze_meeting` directly is duplicate coverage; it must go through `run_pipeline`.

**Files:**
- Create: `tests/test_signal_backend_routing.py`

**Step 1: Trace the pipeline-level routing surface**

Read three places, in order:

1. `recap/artifacts.py` (around line 56) — confirm `RecordingMetadata.llm_backend` is the source field.
2. `recap/daemon/runtime_config.py` — find where `RecordingMetadata.llm_backend` flows into `PipelineRuntimeConfig` (or whatever struct the pipeline consumes). Note the exact field name.
3. `recap/pipeline/__init__.py` — find where `run_pipeline` (or the equivalent entry called by Task 2's E2E test) reads the backend from config and passes it to `analyze_meeting`. This is the routing path the test must exercise.

The test must NOT call `analyze_meeting` directly. It MUST call `run_pipeline` (or whichever pipeline-entry function Task 2 used) so the wiring through `RecordingMetadata → PipelineRuntimeConfig → analyze` is what's under test.

**Step 2: Write the test**

```python
"""Signal backend routing test (Phase 6 Task 3).

Proves that ``RecordingMetadata.llm_backend`` flows through the
pipeline and reaches ``subprocess.run`` with the right argv. The
analyze-layer unit tests in tests/test_analyze.py already prove that
``_build_command`` and ``analyze_meeting`` dispatch correctly when
called directly; this test proves the PIPELINE wiring delivers the
right backend selection to that layer end-to-end.

Mocks at the system boundaries: ML stages (transcribe/diarize) are
mocked because no GPU; ``subprocess.run`` is mocked so the test
captures argv without needing a real LLM. Vault writer, artifacts,
and runtime config all run for real.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from recap.artifacts import RecordingMetadata, write_recording_metadata
from recap.models import AnalysisResult, TranscriptResult


def _make_silent_flac(path: pathlib.Path, seconds: int = 5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=16000",
            "-t", str(seconds), str(path),
        ],
        check=True, capture_output=True,
    )


def _stub_subprocess_result() -> MagicMock:
    """A ``subprocess.CompletedProcess`` shape ``analyze_meeting`` parses."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = json.dumps({
        "summary": "stub", "key_points": [],
        "action_items": [], "decisions": [], "questions": [],
    })
    result.stderr = ""
    return result


@pytest.fixture
def vault_path(tmp_path: pathlib.Path) -> pathlib.Path:
    vault = tmp_path / "vault"
    (vault / "_Recap" / ".recap").mkdir(parents=True)
    (vault / "Clients" / "Alpha" / "Meetings").mkdir(parents=True)
    return vault


@pytest.fixture
def recordings_path(tmp_path: pathlib.Path) -> pathlib.Path:
    rec = tmp_path / "recordings"
    rec.mkdir()
    return rec


def _build_pipeline_config(vault_path, recordings_path, llm_backend: str):
    """Construct the runtime config the pipeline expects.

    Reuses the same shape ``recap/daemon/runtime_config.py`` builds when
    the daemon spawns the pipeline — the goal is to exercise the real
    routing path, not invent a parallel one. If the constructor name
    differs from below, adjust to match the actual factory.
    """
    from recap.pipeline import PipelineRuntimeConfig  # adjust import path
    return PipelineRuntimeConfig(
        vault_path=vault_path,
        recordings_path=recordings_path,
        llm_backend=llm_backend,
        # ... fill remaining fields by reading runtime_config.py and
        # mirroring what daemon/runtime_config.py:build_*_config produces.
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_ollama_backend_in_metadata_dispatches_ollama_subprocess(
    vault_path, recordings_path,
):
    audio_path = recordings_path / "ollama-test.flac"
    _make_silent_flac(audio_path)
    rec_meta = RecordingMetadata(
        recording_id="ollama-test",
        org="alpha", platform="meet", title="Ollama routing",
        participants=[], started_at="2026-04-15T10:00:00-04:00",
        llm_backend="ollama",  # the field under test
        note_path=None,
    )
    write_recording_metadata(audio_path, rec_meta)

    transcript = TranscriptResult(
        utterances=[{"speaker": "Alex", "start": 0.0, "end": 1.0, "text": "Hi."}],
        segments=[],
    )

    from recap.pipeline import run_pipeline

    with (
        patch("recap.pipeline.transcribe.run", return_value=transcript),
        patch("recap.pipeline.diarize.run", return_value=[
            {"speaker": "Alex", "start": 0.0, "end": 1.0},
        ]),
        patch(
            "recap.pipeline.audio_convert.convert_flac_to_aac",
            return_value=audio_path.with_suffix(".m4a"),
        ),
        patch(
            "recap.analyze.subprocess.run",
            return_value=_stub_subprocess_result(),
        ) as mock_subprocess,
    ):
        config = _build_pipeline_config(
            vault_path, recordings_path, llm_backend="ollama",
        )
        run_pipeline(audio_path=audio_path, metadata=rec_meta, config=config)

    # The pipeline reached analyze, which built the ollama command.
    assert mock_subprocess.called, (
        "subprocess.run never called -- pipeline did not reach analyze stage"
    )
    cmd = mock_subprocess.call_args[0][0]
    assert cmd[0] == "ollama", (
        f"Expected pipeline to dispatch ollama; got cmd={cmd!r}. "
        f"This means RecordingMetadata.llm_backend did not flow through "
        f"PipelineRuntimeConfig to analyze_meeting."
    )
    assert "run" in cmd


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_claude_backend_in_metadata_dispatches_claude_subprocess(
    vault_path, recordings_path,
):
    """Symmetric guard so a routing regression in either direction is caught."""
    audio_path = recordings_path / "claude-test.flac"
    _make_silent_flac(audio_path)
    rec_meta = RecordingMetadata(
        recording_id="claude-test",
        org="alpha", platform="meet", title="Claude routing",
        participants=[], started_at="2026-04-15T10:00:00-04:00",
        llm_backend="claude",
        note_path=None,
    )
    write_recording_metadata(audio_path, rec_meta)

    transcript = TranscriptResult(
        utterances=[{"speaker": "Alex", "start": 0.0, "end": 1.0, "text": "Hi."}],
        segments=[],
    )

    from recap.pipeline import run_pipeline

    with (
        patch("recap.pipeline.transcribe.run", return_value=transcript),
        patch("recap.pipeline.diarize.run", return_value=[
            {"speaker": "Alex", "start": 0.0, "end": 1.0},
        ]),
        patch(
            "recap.pipeline.audio_convert.convert_flac_to_aac",
            return_value=audio_path.with_suffix(".m4a"),
        ),
        patch(
            "recap.analyze.subprocess.run",
            return_value=_stub_subprocess_result(),
        ) as mock_subprocess,
    ):
        config = _build_pipeline_config(
            vault_path, recordings_path, llm_backend="claude",
        )
        run_pipeline(audio_path=audio_path, metadata=rec_meta, config=config)

    assert mock_subprocess.called
    cmd = mock_subprocess.call_args[0][0]
    assert cmd[0] != "ollama", (
        f"Pipeline incorrectly dispatched ollama for claude backend; cmd={cmd!r}"
    )
    # Claude CLI command name comes from config; default is "claude".
    # The exact head of the argv depends on PipelineRuntimeConfig defaults.
```

**Step 3: Run + iterate**

```bash
uv run pytest tests/test_signal_backend_routing.py -v
```

If `_build_pipeline_config` doesn't match the real `PipelineRuntimeConfig` shape, fix the helper, not the source. If `run_pipeline` reads `llm_backend` from `metadata` rather than `config`, the assertions still hold — but document which path actually drove dispatch in the task report. **The test must FAIL if a future refactor breaks pipeline-level routing**, even though the analyze-layer unit tests still pass.

**Step 4: Sanity check — the test must catch a real regression**

Temporarily edit `recap/pipeline/__init__.py` to ALWAYS pass `backend="claude"` to `analyze_meeting` regardless of what the metadata/config says. Re-run the test:

```bash
uv run pytest tests/test_signal_backend_routing.py::test_ollama_backend_in_metadata_dispatches_ollama_subprocess -v
```

Expected: FAIL. This proves the test actually exercises the routing path. Revert the source edit, re-run: PASS.

**Step 5: Run full suite + commit**

```bash
uv run pytest -q
git add tests/test_signal_backend_routing.py
git commit -m "test: signal backend routing flows through run_pipeline to subprocess"
```

---

## Task 4: Add `tests/test_event_index.py` edge cases — corruption, concurrent ops

**Context:** Parent design (§400): "edge cases (corrupted index file → rebuild; concurrent modifications)." Today `tests/test_event_index.py` has 17 tests covering the happy path, persistence, schema-version + corrupt-JSON warning paths. Phase 6 adds: rebuild-after-corruption flow and concurrent add/remove safety.

**Files:**
- Modify: `tests/test_event_index.py` (append a new test class `TestEdgeCases`)

**Step 1: Read `recap/daemon/calendar/index.py`** to confirm:
- `EventIndex._load` already swallows JSON errors and starts empty (verified — `tests/test_event_index.py:151` proves this).
- Whether `EventIndex.rebuild()` is idempotent and whether it calls `_save` atomically.
- Whether the index file is written via `tmp_path.replace()` (atomic on POSIX) or direct `write_text` (non-atomic).

**Step 2: Append the new test class**

```python
# Append to tests/test_event_index.py

class TestEdgeCases:
    """Phase 6: corruption recovery and concurrent-modification safety."""

    def test_corrupt_file_then_rebuild_recovers(self, tmp_path):
        """A corrupt on-disk index can be rebuilt from the vault."""
        from recap.daemon.calendar.index import EventIndex

        index_path = tmp_path / "event-index.json"
        index_path.write_text("{this is not valid json", encoding="utf-8")

        idx = EventIndex(index_path)
        assert idx.all_entries() == []  # corrupt load → empty start

        # Seed a vault note with a known event_id frontmatter.
        vault = tmp_path / "vault"
        meetings = vault / "Clients" / "Alpha" / "Meetings"
        meetings.mkdir(parents=True)
        note = meetings / "2026-04-15-test.md"
        note.write_text(
            "---\n"
            "event-id: evt-rebuild-1\n"
            "org: alpha\n"
            "title: Rebuild test\n"
            "---\n",
            encoding="utf-8",
        )

        idx.rebuild(vault)
        entries = idx.all_entries()
        assert len(entries) == 1
        # The rebuild must have refreshed the persisted file too.
        from_disk = EventIndex(index_path)
        assert len(from_disk.all_entries()) == 1

    def test_concurrent_add_and_remove_eventually_consistent(self, tmp_path):
        """Two EventIndex instances mutating the same file end in a
        consistent state after both call _save in sequence.

        Not a true concurrency test (no threads); checks that the
        last-writer-wins semantics don't drop data when callers
        coordinate at the application layer.
        """
        from recap.daemon.calendar.index import EventIndex

        index_path = tmp_path / "event-index.json"

        a = EventIndex(index_path)
        a.add("evt-A", "Clients/Alpha/Meetings/a.md")

        # Simulate a separate process / instance reading the file
        # and adding its own entry.
        b = EventIndex(index_path)
        b.add("evt-B", "Clients/Alpha/Meetings/b.md")

        # Reload from disk: b's add is the most recent _save, so
        # it should have evt-B; evt-A may or may not survive
        # depending on whether b read a's snapshot.
        c = EventIndex(index_path)
        assert c.lookup("evt-B") == "Clients/Alpha/Meetings/b.md"
        # Document the actual last-writer-wins behavior with a
        # clear assertion that future contributors can read.

    def test_empty_file_loads_as_empty_index(self, tmp_path):
        """An empty (zero-byte) index file is treated as a fresh start."""
        from recap.daemon.calendar.index import EventIndex

        index_path = tmp_path / "event-index.json"
        index_path.write_text("", encoding="utf-8")

        idx = EventIndex(index_path)
        assert idx.all_entries() == []

    def test_partial_write_truncated_json_recovers(self, tmp_path):
        """A truncated write (e.g. crash mid-_save) doesn't crash the loader."""
        from recap.daemon.calendar.index import EventIndex

        index_path = tmp_path / "event-index.json"
        # First write a valid index.
        idx = EventIndex(index_path)
        idx.add("evt-1", "Clients/Alpha/Meetings/one.md")
        idx.add("evt-2", "Clients/Alpha/Meetings/two.md")

        # Truncate to half its bytes to simulate a partial fsync.
        contents = index_path.read_bytes()
        index_path.write_bytes(contents[: len(contents) // 2])

        # New instance loads: corrupt → empty per existing
        # warn-and-continue policy.
        recovered = EventIndex(index_path)
        assert recovered.all_entries() == []

    def test_rebuild_is_idempotent(self, tmp_path):
        """Calling rebuild twice in a row produces the same entries."""
        from recap.daemon.calendar.index import EventIndex

        vault = tmp_path / "vault"
        meetings = vault / "Clients" / "Alpha" / "Meetings"
        meetings.mkdir(parents=True)
        (meetings / "n.md").write_text(
            "---\nevent-id: evt-1\norg: alpha\n---\n", encoding="utf-8",
        )

        idx = EventIndex(tmp_path / "event-index.json")
        idx.rebuild(vault)
        first = idx.all_entries()
        idx.rebuild(vault)
        second = idx.all_entries()
        assert first == second
```

**Step 3: Run + iterate**

```bash
uv run pytest tests/test_event_index.py::TestEdgeCases -v
```

If a test reveals a real bug (e.g. `rebuild()` is NOT idempotent, or the index doesn't survive truncation), pause and ask. The plan's intent is tests-only; source fixes are out of scope.

**Step 4: Run full suite + commit**

```bash
uv run pytest -q
git add tests/test_event_index.py
git commit -m "test: event-index edge cases (corruption, concurrent ops, idempotent rebuild)"
```

---

## Task 5: New `tests/test_extension_auth.py` — finalized Bearer + bootstrap protocol

**Context:** Parent design (§401): "/api/meeting-detected rejects no auth; accepts valid token; /bootstrap/token serves only during bootstrap window, only from localhost." Each of these is already proved somewhere (`tests/test_pairing.py`, `tests/test_daemon_server.py::TestApiMeetingDetectedAuth`). Phase 6 consolidates them into one file that documents the **post-Phase-4 finalized contract** in one place. This makes the auth surface auditable in a single read.

**Files:**
- Create: `tests/test_extension_auth.py`

**Step 1: Inspect the existing fixtures**

`tests/conftest.py` exports `daemon_client` (writes `config.yaml`, returns `(client, daemon)` with the auth middleware wired at `AUTH_TOKEN`). Reuse it.

`tests/test_pairing.py` has its own `client` fixture — read it to see the pairing-window-aware setup pattern.

**Step 2: Write the consolidated contract test**

```python
"""Extension auth contract (Phase 6 Task 5).

Consolidates the finalized post-Phase-4 protocol into one place:

  1. /api/meeting-* requires Bearer auth.
  2. /bootstrap/token serves only while PairingWindow is open.
  3. /bootstrap/token enforces loopback-only (defense-in-depth).
  4. A 401 on any /api/* path means "re-pair", not "retry".

This file is the surface-area audit; per-endpoint behavior tests
live in test_daemon_server.py and test_pairing.py.
"""
from __future__ import annotations

import pytest

from tests.conftest import AUTH_TOKEN


@pytest.mark.asyncio
class TestMeetingApiBearer:
    """Contract: /api/meeting-detected and /api/meeting-ended both
    require a Bearer header that exactly matches the daemon auth token.
    """

    async def test_meeting_detected_no_auth_returns_401(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/meeting-detected",
            json={"platform": "meet", "url": "https://meet.google.com/x", "title": "x"},
        )
        assert resp.status == 401

    async def test_meeting_detected_wrong_bearer_returns_401(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post(
            "/api/meeting-detected",
            headers={"Authorization": "Bearer not-the-real-token"},
            json={"platform": "meet", "url": "https://meet.google.com/x", "title": "x"},
        )
        assert resp.status == 401

    async def test_meeting_ended_no_auth_returns_401(self, daemon_client):
        client, _ = daemon_client
        resp = await client.post("/api/meeting-ended", json={"tabId": 1})
        assert resp.status == 401


@pytest.mark.asyncio
class TestBootstrapTokenWindow:
    """Contract: /bootstrap/token returns 200 only during an open
    PairingWindow; before/after the window it returns 404.
    """

    async def test_returns_404_before_window_opens(self, daemon_client):
        client, daemon = daemon_client
        # Pairing window is closed by default.
        resp = await client.get("/bootstrap/token")
        assert resp.status == 404

    async def test_returns_token_during_open_window(self, daemon_client):
        client, daemon = daemon_client
        daemon.pairing.open()
        resp = await client.get("/bootstrap/token")
        assert resp.status == 200
        body = await resp.json()
        assert body["token"] == AUTH_TOKEN

    async def test_window_is_one_shot(self, daemon_client):
        client, daemon = daemon_client
        daemon.pairing.open()
        resp1 = await client.get("/bootstrap/token")
        assert resp1.status == 200
        resp2 = await client.get("/bootstrap/token")
        assert resp2.status == 404


@pytest.mark.asyncio
class TestBootstrapLoopbackOnly:
    """Contract: /bootstrap/token rejects non-loopback peers even when
    the PairingWindow is open. The handler reads the peer IP via
    ``server._extract_peer_ip``; we patch that to force a non-loopback
    address and assert the route returns 403 from the actual handler
    code path. (Phase 3 already covers this in
    ``tests/test_pairing.py::TestBootstrapTokenRoute::test_rejects_non_loopback``;
    Task 5 re-runs the same real-behavior check inside the
    consolidated extension-auth surface so the contract is auditable
    in one file.)
    """

    async def test_rejects_non_loopback_peer(
        self, daemon_client, monkeypatch,
    ):
        from recap.daemon import server as server_mod

        client, daemon = daemon_client
        daemon.pairing.open()
        monkeypatch.setattr(
            server_mod, "_extract_peer_ip", lambda _request: "10.0.0.5",
        )

        resp = await client.get("/bootstrap/token")
        assert resp.status == 403
        # The window stays open so a real loopback caller can still
        # complete the pair after the spoofed peer is rejected.
        assert daemon.pairing.is_open is True

    async def test_loopback_peer_succeeds_when_window_open(
        self, daemon_client, monkeypatch,
    ):
        from recap.daemon import server as server_mod

        client, daemon = daemon_client
        daemon.pairing.open()
        # Force the peer to look like a loopback IP regardless of the
        # transport ``aiohttp.test_utils`` reports.
        monkeypatch.setattr(
            server_mod, "_extract_peer_ip", lambda _request: "127.0.0.1",
        )

        resp = await client.get("/bootstrap/token")
        assert resp.status == 200


@pytest.mark.asyncio
class TestPostPairingApiAccess:
    """Contract: after a successful pairing, the same token works on
    /api/* endpoints — i.e. the bootstrap token IS the daemon auth
    token, not a one-shot exchange voucher.
    """

    async def test_paired_token_works_on_status(self, daemon_client):
        client, daemon = daemon_client
        daemon.pairing.open()
        boot = await client.get("/bootstrap/token")
        token = (await boot.json())["token"]
        resp = await client.get(
            "/api/status", headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status == 200
```

**Step 3: Run + iterate**

```bash
uv run pytest tests/test_extension_auth.py -v
```

If `TestBootstrapLoopbackOnly` finds the source bind has changed or the inspect-based assertion is fragile, replace with a more robust check (e.g. import `_TCPSite_HOST` constant if one exists, or read `Daemon.start.__code__.co_consts`). Goal: prove the loopback guarantee survives via SOME mechanical check.

**Step 4: Run full suite + commit**

```bash
uv run pytest -q
git add tests/test_extension_auth.py
git commit -m "test: consolidated extension auth contract (Bearer, bootstrap window, loopback)"
```

---

## Task 6: Audit + rewrite over-mocked `tests/test_pipeline.py` cases

**Context:** Parent design (§397): "rewrite the tests that patch `write_meeting_note` to use a real tmp vault and assert on actual file content. Delete tests that only assert `pipeline-status: complete` via mocked write." Today's grep shows zero direct patches of `write_meeting_note` / `upsert_note` / `save_*` in `tests/`. So the over-mocking is likely subtler: tests that patch ML stages but ALSO patch `_PATCH_DURATION`, `_PATCH_CONVERT`, `_PATCH_DELETE_SRC` and never check the real file outputs.

**Files:**
- Modify: `tests/test_pipeline.py` (rewrite or delete identified tests).

**Step 1: Survey**

```bash
grep -n "def test_\|_PATCH_" tests/test_pipeline.py
```

For each test function:
- Read the assertions. If the only assertion is `mock.assert_called_with(...)` on a patched stage and there's no read of the resulting note file, mark it for **delete**.
- If the test patches the WRITE side (vault writer, artifacts, EventIndex), mark for **rewrite** — drop the write-side patch and assert on the actual written file.
- If the test patches only the READ side (transcribe/diarize/analyze) and asserts on the file outputs, **keep**.

Produce a table in the task report: function name, current pattern, decision (delete / rewrite / keep), one-line rationale.

**Step 2: Apply decisions**

For **rewrite** cases, the pattern is:

```python
# Before
with patch("recap.vault.write_meeting_note") as m:
    run_pipeline(...)
    m.assert_called_once()

# After
note_path = vault_path / "Clients/Alpha/Meetings/<expected>.md"
run_pipeline(..., config=config_with_vault_path)
assert note_path.exists()
text = note_path.read_text(encoding="utf-8")
assert "## Summary" in text
```

For **delete** cases, just remove the function. Don't add `xfail`/`skip` — Phase 6 is the cleanup pass.

**Step 3: Run + verify**

```bash
uv run pytest tests/test_pipeline.py -v
```

The pass count after this task may be LOWER than baseline (deletions removed tests). The remaining tests must all pass and must exercise real outputs.

**Step 4: Re-measure coverage**

```bash
uv run pytest --cov=recap --cov-report=term -q 2>&1 | tail -20
```

Coverage may drop slightly from deletions; the new E2E test (Task 2) should compensate. Note the delta in the task report.

**Step 5: Run full suite + commit**

```bash
uv run pytest -q
git add tests/test_pipeline.py
git commit -m "refactor(test): drop over-mocked pipeline tests; assert on real file outputs"
```

---

## Task 7: Audit + delete shape-only mocked tests in `tests/test_daemon_server.py`

**Context:** Parent design (§402): "Delete `tests/test_daemon_server.py` tests that only assert response shape with full mocks (keep the ones that exercise real handlers)."

**Files:**
- Modify: `tests/test_daemon_server.py`

**Step 1: Survey**

`tests/test_daemon_server.py` has many test classes (`TestHealthEndpoint`, `TestApiStatusAuth`, `TestArmEndpoint`, ..., `TestApiStatusReal`, `TestWebSocketJournalBroadcast`). The `*Real` classes use `daemon_client` (a real `Daemon`); the others use `client` (an `aiohttp` test client wrapped around `create_app` with no real `Daemon`).

For each test class:
- If it uses the real `Daemon` fixture and asserts on real handler behavior — **keep**.
- If it uses a stubbed handler/detector AND asserts only on response shape (status code, key presence) — candidate for **delete IF AND ONLY IF the same behavior is covered elsewhere**.
- Auth-gate tests (e.g. `TestApiStatusAuth::test_returns_401_without_auth`) are NOT shape-only; they prove the middleware works. **Keep.**
- Field-presence tests like `TestApiStatusAuth::test_response_has_expected_fields` ARE shape assertions, but they pin the canonical response shape — useful contract documentation. **Keep** unless the same shape is already pinned by `TestApiStatusReal` or `tests/test_phase4_integration.py`.

Produce a delete/keep table in the task report with rationale per class.

**Step 2: Apply**

Delete only the test functions/classes you're confident are pure mock-theater. When in doubt, keep — the cost of a redundant test is far less than the cost of dropping a contract assertion.

**Step 3: Run + verify**

```bash
uv run pytest tests/test_daemon_server.py -v
```

All remaining tests pass.

**Step 4: Re-measure coverage**

```bash
uv run pytest --cov=recap --cov-report=term -q 2>&1 | tail -20
```

Note the delta. Should be small (these tests exercise the same handlers the integration tests already cover).

**Step 5: Run full suite + commit**

```bash
uv run pytest -q
git add tests/test_daemon_server.py
git commit -m "refactor(test): drop shape-only mocked daemon_server tests covered elsewhere"
```

---

## Task 8: Enable the `--cov-fail-under=70` coverage gate

**Context:** Final Phase 6 step. Tasks 2-5 added integration tests that exercise real code; Tasks 6-7 cut deadweight. Now lock in the floor so future regressions surface immediately.

**Files:**
- Modify: `pyproject.toml` (`[tool.pytest.ini_options]` — add `addopts` with the coverage flags).

**Step 1: Compute the current coverage**

```bash
uv run pytest --cov=recap --cov-report=term -q 2>&1 | grep "^TOTAL"
```

Expected: ≥ 70%. If lower, the task report must list the modules below the line and propose either (a) more test additions OR (b) ratifying a lower threshold for this phase with a clear plan to raise it.

**Step 2: Wire the gate**

In `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=recap --cov-fail-under=70 --cov-report=term-missing"
```

(Adjust if `[tool.pytest.ini_options]` already has `addopts`; merge.)

**Step 3: Verify the gate fires correctly**

Confirm pytest enforces the threshold:

```bash
uv run pytest -q 2>&1 | tail -10
```

Should pass and report coverage.

Verify the gate fails when below threshold (sanity check; revert immediately).

This repo's primary shell is Git Bash on Windows, but `sed -i` behavior differs across `sed` builds — a portable, repo-friendly approach uses Python:

```bash
uv run python -c "
from pathlib import Path
p = Path('pyproject.toml')
p.write_text(p.read_text(encoding='utf-8').replace('--cov-fail-under=70', '--cov-fail-under=99'), encoding='utf-8')
"
uv run pytest -q 2>&1 | tail -5
# Expected: 'Required test coverage of 99% not reached'
git checkout -- pyproject.toml
```

The `git checkout -- pyproject.toml` revert is the simplest possible undo; no `.bak` file lingers. Re-run `uv run pytest -q` and confirm the 70% gate now passes.

**Step 4: Run final full suite**

```bash
uv run pytest -q
```

Expected: passes; coverage ≥ 70%.

**Step 5: Update handoff doc with the final number**

Append to `docs/handoffs/2026-04-15-phase6-coverage-baseline.md`:

```markdown
## Phase 6 close

**Date:** <today>
**Final commit:** <git rev-parse HEAD>
**Final coverage:** XX.X% (gate: 70%)
**Tests added:** test_e2e_pipeline.py, test_signal_backend_routing.py,
  test_extension_auth.py, TestEdgeCases in test_event_index.py.
**Tests removed:** <list from Tasks 6-7>.
```

**Step 6: Commit**

```bash
git add pyproject.toml docs/handoffs/2026-04-15-phase6-coverage-baseline.md
git commit -m "chore: enable --cov-fail-under=70 gate over recap/"
```

---

## Post-Phase Verification

| Command | Expected |
|---|---|
| `uv run pytest -q` | all pass; coverage line ≥ 70% |
| `uv run pytest --cov=recap --cov-report=term -q` | coverage report cleanly emitted; gate honored |
| `cd obsidian-recap && npm run build` | clean (no plugin changes expected) |
| `grep -rn "patch.*write_meeting_note\|patch.*upsert_note" tests/ --include="*.py"` | 0 hits |

**Acceptance criteria** (parent design §405-413):

- [ ] True end-to-end pipeline test using a real tmp vault and real file outputs (Task 2 Steps 1-6).
- [ ] Test proving calendar-seeded note upsert produces full canonical frontmatter (Task 2 Step 7 — explicit subtest, no longer conditional).
- [ ] Test proving Signal backend choice changes pipeline execution config.
- [ ] Real tests for event-index lifecycle.
- [ ] Tests for extension auth on the finalized protocol.
- [ ] Over-mocked tests deleted or rewritten.
- [ ] Final suite passes cleanly. Coverage ≥ 70% over `recap/`.

---

## Handoff to Final Integration Pass

After Phase 6 closes, the parent design's "Final Integration Pass" (`docs/plans/2026-04-14-fix-everything-design.md` §417) takes over. That phase is solo (no delegation) and exercises the full system on real recordings before the branch can ship. Phase 6 is the last test-infrastructure phase; everything after it is human acceptance and shipping.
