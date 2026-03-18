# Phase 5a: Dashboard UI Design

## Scope

Build the main dashboard window for Recap — call history list, meeting detail view with notes/transcript/playback, and manual recording controls. Calendar integration (upcoming meetings) is deferred to Phase 5b.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Rust-heavy backend (Approach A) | Consistent with existing IPC patterns, clean security model |
| Data source | Filesystem scanning via Rust IPC | No database. Recordings folder is the source of truth |
| Video player | Vidstack | Polished player UI out of the box, handles audio-only gracefully |
| Detail view content | Two tabs: Notes + Transcript | Notes shows rendered vault markdown, Transcript shows timestamped utterances |
| Markdown rendering | `marked` + custom wikilink plugin | Lightweight, handles `[[wikilinks]]` and `![[embeds]]` |
| Asset serving | Tauri asset protocol | Configure `assetScope` for recordings, vault meetings, and frames folders |
| Pagination | Cursor-based, 50 per page | Supports large recording collections without performance issues |

## Pipeline Change: Preserve Metadata

The pipeline currently leaves `meeting.json` and `status.json` in the temp working directory. Phase 5a requires a small pipeline change: **copy both files to the recordings folder** alongside the recording and transcript, using the same `{date}-{slug}` naming convention.

After pipeline completion, the recordings folder contains per meeting:
```
2026-03-16-acme-kickoff.mp4
2026-03-16-acme-kickoff.transcript.json
2026-03-16-acme-kickoff.meeting.json
2026-03-16-acme-kickoff.status.json
```

This makes the recordings folder self-describing — no vault dependency for the dashboard to list meetings.

## Data Layer (Rust)

### New module: `src-tauri/src/meetings.rs`

**Data structures:**

```rust
MeetingSummary {
    id: String,                    // filename stem, e.g. "2026-03-16-acme-kickoff"
    title: String,                 // from meeting.json
    date: String,                  // ISO date
    platform: String,              // "zoom", "teams", etc.
    participants: Vec<String>,     // participant names
    duration_seconds: Option<f64>,
    pipeline_status: PipelineStatus,
    has_note: bool,
    has_transcript: bool,
    has_video: bool,
    recording_path: Option<String>,
    note_path: Option<String>,
}

MeetingDetail {
    summary: MeetingSummary,
    note_content: Option<String>,        // raw markdown from vault note
    transcript: Option<Vec<Utterance>>,  // parsed transcript JSON
    screenshots: Vec<Screenshot>,
}

Utterance { speaker: String, start: f64, end: f64, text: String }
Screenshot { path: String, caption: Option<String> }
```

**IPC commands:**

| Command | Params | Returns | Description |
|---------|--------|---------|-------------|
| `list_meetings` | recordings_dir, vault_meetings_dir, cursor?, limit? | `{ items: Vec<MeetingSummary>, next_cursor: Option<String> }` | Scan recordings folder, sorted by date desc, paginated |
| `get_meeting_detail` | meeting_id, recordings_dir, vault_meetings_dir, frames_dir | `MeetingDetail` | Full data for one meeting |
| `search_meetings` | query, recordings_dir, vault_meetings_dir, limit? | `Vec<MeetingSummary>` | Substring match on title/participants |

Commands take directory paths from the frontend (read from settings store) to remain stateless.

**Correlation logic:** `list_meetings` scans the recordings folder for `.meeting.json` files. For each, it checks if a matching vault note exists by looking for `{date} - {title}.md` in the vault meetings folder. Recordings without `.meeting.json` are included with metadata derived from the filename.

## Dashboard Layout

### List View (`#dashboard`)

```
┌─────────────────────────────────────────────────────┐
│ [RecordingStatusBar - shown only when recording]     │
│  ● Recording: Zoom Meeting  00:23:45  [Stop] [Cancel]│
├─────────────────────────────────────────────────────┤
│ Recap                                    [Settings ⚙]│
│                                                      │
│ [Search meetings...                               🔍]│
│                                                      │
│ ┌─────────────────────────────────────────────────┐  │
│ │ 📅 2026-03-16  Project Kickoff with Acme Corp   │  │
│ │ Zoom · 45m · 3 participants     ✅ Completed    │  │
│ ├─────────────────────────────────────────────────┤  │
│ │ 📅 2026-03-15  Weekly Standup                   │  │
│ │ Zoom · 30m · 5 participants     ⏳ Processing   │  │
│ ├─────────────────────────────────────────────────┤  │
│ │ 📅 2026-03-14  Client Review                    │  │
│ │ Zoom · 60m · 2 participants     ❌ Failed: transcribe │
│ └─────────────────────────────────────────────────┘  │
│                                                      │
│ [Load more]                                          │
└─────────────────────────────────────────────────────┘
```

### Detail View (`#meeting/{id}`)

```
┌─────────────────────────────────────────────────────┐
│ ← Back to Dashboard                      [Settings ⚙]│
│                                                      │
│ Project Kickoff with Acme Corp                       │
│ 2026-03-16 · Zoom · 45m · Jane Smith, Bob Jones      │
│                                                      │
│ [RetryBanner - shown if pipeline failed]             │
│  ⚠ Pipeline failed at transcribe. [Re-transcribe]   │
│                                                      │
│ ┌─────────────────────────────────────────────────┐  │
│ │              Vidstack Player                     │  │
│ │         (or audio-only placeholder)              │  │
│ └─────────────────────────────────────────────────┘  │
│                                                      │
│ [Notes] [Transcript]                                 │
│ ┌─────────────────────────────────────────────────┐  │
│ │ ## Summary                                      │  │
│ │ Discussed Q3 roadmap and budget allocation...   │  │
│ │                                                 │  │
│ │ ## Key Points                                   │  │
│ │ - Infrastructure modernization timeline...      │  │
│ │                                                 │  │
│ │ ## Action Items                                 │  │
│ │ - [ ] Tim: Send proposal by Friday              │  │
│ └─────────────────────────────────────────────────┘  │
│                                                      │
│ Screenshots                                          │
│ ┌──────┐ ┌──────┐ ┌──────┐                          │
│ │ img1 │ │ img2 │ │ img3 │                          │
│ └──────┘ └──────┘ └──────┘                          │
└─────────────────────────────────────────────────────┘
```

