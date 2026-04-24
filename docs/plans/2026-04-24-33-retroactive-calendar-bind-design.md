# Issue #33 — Retroactive Calendar Attachment Design

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:writing-plans` to produce the implementation plan from this design.

**Goal:** Let the user retroactively re-bind a recording from a synthetic `unscheduled:<uuid>` identity to a real calendar event. Single user action collapses two notes (unscheduled recording note + calendar stub) into one canonical calendar-backed note, updates EventIndex, rewrites the RecordingMetadata sidecar, and preserves meaningful user edits from the stub.

**Architecture:** Plugin scans vault for calendar stub notes near the recording's date and presents a quick-pick. User selects; plugin POSTs `event_id` to a new daemon endpoint. Daemon runs a single orchestrated bind operation with idempotent retry semantics: merge onto calendar stub's path, preserve meaningful stub body content under `## Pre-Meeting Notes`, rewrite sidecar to bound-event state, update EventIndex, delete unscheduled note. Conflict path (target already has a recording) surfaces as 409 with a structured body; plugin shows an explicit Replace/Cancel confirmation.

**Tech Stack:** Python 3.12 + aiohttp; Obsidian plugin (TypeScript + existing Vitest); pytest + manual acceptance.

**Follow-up:** [#39 — Merge multiple recordings of the same calendar event into one meeting artifact](https://github.com/TimSimpsonJr/recap/issues/39) is the dedicated place for "combine recordings" semantics, which #33 explicitly does not do.

---

## 1. Architecture overview

### User flow

1. User opens an unscheduled meeting note in Obsidian.
2. Runs "Link to calendar event" command.
3. Plugin scans `<org-subfolder>/Meetings/*.md` for candidate stubs: frontmatter `event-id` present AND not starting with `unscheduled:` AND `date` within ±1 day of the recording's date.
4. Plugin shows quick-pick: title + date + time + calendar-source per candidate.
5. User picks one. Plugin sends `POST /api/recordings/{stem}/attach-event` with `{event_id}`.
6. Daemon performs a **single orchestrated bind operation with idempotent retry semantics** (merged note write + sidecar rewrite + EventIndex update + unscheduled-note delete). Returns new note path on success.
7. Plugin closes the old unscheduled note view and opens the new canonical note.

### Ownership split

- **Plugin owns:** command registration, candidate scan (vault-local), picker UI, conflict-confirmation modal, post-success note navigation.
- **Daemon owns:** bind orchestration, merge logic, frontmatter rewrite, body-preservation heuristic, EventIndex updates, sidecar rewrite, unscheduled file deletion.

### Final state after bind (happy path)

```
BEFORE:
  <org>/Meetings/2026-04-24 1430 - Teams call.md   # unscheduled
    frontmatter: event-id=unscheduled:<uuid>, tags=[meeting/x, unscheduled], time=14:30-15:15
    body: pipeline output
  <org>/Meetings/2026-04-24 - sprint-planning.md   # calendar stub
    frontmatter: event-id=E1, calendar-source=google, meeting-link=..., time=14:00-15:00
    body: ## Agenda\n<description or user edits>
  EventIndex: {unscheduled:<uuid> -> unscheduled note, E1 -> stub}
  recording sidecar: event_id=unscheduled:<uuid>, note_path=unscheduled note, ...

AFTER:
  <org>/Meetings/2026-04-24 - sprint-planning.md   # final
    frontmatter: event-id=E1, calendar-source=google, meeting-link=..., time=14:00-15:00,
                 participants=..., companies=..., tags=[meeting/x]   (unscheduled tag removed)
    body: pipeline output, then (if stub had meaningful content) ## Pre-Meeting Notes\n<preserved>
  (unscheduled note file deleted)
  EventIndex: {E1 -> final}
  recording sidecar: event_id=E1, note_path=final, calendar_source=google, meeting_link=...,
                     title="Sprint Planning"
```

### Non-goals

- Silent auto-binding on calendar sync (deferred from v1; issue flagged as optional).
- Bulk re-bind tooling.
- Changing the synthetic `unscheduled:<uuid>` format.
- Combining multiple recordings of the same event into one meeting artifact (tracked as [#39](https://github.com/TimSimpsonJr/recap/issues/39)).

---

## 2. Bind operation data flow

### 2.1 Step sequence

```
Inputs: stem (e.g. "2026-04-24 1430 Teams call"), event_id (e.g. "E1"), replace: bool

1. Resolve audio_path via resolve_recording_path(recordings_path, stem).
   - 404 if not found.

2. Load sidecar (404 if missing). Classify:
   a. sidecar.event_id.startswith("unscheduled:")
      -> normal bind candidate. Continue to step 3.
   b. sidecar.event_id == requested event_id
      -> no-op candidate. Continue to step 3 (confirm paths match after lookup).
   c. else (real event_id, different from requested)
      -> 400 {error: "already_bound_to_other_event", current_event_id, current_note_path}.

3. Resolve target stub via find_note_by_event_id(event_id, ...)
   (recap/daemon/calendar/sync.py:115 — has stale-heal semantics).
   - 404 if not found.

4. Reconcile candidate class with target:
   - Branch (b) no-op candidate: verify sidecar.note_path == target path.
     - Match -> cleanup-on-no-op (see 2.3), return 200 {noop: true, cleanup_performed}.
     - Mismatch -> 400 {error: "already_bound_to_other_event",
                        current_note_path: sidecar.note_path,
                        current_event_id: sidecar.event_id}.
   - Branch (a) normal bind: continue.

5. Read source unscheduled note frontmatter (source_fm).
   - 404 {error: "source note not found"} if the sidecar-referenced note is gone.
   Conflict check on target stub's `recording` field:
   - Absent -> bind (normal case).
   - == source_fm.recording -> idempotent no-op (edge: retry after crash
     mid-sidecar-write). Cleanup (see 2.3), return 200 {noop: true}.
   - != source_fm.recording AND replace=false -> 409 {error: "recording_conflict",
                                                      existing_recording, note_path}.
   - != source_fm.recording AND replace=true -> proceed (replace path).

6. Read stub body. Apply Q3 Pre-Meeting Notes heuristic (Section 2.2).

7. Build merged frontmatter:
   - Start from stub's frontmatter (event-id, calendar-source, meeting-link, time, date, title, org, org-subfolder).
   - Overlay source's non-calendar keys (participants, companies, duration, recording,
     audio_warnings, system_audio_devices_seen, recording_started_at).
   - Remove "unscheduled" tag from tags list; preserve other tags.
   - pipeline-status: always take from source (reflects most-recent pipeline state;
     prevents stale "complete" from a replaced recording).

8. Atomic write merged note to target path (temp + os.replace via
   _atomic_write_note from recap/vault.py).

9. Rewrite sidecar to bound-event state (atomic temp + os.replace):
   event_id=target_event_id, note_path=target's vault-relative path,
   calendar_source=stub.calendar_source, meeting_link=stub.meeting_link,
   title=stub.title.

10. EventIndex.remove(synthetic_id). (Idempotent no-op if already removed.)

11. Delete unscheduled note file.

12. Return 200 {status: "ok", note_path: target vault-relative, noop: false}.
```

### 2.2 Body-merge heuristic

Per Q3 locked rule:

1. Normalize line endings and trim outer whitespace on stub body.
2. If body starts with `## Agenda` heading: strip it once, trim remainder.
3. If remainder is empty: skip append (pure template).
4. If remainder is non-empty: append `\n\n## Pre-Meeting Notes\n\n<remainder>` to source body.
5. If body does not start with `## Agenda` (unexpected shape fallback): append whole stub body verbatim under `## Pre-Meeting Notes`.

### 2.3 Retry semantics — cleanup-on-no-op

Every no-op return path (steps 4 and 5) performs idempotent cleanup:
- If the source unscheduled note still exists at `sidecar.note_path`: delete it.
- If `EventIndex.lookup(synthetic_id)` returns non-None: `remove(synthetic_id)`.
- Return `{noop: true, cleanup_performed: <bool>}`.

This heals leaked state from mid-bind crashes:
- Crash between merged-note write (step 8) and sidecar rewrite (step 9): retry re-enters step 2 branch (a), re-runs merge (idempotent), sidecar rewrite retries.
- Crash between sidecar rewrite and EventIndex remove: retry hits step 2 branch (b) match in step 4, cleanup fires.
- Crash between EventIndex remove and unscheduled file delete: same as above.

**Retry is always safe.** No partial-success state corrupts user data.

### 2.4 Conflict path (replace=true)

When `replace=true`:
- Step 5 skips the conflict check (uses the branch that would otherwise trigger 409).
- Step 8 overwrites the stub with the new recording's merged content.
- Step 9 rewrites the sidecar.
- Step 11 deletes the unscheduled note.
- **Orphan artifacts from the old recording** (FLAC/M4A + transcript + speakers.json + analysis.json + metadata.json) remain on disk. Deferred cleanup concern; user can delete manually.

### 2.5 Sanity checks

Before step 5, daemon validates:
- Requested `event_id` does NOT start with `unscheduled:` → 400 `target_event_must_be_real_calendar_event`. Defense-in-depth beyond plugin filtering.
- Stub's `org` matches source note's `org` → 400 `cross_org_bind_refused` on mismatch.
- Stub's `date` is within ±1 day of source's `date` → 400 `date_out_of_window` on mismatch.

Failed sanity check → 400 with specific error code.

---

## 3. Plugin-side changes

### 3.1 DaemonClient additions

**File:** `obsidian-recap/src/api.ts`

Extend `DaemonError` with optional parsed body. Benefits every future structured-error endpoint.

```typescript
export class DaemonError extends Error {
    constructor(
        public status: number,
        message: string,
        public body?: unknown,   // parsed JSON body when available
    ) {
        super(message);
    }
}
```

Update `get<T>` and `post<T>` helpers to parse JSON error bodies when present:

```typescript
async post<T>(path: string, body?: unknown): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, { /* ... */ });
    if (!resp.ok) {
        const text = await resp.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(text);
        } catch {
            // non-JSON; body stays undefined
        }
        throw new DaemonError(resp.status, text, parsed);
    }
    return resp.json() as Promise<T>;
}
```

New `attachEvent` method:

```typescript
export interface AttachEventResponse {
    status: string;
    note_path: string;
    noop?: boolean;
    cleanup_performed?: boolean;
}

export interface AttachEventConflict {
    error: "recording_conflict";
    existing_recording: string;
    note_path: string;
}

export interface AttachEventAlreadyBound {
    error: "already_bound_to_other_event";
    current_event_id: string;
    current_note_path?: string;
}

async attachEvent(params: {
    stem: string;
    event_id: string;
    replace?: boolean;
}): Promise<AttachEventResponse> {
    return this.post(
        `/api/recordings/${encodeURIComponent(params.stem)}/attach-event`,
        {event_id: params.event_id, replace: params.replace ?? false},
    );
}
```

Note: network failures (fetch throws) still surface as raw Errors, not `DaemonError`. This matches existing client behavior; out-of-scope for this change.

### 3.2 Command registration

**File:** `obsidian-recap/src/main.ts`

```typescript
this.addCommand({
    id: "recap-link-to-calendar-event",
    name: "Link to calendar event",
    checkCallback: (checking: boolean) => {
        const file = this.app.workspace.getActiveFile();
        if (!file) return false;
        const cache = this.app.metadataCache.getFileCache(file);
        const eventId = cache?.frontmatter?.["event-id"];
        const isUnscheduled = typeof eventId === "string"
            && eventId.startsWith("unscheduled:");
        if (!isUnscheduled) return false;
        if (checking) return true;
        void this.openLinkToCalendarFlow(file);
        return true;
    },
});
```

Also surface as a context-menu item on unscheduled meeting rows in `MeetingListView`. This requires plumbing through `MeetingListView.ts` + `MeetingRow.ts` (the row currently only supports left-click open; right-click menu is new surface).

### 3.3 Orchestrator

```typescript
private async openLinkToCalendarFlow(file: TFile): Promise<void> {
    if (!this.client) { new Notice("Daemon not connected"); return; }

    const cache = this.app.metadataCache.getFileCache(file);
    const fm = cache?.frontmatter;
    const recording = (fm?.recording ?? "").toString().replace(/\[\[|\]\]/g, "");
    const stem = recording.replace(/\.(flac|m4a|aac)$/i, "");
    const orgSubfolder = fm?.["org-subfolder"] || "";
    const org = fm?.org || "";
    const recordingDate = fm?.date || "";
    if (!stem || !orgSubfolder || !recordingDate) {
        new Notice("Missing recording/date/org-subfolder in frontmatter");
        return;
    }

    const candidates = this.scanCalendarStubCandidates(orgSubfolder, recordingDate);
    if (candidates.length === 0) {
        new Notice("No calendar events found within one day of this recording");
        return;
    }

    new CalendarEventPickerModal(this.app, candidates, async (picked) => {
        await this.submitAttachEvent(file, stem, picked.event_id);
    }).open();
}
```

### 3.4 Candidate scan

```typescript
interface CalendarEventCandidate {
    event_id: string;
    title: string;
    date: string;
    time: string;
    calendar_source: string;
    note_path: string;
}

private scanCalendarStubCandidates(
    orgSubfolder: string, recordingDate: string,
): CalendarEventCandidate[] {
    const prefix = orgSubfolder.endsWith("/")
        ? `${orgSubfolder}Meetings/` : `${orgSubfolder}/Meetings/`;
    const recordingDay = new Date(recordingDate + "T00:00:00Z");
    const out: CalendarEventCandidate[] = [];

    for (const file of this.app.vault.getMarkdownFiles()) {
        if (!file.path.startsWith(prefix)) continue;
        const fm = this.app.metadataCache.getFileCache(file)?.frontmatter;
        if (!fm) continue;
        const eventId = fm["event-id"];
        if (typeof eventId !== "string") continue;
        if (eventId.startsWith("unscheduled:")) continue;

        const date = fm.date;
        if (typeof date !== "string") continue;
        const eventDay = new Date(date + "T00:00:00Z");
        const diffDays = Math.abs(
            (eventDay.getTime() - recordingDay.getTime()) / (24 * 60 * 60 * 1000),
        );
        if (diffDays > 1) continue;

        out.push({
            event_id: eventId,
            title: String(fm.title ?? file.basename),
            date,
            time: String(fm.time ?? ""),
            calendar_source: String(fm["calendar-source"] ?? ""),
            note_path: file.path,
        });
    }

    out.sort((a, b) => a.date !== b.date
        ? a.date.localeCompare(b.date)
        : a.time.localeCompare(b.time));
    return out;
}
```

### 3.5 Picker + confirmation modals

**File:** `obsidian-recap/src/views/CalendarEventPickerModal.ts` (new) — extends `SuggestModal<CalendarEventCandidate>`. Fuzzy search by title + date. Each row renders `Sprint Planning — 2026-04-24 — 14:00-15:00 — google`.

**File:** `obsidian-recap/src/views/ConfirmReplaceModal.ts` (new) — minimal [Replace] / [Cancel] confirmation. Body explains the trade-off: existing recording content is overwritten; old artifacts remain on disk.

### 3.6 Submit + conflict handling

```typescript
private async submitAttachEvent(
    sourceFile: TFile, stem: string, eventId: string, replace: boolean = false,
): Promise<void> {
    if (!this.client) return;
    try {
        const result = await this.client.attachEvent({stem, event_id: eventId, replace});
        new Notice(result.noop ? "Already bound to this event." : "Linked to calendar event. Opening note...");
        await this.openTargetNote(result.note_path);
    } catch (e) {
        if (e instanceof DaemonError) {
            if (e.status === 409 && e.body && typeof e.body === "object") {
                const body = e.body as AttachEventConflict;
                if (body.error === "recording_conflict") {
                    const confirmed = await new ConfirmReplaceModal(
                        this.app, body.existing_recording, stem,
                    ).prompt();
                    if (confirmed) {
                        await this.submitAttachEvent(sourceFile, stem, eventId, true);
                    }
                    return;
                }
            }
            if (e.status === 400) {
                new Notice(`Recap: ${e.message || "bad request"}`);
                return;
            }
        }
        new Notice(`Recap: link failed — ${e}`);
    }
}
```

### 3.7 Files touched

| Area | New code |
|---|---|
| `api.ts` | `DaemonError.body` extension + JSON parse in `get`/`post` error paths + `attachEvent` method + 3 response/error types |
| `main.ts` | Command registration + `openLinkToCalendarFlow` + `scanCalendarStubCandidates` + `submitAttachEvent` + `openTargetNote` |
| `views/MeetingListView.ts` + `components/MeetingRow.ts` | Row context-menu plumbing. Non-trivial: requires new callback through `MeetingListView` deps + row template changes. Scope note for the plan. |
| `views/CalendarEventPickerModal.ts` | New file — SuggestModal extension |
| `views/ConfirmReplaceModal.ts` | New file — minimal confirm dialog |

---

## 4. Daemon-side changes

### 4.1 New endpoint

**File:** `recap/daemon/server.py`

Synchronous handler (no `asyncio.to_thread` in v1 — the orchestration is fast file I/O + in-memory index mutation):

```python
async def _api_attach_event(request: web.Request) -> web.Response:
    """POST /api/recordings/<stem>/attach-event -- retroactive calendar bind."""
    daemon: Daemon = request.app["daemon"]
    stem = request.match_info["stem"]
    if not _STEM_RE.fullmatch(stem):
        return web.json_response({"error": "invalid stem"}, status=400)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be an object"}, status=400)

    event_id = body.get("event_id")
    replace = bool(body.get("replace", False))
    if not isinstance(event_id, str) or not event_id:
        return web.json_response({"error": "missing event_id"}, status=400)
    if event_id.startswith("unscheduled:"):
        return web.json_response(
            {"error": "target_event_must_be_real_calendar_event"}, status=400,
        )

    from recap.daemon.recorder.attach import (
        attach_event_to_recording,
        AttachAlreadyBoundError, AttachConflictError, AttachNotFoundError,
    )
    try:
        result = attach_event_to_recording(
            daemon=daemon, stem=stem, event_id=event_id, replace=replace,
        )
        return web.json_response(result.to_dict())
    except AttachAlreadyBoundError as e:
        return web.json_response(e.to_dict(), status=400)
    except AttachConflictError as e:
        return web.json_response(e.to_dict(), status=409)
    except AttachNotFoundError as e:
        return web.json_response(e.to_dict(), status=404)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        logger.exception("attach-event failed for stem=%s", stem)
        return web.json_response({"error": f"attach failed: {e}"}, status=500)
```

Route registration: `app.router.add_post("/api/recordings/{stem}/attach-event", _api_attach_event)`.

### 4.2 New module: `recap/daemon/recorder/attach.py`

Orchestration lives in its own module so unit tests can exercise it without the HTTP layer.

```python
from dataclasses import dataclass, asdict

@dataclass
class AttachResult:
    status: str  # "ok"
    note_path: str
    noop: bool = False
    cleanup_performed: bool = False

    def to_dict(self) -> dict: return asdict(self)


class AttachAlreadyBoundError(Exception):
    def __init__(self, current_event_id: str, current_note_path: str | None = None):
        self.current_event_id = current_event_id
        self.current_note_path = current_note_path
    def to_dict(self) -> dict: ...


class AttachConflictError(Exception):
    def __init__(self, existing_recording: str, note_path: str):
        self.existing_recording = existing_recording
        self.note_path = note_path
    def to_dict(self) -> dict: ...


class AttachNotFoundError(Exception):
    def __init__(self, what: str): self.what = what
    def to_dict(self) -> dict: ...


def attach_event_to_recording(
    *, daemon: "Daemon", stem: str, event_id: str, replace: bool = False,
) -> AttachResult:
    """Orchestrate the bind per Section 2. Raises the appropriate error
    type on each failure class. Retry-safe via cleanup-on-no-op."""

    # Defense-in-depth synthetic-id guard for callers that bypass the
    # HTTP layer (tests, future internal uses).
    if event_id.startswith("unscheduled:"):
        raise ValueError("target_event_must_be_real_calendar_event")

    # ... steps 1-12 per Section 2 ...
```

Private helpers:
- `_classify_sidecar(sidecar, event_id) -> "normal" | "noop_candidate"` (raises `AttachAlreadyBoundError` on class c).
- `_build_merged_frontmatter(stub_fm, source_fm) -> dict`.
- `_merge_bodies(stub_body, source_body) -> str` (Q3 heuristic).
- `_cleanup_after_bind(daemon, synthetic_id, unscheduled_path) -> bool` (idempotent; returns True if anything was cleaned).

### 4.3 New helper: `_atomic_write_note` in `recap/vault.py`

Existing vault writers at [vault.py:158](recap/vault.py:158) write directly. The bind's merged-note write needs crash safety.

```python
def _atomic_write_note(path: Path, content: str) -> None:
    """Write a note atomically via temp-file + os.replace.

    Used by the retroactive-bind flow (#33) where a half-written merged
    note would corrupt the calendar stub on crash."""
    import os
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError:
        if tmp_path.exists():
            try: tmp_path.unlink()
            except OSError: pass
        raise
```

### 4.4 `write_recording_metadata` upgraded to atomic (MANDATORY in this issue)

[artifacts.py:151](recap/artifacts.py:151) currently does a direct write. Upgrade to temp+replace so the bind's sidecar rewrite is crash-safe. Pre-existing callers (recorder start, #29's on_before_finalize, pipeline reprocess) get stronger crash semantics for free — no behavior change.

```python
def write_recording_metadata(audio_path: Path, metadata: RecordingMetadata) -> None:
    """Write the sidecar atomically (temp + os.replace)."""
    import os
    sidecar_path = _sidecar_path(audio_path)
    tmp_path = sidecar_path.with_suffix(sidecar_path.suffix + ".tmp")
    try:
        tmp_path.write_text(
            json.dumps(metadata.to_dict(), indent=2), encoding="utf-8",
        )
        os.replace(tmp_path, sidecar_path)
    except OSError:
        if tmp_path.exists():
            try: tmp_path.unlink()
            except OSError: pass
        raise
```

Add `rebind_recording_metadata_to_event` in the same module:

```python
def rebind_recording_metadata_to_event(
    audio_path: Path, *, event_id: str, note_path: str,
    calendar_source: str | None, meeting_link: str | None,
    title: str | None,
) -> None:
    """Rewrite sidecar from unscheduled state to bound-event state."""
    rm = load_recording_metadata(audio_path)
    if rm is None:
        raise ValueError(f"no sidecar for {audio_path}")
    rm.event_id = event_id
    rm.note_path = note_path
    if calendar_source is not None: rm.calendar_source = calendar_source
    if meeting_link is not None: rm.meeting_link = meeting_link
    if title is not None: rm.title = title
    write_recording_metadata(audio_path, rm)
```

### 4.5 Files touched

| File | Change |
|---|---|
| `recap/daemon/server.py` | New `_api_attach_event` handler + route |
| `recap/daemon/recorder/attach.py` | **New module** — orchestrator + error types + private helpers |
| `recap/vault.py` | New `_atomic_write_note` helper |
| `recap/artifacts.py` | `write_recording_metadata` upgraded to atomic (required) + new `rebind_recording_metadata_to_event` |

---

## 5. Error handling and edge cases

### 5.1 Endpoint error responses

| Condition | Status | Body |
|---|---|---|
| Missing auth | 401 | existing middleware |
| Invalid stem | 400 | `{error: "invalid stem"}` |
| Body not JSON / not object | 400 | `{error: "invalid JSON body"}` |
| Missing event_id | 400 | `{error: "missing event_id"}` |
| `event_id.startswith("unscheduled:")` | 400 | `{error: "target_event_must_be_real_calendar_event"}` |
| Stem not resolvable | 404 | `{error: "recording not found"}` |
| Sidecar missing | 404 | `{error: "sidecar not found"}` |
| Sidecar bound to different real event_id | 400 | `{error: "already_bound_to_other_event", current_event_id, current_note_path?}` |
| Target event_id not found | 404 | `{error: "event not found"}` |
| Source unscheduled note gone (sidecar references missing path) | 404 | `{error: "source note not found", note_path}` |
| Cross-org bind (stub.org ≠ source.org) | 400 | `{error: "cross_org_bind_refused", source_org, target_org}` |
| Date outside ±1 day | 400 | `{error: "date_out_of_window", source_date, target_date}` |
| Target has different recording, replace=false | 409 | `{error: "recording_conflict", existing_recording, note_path}` |
| Merged note write fails (OSError) | 500 | `{error: "note write failed: <detail>"}` |
| Sidecar rewrite fails | 500 | `{error: "sidecar rewrite failed: <detail>"}` — merged note exists, retry heals |
| EventIndex remove fails | 500 | Retry heals (remove is idempotent) |
| Unscheduled delete fails | 500 | Retry heals (re-checks existence) |
| Shutdown | 503 | existing middleware |

### 5.2 Orchestrator edge cases

**Crash between merged-note write and sidecar rewrite.** Sidecar still has `unscheduled:<uuid>`. Retry re-enters step 2 branch (a), re-runs merge (overwrite is idempotent), sidecar rewrite retries. One extra user click.

**Crash between sidecar rewrite and EventIndex remove.** Sidecar bound, merged note live, synthetic EventIndex entry still present. Retry re-enters step 2 branch (b), step 4 match, cleanup fires. User-visible: "Already bound" notice.

**Crash between EventIndex remove and unscheduled delete.** Merged note live, sidecar bound, synthetic entry removed, unscheduled file orphan. Retry no-op cleanup deletes the orphan.

**User picks the unscheduled note itself as the target.** Plugin filters out `unscheduled:` event-ids (Section 3.4). A buggy client bypassing the filter hits the daemon's `target_event_must_be_real_calendar_event` guard (Section 5.1).

**User picks an event_id that matches their own already-bound sidecar.** Step 2b's no-op path.

### 5.3 File system edge cases

**Vault path renamed externally between request receive and step 9.** Writes fail with OSError, return 500. Retry after fixing. Pre-existing risk pattern.

**Target stub deleted since plugin scanned.** `find_note_by_event_id` returns None → 404 `event not found`.

**Source unscheduled note deleted since plugin triggered.** 404 `source note not found` with expected path in response.

**Disk full during `_atomic_write_note`.** Temp write fails, stub untouched. Standard failure mode.

**Permission error on unscheduled delete after merged note + sidecar + EventIndex updates completed.** Returns 500 `{cleanup delete failed}` but the bind itself succeeded. User can manually delete the orphan. Retry would hit the same error. Rare; documented in the acceptance checklist.

### 5.4 EventIndex stale-heal leverage

`find_note_by_event_id` (sync.py:115) has stale-heal semantics: if the index entry's path is gone, it scans the meetings dir and updates the index. The attach orchestrator benefits for free.

### 5.5 Plugin-side error UX

- 400 generic → `Notice("Recap: <message>")`.
- 400 `already_bound_to_other_event` → `Notice("This recording is already bound to event <id>.")`.
- 404 generic → `Notice("Recap: event not found")`.
- 404 `source note not found` → `Notice("Source note moved or deleted at <path>")`.
- 409 `recording_conflict` → modal confirmation → re-POST with `replace: true`.
- 500 → `Notice("Recap: link failed — <message>")`.
- Network failure → raw Error falls through to generic handler.

### 5.6 Concurrency

- `EventIndex` has its own `threading.Lock`.
- Multiple `attach-event` requests may reach the handler concurrently. `attach_event_to_recording()` runs synchronously — once an orchestration starts, it completes before the event loop picks up the next request's body. Request B may begin request parsing before A commits, but it won't enter the synchronous bind critical section until A finishes.
- Two concurrent requests for same stem: B sees already-bound sidecar → no-op path.
- `attach-event` vs concurrent calendar sync on the same target stub: sync's write may be overwritten by attach's merged write. Acceptable v1 race — sync runs every ~60s, attach window is ~50-100ms.

### 5.7 Documented v1 limitations

- **Replace-path orphans**: old recording's FLAC/M4A/transcript/analysis/speakers.json/metadata.json remain on disk. Deferred.
- **Permission-error on unscheduled delete after successful bind**: 500 + manual cleanup.
- **No auto-detect of calendar matches** (issue non-goal).

---

## 6. Testing strategy

### 6.1 Test file matrix

| File | Scope | New / extended |
|---|---|---|
| `tests/test_attach.py` | `attach_event_to_recording` + helpers | **new** |
| `tests/test_artifacts.py` | Atomic sidecar write + `rebind_recording_metadata_to_event` | extended |
| `tests/test_vault.py` | `_atomic_write_note` | extended |
| `tests/test_daemon_server.py` | `POST /api/recordings/{stem}/attach-event` endpoint contract | extended |
| `tests/test_attach_integration.py` | End-to-end bind scenarios | **new** |
| `obsidian-recap/src/api.test.ts` (or equivalent) | `DaemonError.body` JSON parsing | extended |

### 6.2 Representative coverage

**`tests/test_attach.py`** — per-helper unit tests:

Classifier: sidecar unscheduled → normal; same event_id → noop_candidate; different real id → AttachAlreadyBoundError.

Body-merge: empty body → no Pre-Meeting; `## Agenda\n` + empty → no Pre-Meeting; `## Agenda\n` + content → Pre-Meeting Notes with content; unexpected shape → whole body under Pre-Meeting Notes; source body always preserved verbatim.

Frontmatter-merge: stub keys kept, source keys overlaid, unscheduled tag removed, pipeline-status from source (includes replace-path test where stub is "complete" + source is "partial" → result "partial").

Full orchestration:
- Normal bind happy path.
- No-op retry with sidecar already bound; cleanup fires on orphans.
- `AttachAlreadyBoundError` on different real event_id.
- `AttachConflictError` on different recording + replace=false.
- Replace path: skips conflict check, old artifacts remain on disk (assertion).
- `AttachNotFoundError` on stem/sidecar/event_id unresolvable.
- Cross-org + date-outside-window → ValueError.
- Synthetic event_id as requested target → ValueError (orchestrator-level guard).

**`tests/test_artifacts.py` extensions:**
- `write_recording_metadata` uses temp+replace.
- Cleans up temp on OSError.
- Roundtrip (write-then-load identity).
- `rebind_recording_metadata_to_event` rewrites all five fields.
- Raises ValueError on missing sidecar.

**`tests/test_daemon_server.py::TestApiAttachEvent`:** 401, 400 invalid stem, 400 missing event_id, 400 synthetic event_id guard, 400 bad JSON / not object, 404 stem/sidecar/event unresolvable, 400 already-bound-to-other, 400 cross-org, 400 date-out-of-window, 409 recording_conflict, 200 happy path (stem path), 200 happy path (replace=true), 200 no-op (sidecar already bound), 500 on merged-note write mock, 500 on sidecar rewrite mock.

**`tests/test_attach_integration.py`** — 4 end-to-end scenarios:
1. Happy path untouched stub: merged note correct, unscheduled gone, EventIndex cleaned.
2. User-edited stub: Pre-Meeting Notes section present.
3. Replace path: old recording's artifacts remain on disk.
4. Retry after partial-success: pre-seed crash state, re-POST, no-op cleanup heals both orphans.

**`obsidian-recap/src/api.test.ts`** extensions: 409/400/500 with JSON body → `err.body` parsed; 500 with non-JSON text → `err.body` undefined, `err.message` has the raw text; network failure → raw Error, NOT `DaemonError` (matches current client behavior).

### 6.3 Manual acceptance (`docs/handoffs/YYYY-MM-DD-33-acceptance.md`)

9 scenarios:
1. Command visible on unscheduled notes, hidden on scheduled notes.
2. Picker shows calendar events within ±1 day; no `unscheduled:` events.
3. Happy-path bind on untouched stub.
4. Happy-path bind on user-edited stub (Pre-Meeting Notes preserved).
5. Conflict path: 409 → Replace modal → Replace confirms.
6. Conflict Cancel path → nothing changes.
7a. Duplicate POST/retry after success via CLI → 200 {noop: true}.
7b. Retry after simulated partial success → 200 {noop: true, cleanup_performed: true}; orphans healed.
8. No candidate events → friendly notice.
9. Calendar sync during bind → eventual consistency; attach's write wins (documented race).

### 6.4 Out of scope

- Browser integration tests.
- Load testing.
- Fuzz tests on body-merge heuristic.

### 6.5 Desired-capability coverage

| Capability | Covered by |
|---|---|
| User-facing re-bind action | Section 3 command + picker |
| API surface `POST /api/recordings/{stem}/attach-event` | Section 4.1 + Section 6.2 endpoint tests |
| Atomic-style rewrite of frontmatter + EventIndex + note merge | Section 4.2 orchestration + Section 6.2 helper tests |
| Auto-reconcile suggestion on calendar sync | **Out of scope v1** |

---

## References

- Issue: [#33](https://github.com/TimSimpsonJr/recap/issues/33)
- Prerequisite (merged): #27 / PR #34 (unscheduled meetings)
- Follow-up: [#39](https://github.com/TimSimpsonJr/recap/issues/39) (merge multiple recordings)
- Related: #28 speaker correction (merged PR #38) — established the pattern of atomic sidecar writes used here
