# Phase 5b: Wire Frontend to Real Backend Data

## Overview

Connect existing Svelte frontend components to the Rust backend IPC commands that already exist. Replace all dummy data paths with real IPC calls, add error handling for missing/broken data, and surface pipeline progress on meeting cards.

No new backend commands needed — all IPC endpoints are implemented.

## Scope

- Meetings store → real IPC (list, detail, search, filters, graph)
- Asset protocol for recordings, vault notes, screenshots
- Settings change reactivity
- Error states for missing/misconfigured paths
- Pipeline progress dot indicators (Approach C)
- Dummy data preserved behind `VITE_DUMMY_DATA` env var

## Meetings Store Wiring

### list_meetings

Replace `DUMMY_MEETINGS` with `invoke('list_meetings', { recordingsDir, vaultMeetingsDir, cursor, limit })`.

Response: `MeetingListResponse { items: Vec<MeetingSummary>, next_cursor?: String }`

- Initial load: no cursor, limit 25
- "Load more" button appears when `next_cursor` is present
- Appends to existing list (no full re-fetch)

### get_meeting_detail

Replace `getDummyDetail()` with `invoke('get_meeting_detail', { meetingId, recordingsDir, vaultMeetingsDir, framesDir })`.

Response: `MeetingDetail { summary, note_content?, transcript?: Vec<Utterance>, screenshots: Vec<Screenshot> }`

- DetailPanel and MeetingDetail both use this
- Missing note → show "Generate Note" button
- Missing transcript → show "Re-transcribe" button

### search_meetings

Replace client-side dummy filtering with `invoke('search_meetings', { query, recordingsDir, vaultMeetingsDir, limit })`.

- Debounced input (300ms)
- Replaces meeting list with search results
- Clear search restores paginated list

### get_filter_options

Replace `DUMMY_FILTER_OPTIONS` with `invoke('get_filter_options', { recordingsDir })`.

Response: `FilterOptions { companies, participants, platforms }`

- Populates FilterSidebar checkboxes
- Refreshed when recordings dir changes in Settings
- Client-side filtering against loaded meeting list (filters don't trigger new IPC calls)

### get_graph_data

Replace `DUMMY_GRAPH_DATA` with `invoke('get_graph_data', { recordingsDir })`.

Response: `GraphData { nodes: Vec<GraphNode>, edges: Vec<GraphEdge> }`

- GraphView consumes directly
- GraphSidebar filtered lists use client-side filtering of loaded meetings

## Asset Protocol

Already wired via `src/lib/assets.ts` → `convertFileSrc()` from `@tauri-apps/api/core`.

Asset scope in `tauri.conf.json`: `["**/*"]` (permissive).

Usage points:
- **Recording playback:** `MeetingPlayer.svelte` passes `assetUrl(recording_path)` to Vidstack `<media-player>`
- **Vault note rendering:** `DetailPanel.svelte` receives `note_content` as string from `get_meeting_detail` (backend reads the file), so no direct asset URL needed
- **Frame screenshots:** `Screenshot.path` → `assetUrl(path)` for `<img>` tags in detail panel

No changes needed to asset protocol configuration.

## Settings Change Reactivity

When user changes recordings dir or vault path in Settings:

1. Settings store saves new values via `tauri-plugin-store`
2. Meetings store exposes a `reset()` method that clears cached data and cursor
3. Settings save calls `meetingsStore.reset()`
4. Components that subscribe to the meetings store re-fetch on next render
5. Filter options and graph data also invalidated

Simple invalidation — no caching layer needed for Phase 5b.

## Error Handling

### Store-level errors

Each store tracks an `error` state alongside its data:

```typescript
{ data: Meeting[] | null, loading: boolean, error: string | null }
```

### Error states by scenario

| Scenario | Detection | UI |
|---|---|---|
| Recordings dir not configured | Settings store check | "Configure recordings directory in Settings" banner |
| Vault path not configured | Settings store check | "Configure vault path in Settings" banner |
| Recordings dir doesn't exist | IPC returns error | "Recordings directory not found" with Settings link |
| IPC call fails (generic) | Catch in store | Inline error message with "Retry" button |
| Individual meeting missing files | `has_note`, `has_transcript`, `has_video` flags on `MeetingSummary` | Per-card indicators + action buttons in detail |
| Empty results | Items array empty | "No meetings found" empty state |

## Pipeline Progress UI (Approach C)

### Dot Indicators on Meeting Cards

Each `MeetingSummary` includes `pipeline_status: PipelineStatus` with six stages: merge, frames, transcribe, diarize, analyze, export.

Display as a row of 6 small dots on the meeting card:
- **Completed:** accent color (`--accent`)
- **Failed:** red (`--status-failed-text`)
- **Pending:** muted (`--text-faint`)
- **In progress:** accent with pulse animation

### Expandable Inline Detail

Click the dot row to expand a small section below the card showing:
- Stage names with status icons
- Timestamps for completed stages
- Error messages for failed stages
- Action buttons: "Retry from [stage]" for failed stages

### Edge Case Buttons

Surfaced in both the expanded dot detail and the DetailPanel:
- **Missing vault note + has recording:** "Generate Note" → `retry_processing(recording_dir, from_stage: "analyze")`
- **Missing/bad transcript + has recording:** "Re-transcribe" → `retry_processing(recording_dir, from_stage: "transcribe")`
- **All stages failed:** "Reprocess" → `retry_processing(recording_dir, from_stage: "merge")`

## Dummy Data Preservation

- `VITE_DUMMY_DATA=true` in `.env.development` continues to work
- Each store checks `USE_DUMMY_DATA` before making IPC calls
- Pattern: `if (USE_DUMMY_DATA) return dummyData; else return invoke(...)`
- Real data is the default when env var is absent or false

## Files Modified

- `src/lib/stores/meetings.ts` — real IPC calls, pagination, error states
- `src/routes/Dashboard.svelte` — error state rendering, settings check
- `src/lib/components/DetailPanel.svelte` — real detail loading, edge case buttons
- `src/lib/components/FilterSidebar.svelte` — real filter options
- `src/routes/GraphView.svelte` — real graph data
- `src/lib/components/GraphSidebar.svelte` — filtered from real data
- `src/lib/components/MeetingCard.svelte` — pipeline dot indicators (new)
- `src/lib/components/PipelineStatus.svelte` — expandable stage detail (new)
- `src/routes/Settings.svelte` — store reset on path changes
- `src/lib/tauri.ts` — verify type interfaces match actual backend responses