## Component Structure

```
src/routes/
  Dashboard.svelte              # List view — manages pagination, search state
  MeetingDetail.svelte          # Detail view — fetches detail, coordinates player/transcript

src/lib/components/
  MeetingList.svelte            # Scrollable list of MeetingRow items
  MeetingRow.svelte             # Single row: title, date, status badge, platform icon
  SearchBar.svelte              # Debounced text input, emits search query
  RecordingStatusBar.svelte     # Active recording: red dot, timer, stop/cancel
  PipelineStatusBadge.svelte    # Colored badge: completed / processing / failed
  RetryBanner.svelte            # Failed pipeline banner with contextual retry buttons
  MeetingHeader.svelte          # Detail header: title, metadata
  MeetingPlayer.svelte          # Vidstack wrapper, exposes seek(time) method
  MeetingNotes.svelte           # Renders vault markdown via marked + wikilink plugin
  MeetingTranscript.svelte      # Scrollable utterances, clickable timestamps emit seek events
  ScreenshotGallery.svelte      # Grid of screenshots with captions

src/lib/stores/
  meetings.ts                   # Wraps list/search IPC, manages pagination state
  recorder.ts                   # Subscribes to recorder-state-changed events

src/lib/tauri.ts                # Add typed wrappers for new IPC commands
src/lib/assets.ts               # assetUrl(path) — converts local paths to asset:// URLs
src/lib/markdown.ts             # marked config + wikilink/embed tokenizer
```

**Key interactions:**
- `MeetingTranscript` emits `seek` event on timestamp click → `MeetingDetail` calls `MeetingPlayer.seek(time)`
- `RecordingStatusBar` subscribes to `recorder-state-changed` Tauri events, calls `start_recording`/`stop_recording`/`cancel_recording` IPC
- `RetryBanner` calls `retry_processing` IPC with appropriate `from_stage` based on which stage failed or which output is missing
- Pipeline completion emits `pipeline-completed` event → `meetings` store auto-refreshes the list

## Asset Protocol Configuration

Add asset scope to `tauri.conf.json` allowing the webview to serve local files:
- Recordings folder (from settings: `recordingsFolder`)
- Vault meetings folder (derived from `vaultPath` + `meetingsFolder`)
- Frames folder (derived from `recordingsFolder` or configured separately)

The frontend utility `assetUrl(path)` converts a local path like `C:\Users\tim\...\recording.mp4` to `asset://localhost/C:/Users/tim/.../recording.mp4`.

Note: The asset scope paths are dynamic (user-configured), so we need to use Tauri's runtime scope modification or configure a broad-enough scope at build time. If runtime scope modification isn't feasible, we scope to the user's home directory or use `convertFileSrc` from `@tauri-apps/api`.

## Edge Cases

| # | Edge Case | Handling |
|---|-----------|----------|
| 1 | Pipeline crashes mid-run | Failed badge with stage name. "Retry from [stage]" button via `retry_processing` IPC |
| 2 | Pipeline running when dashboard opens | "Processing" badge with spinner. Auto-refresh on `pipeline-completed` event |
| 3 | Recording in progress | RecordingStatusBar at top of list. Meeting not in list yet (in temp dir) |
| 4 | User deletes recording file | Absent from next scan. No error, no orphan |
| 5 | User edits vault note | Notes tab renders current file content. No conflict detection |
| 6 | Recording with no meeting.json | Derive title from filename. "Unknown" platform, empty participants |
| 7 | meeting.json but no recording file | Show metadata, disable player. "Recording file not found" message |
| 8 | Missing or malformed transcript | Transcript tab: "Transcript unavailable." Show "Re-transcribe" button if recording file exists — calls `retry_processing` with `from_stage: "transcribe"` |
| 9 | No vault note | Notes tab: "No meeting note generated." Show "Generate Note" button if recording exists — calls `retry_processing` with `from_stage: "analyze"` (or `"export"` if analysis already completed per status.json) |
| 10 | Zero recordings | Empty state: "No meetings recorded yet. Start a Zoom call and Recap will detect it automatically." |
| 11 | Large number of recordings | Cursor-based pagination, 50 per page, "Load more" button |
| 12 | Long meeting title | Truncate with ellipsis in list row, full title in detail header |
| 13 | Audio-only recording (no video) | Vidstack renders in audio mode. Show simple placeholder instead of black frame |

## New Dependencies

| Package | Purpose | Size |
|---------|---------|------|
| `vidstack` | Video/audio player | ~50KB |
| `marked` | Markdown → HTML rendering | ~30KB |

## Out of Scope (Phase 5b+)

- Calendar polling / upcoming meetings display
- Speaker correction UI (reassigning diarization labels)
- Real-time pipeline progress (stage-by-stage updates during processing)
- Bulk operations (delete multiple recordings, reprocess all failed)
