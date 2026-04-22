# Unscheduled Meetings — Design

**Issue:** [#27](https://github.com/TimSimpsonJr/recap/issues/27)
**Status:** Design approved; ready for implementation plan.
**Related:** [#32](https://github.com/TimSimpsonJr/recap/pull/32) widened the funnel into the unscheduled path; [#33](https://github.com/TimSimpsonJr/recap/issues/33) defers retroactive calendar attachment.

---

## Problem

The recorder auto-records Teams, Zoom, and Signal calls when their window is active and (after #32) their call-state check passes. Historically the codebase assumed every recording was backed by a calendar event, so when no event matched, the whole downstream chain silently degraded:

- `note_path` defaulted to empty string, so the pipeline fell back to `{date} - {window_title}.md` ([pipeline/__init__.py:244](../../recap/pipeline/__init__.py)), producing PII-bearing names like `2026-04-22 - Call with Bob.md`.
- Canonical frontmatter dropped `time`, `event-id`, `calendar-source`, and `meeting-link` because the calendar-owned merge branch at [vault.py:122-128](../../recap/vault.py) only emits them when present in `recording_metadata`.
- `_update_index_if_applicable` skipped the EventIndex update because there was no `event-id` ([vault.py:222-224](../../recap/vault.py)), so rename tracking and O(1) lookup stopped working for these notes.
- MeetingListView rendered blank `time` columns because the frontmatter was missing that key.
- `analyze.py` passed an empty `{{participants}}` block into a prompt that still told Claude "map `SPEAKER_XX` labels to a participant name from the roster above" — contradictory instructions.

Nothing crashed. Everything silently degraded. #32 turned this from an edge case into the hot path for Teams auto-recording.

## Goals and non-goals

**Goals**
1. Give unscheduled recordings a **stable synthetic identity** so EventIndex, rename tracking, and pipeline retries stay coherent.
2. Generate a **deterministic, non-PII filename** from recording start time + platform.
3. Populate a **minimum viable frontmatter set** so MeetingListView, Dataview queries, and the rename/index flow behave the same as for scheduled notes.
4. Stop feeding the analyzer contradictory context when the participant roster is empty.

**Non-goals**
- Retroactive calendar attachment — deferred to [#33](https://github.com/TimSimpsonJr/recap/issues/33).
- Diarization quality improvements — [#28](https://github.com/TimSimpsonJr/recap/issues/28)'s territory.
- Any change to scheduled-meeting codepaths.
- Any new daemon HTTP routes or plugin UI surfaces.

## Architecture

### Single mutation point: `_build_recording_metadata`

When the detector decides to auto-record and has no calendar event, it synthesizes `event_id`, `note_path`, `recording_started_at`, and the "default roster" fields (empty participants, null calendar-source, empty meeting-link, platform-labelled title) **before** the `RecordingMetadata` is passed to the recorder and written to the sidecar.

This mutation lives in `_build_recording_metadata` at [detector.py:126-147](../../recap/daemon/recorder/detector.py) (or a helper it calls). Both auto-detection paths — poll-driven detection and extension-signalled detection — flow through `_recording_metadata_from_enriched` at [detector.py:233](../../recap/daemon/recorder/detector.py), so synthesis at this layer covers both for free.

### Downstream codepaths are unchanged

Once the sidecar carries a valid `event_id` and a populated `note_path`, everything downstream runs its existing calendar-backed logic:

- `_resolve_note_path` short-circuits on `note_path` at [pipeline/__init__.py:230-231](../../recap/pipeline/__init__.py).
- `build_canonical_frontmatter` at [vault.py:86-136](../../recap/vault.py) sees the synthetic id and emits the correct shape.
- `_update_index_if_applicable` at [vault.py:196-224](../../recap/vault.py) writes an EventIndex entry keyed on `unscheduled:<uuid>` — plugin rename tracking, O(1) lookup on reprocess, and Dataview queries all keep working.

**Zero special-casing** for unscheduled in pipeline, vault, or index layers. All the "unscheduled aware" logic lives in the detector.

## Data model

### `RecordingMetadata` change

Additive: one new nullable field.

```python
@dataclass
class RecordingMetadata:
    # ...existing fields...
    recording_started_at: datetime | None = None  # timezone-aware
```

- Populated at detection time for both scheduled and unscheduled paths (symmetry is cheap and future-proof for the `time: "HH:MM-HH:MM"` derivation).
- Missing on old sidecars deserializes to `None`; recovery path handles this (see Error Handling).

### Synthetic identity

```python
event_id = f"unscheduled:{uuid.uuid4().hex}"
```

Opaque, globally unique, stable for the lifetime of the recording (survives pipeline retries via the sidecar). Replaceable in principle for [#33](https://github.com/TimSimpsonJr/recap/issues/33); no mechanism in #27 to replace it.

### Filename convention

```
{YYYY-MM-DD} {HHMM} - {Platform} call.md
```

Examples:
- `2026-04-22 1430 - Teams call.md`
- `2026-04-22 0907 - Zoom call.md`
- `2026-04-22 1615 - Signal call.md`

Windows-safe (no colons), sorts correctly, collision-free for same-platform calls starting in different minutes, readable, non-PII.

Collision handling (rare: same-platform, same-minute) resolves at detection time. The word "unscheduled" does **not** appear in the filename — the synthetic id and frontmatter tag carry that classification.

## Detection-time synthesis

Pseudocode for the unscheduled branch of `_build_recording_metadata`:

```python
captured = datetime.now(timezone.utc).astimezone()       # one instant, used for everything
event_id = f"unscheduled:{uuid.uuid4().hex}"
platform_label = {
    "teams":  "Teams call",
    "zoom":   "Zoom call",
    "signal": "Signal call",
}[platform]

org_config = _resolve_org_config(platform)                # existing helper
subfolder = org_config.resolve_subfolder(vault_path)      # vault-relative
base_dir  = subfolder / "Meetings"
base_name = f"{captured:%Y-%m-%d %H%M} - {platform_label}.md"

candidate = base_dir / base_name
n = 2
while (vault_path / candidate).exists() and n <= 9:
    candidate = base_dir / f"{captured:%Y-%m-%d %H%M} - {platform_label} ({n}).md"
    n += 1
else:
    if (vault_path / candidate).exists():
        # Last resort: full seconds. Still deterministic, still non-PII.
        candidate = base_dir / f"{captured:%Y-%m-%d %H%M%S} - {platform_label}.md"

note_path = str(candidate)                                # vault-relative

return RecordingMetadata(
    event_id=event_id,
    note_path=note_path,
    recording_started_at=captured,
    title=platform_label,
    date=captured.date(),
    platform=platform,
    participants=[],
    companies=[],
    calendar_source=None,
    meeting_link="",
    org=org_config.slug,
    # ...
)
```

### Implementation note — `_build_recording_metadata` needs subfolder

`_build_recording_metadata` does not currently resolve `OrgConfig.resolve_subfolder(vault_path)`. Either:
- Extend `_resolve_org_config()` to return `(org_config, subfolder_path)` as a tuple, or
- Add a small `_resolve_org_and_subfolder()` helper that wraps the existing lookup plus `resolve_subfolder(vault_path)`.

Scheduled-meeting path already knows its `note_path` from the calendar sync layer, so this change is effectively unscheduled-only at the call site. Keep the helper minimal.

## Vault-write-time behaviour

### Frontmatter shape

```yaml
date: 2026-04-22
time: "14:30-15:15"
title: "Teams call"
org: acme
org-subfolder: "Acme"
platform: teams
event-id: "unscheduled:abc123def456..."
participants: []
companies: []
duration: "00:45:12"
type: general                         # whatever analysis inferred
tags:
  - "meeting/general"                 # existing canonical pattern
  - "unscheduled"                     # new marker
pipeline-status: complete
recording: "2026-04-22 1430 Teams.flac"
```

Differences from scheduled:
- `calendar-source` and `meeting-link` are omitted (not `null`). The `calendar-source` field stays reserved for real providers (google/zoho/etc.).
- `tags` gains `unscheduled` alongside the canonical `meeting/<type>` tag. Dataview-queryable: `FROM #unscheduled`.

### `time` range derivation

```python
start = recording_started_at.strftime("%H:%M")
end   = (recording_started_at + duration).strftime("%H:%M")
time  = f"{start}-{end}"
```

Degraded cases (missing/zero duration): emit `"HH:MM-HH:MM"` with start==end, e.g. `"14:30-14:30"`. **Never** a bare `HH:MM` — the plugin parses bare clock-time as the all-day sentinel at [meetingTime.ts:13](../../obsidian-recap/src/lib/meetingTime.ts), which breaks sort/past/upcoming classification.

### `recording` field

Basename only, matching the existing contract at [vault.py:119](../../recap/vault.py) where `recording_path.name` is persisted.

## Analyze prompt branch

[prompts/meeting_analysis.md](../../prompts/meeting_analysis.md) and [analyze.py:20-32](../../recap/analyze.py): add a conditional branch for empty rosters.

Current wording (always emitted):

> The following people were expected in this meeting:
> {{participants}}
>
> ...map each `SPEAKER_XX` label to a participant name from the roster above...

New wording when `participants` is empty:

> No participant roster is available for this meeting. Only assign a real name if it is explicitly established in the transcript (e.g. a self-introduction, "Hi, I'm Alice"). Otherwise use `Unknown Speaker N`.

JSON schema of `AnalysisResult` is unchanged. This removes the contradictory instruction without attempting to improve diarization quality (out of scope; #28 owns that).

## Error handling

| Case | Behaviour |
|---|---|
| Filename collision (same minute, same platform) | Append `(2)`..`(9)` at detection time; fall through to full-seconds timestamp if still colliding. |
| Zero or missing duration at vault-write | Emit `time: "HH:MM-HH:MM"` with start==end. Valid range format, degenerate span, preserves MeetingListView sort. |
| Pre-#27 sidecar replayed through recovery (no `recording_started_at`) | Fall back to `datetime.now()` and log warning. Vintage of sidecar is vanishingly old by the time this matters. |
| `_resolve_org_config(platform)` raises | Existing behavior — recording aborts. No change. |

## Testing

### Unit

- **`test_detector.py`** — `_build_recording_metadata` with no calendar event produces:
  - `event_id` matching `r"^unscheduled:[0-9a-f]{32}$"`
  - `note_path` matching `r"^.*Meetings/\d{4}-\d{2}-\d{2} \d{4} - (Teams|Zoom|Signal) call(?: \(\d\))?\.md$"`
  - non-null `recording_started_at` (timezone-aware)
  - `participants == []`, `meeting_link == ""`, `calendar_source is None`
  - Title matches the platform label
  - Cover both `detect_meeting_windows`-driven path and `_recording_metadata_from_enriched` extension-driven path.
  - Collision test: when `(vault_path / candidate).exists()` returns True for the first two candidates, the result gets `(3)` suffix.

- **`test_artifacts.py`** — `RecordingMetadata` serialization roundtrips `recording_started_at`; missing-field deserializes to `None`.

- **`test_vault.py`** — `build_canonical_frontmatter` with synthetic `event-id` and empty participants produces the shape documented above; `unscheduled` tag present; `calendar-source`/`meeting-link` absent; `time` is a valid range. `_update_index_if_applicable` writes an EventIndex entry keyed on the synthetic id.

- **`test_analyze.py`** — empty `participants` → prompt omits the "map to roster" instruction and includes the fallback wording; non-empty → preserves existing prompt verbatim.

### Integration

Extend `test_phase2_integration.py` or add `test_unscheduled_integration.py`:
1. Fake detector fires auto-record for Teams with no calendar event.
2. Fake recording path + pipeline runs through.
3. Assert note lands at `{default_org_subfolder}/Meetings/YYYY-MM-DD HHMM - Teams call.md`.
4. Assert frontmatter has: `event-id: unscheduled:*`, `time: "HH:MM-HH:MM"`, `tags: [..., unscheduled]`, missing `calendar-source`/`meeting-link`.
5. Assert EventIndex has an entry keyed on the synthetic id.
6. Assert MeetingListView's query path (by reading the org subfolder scan) finds the note.

## Migration and rollout

- No config changes required.
- No user-visible UI changes.
- Existing sidecars from before this PR don't have `recording_started_at` — they deserialize to `None` and the recovery path logs a warning + uses `datetime.now()`. No existing recording is broken.
- No data migration. Old unscheduled notes (with PII filenames, missing `event-id`) stay as-is unless the user manually reprocesses.

## Open questions

None at design-approval time. Implementation plan (next step via `writing-plans` skill) will break this into ordered tasks with tests.
