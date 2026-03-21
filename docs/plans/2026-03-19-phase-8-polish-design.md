# Phase 8: Polish — Design

## Scope

Four feature areas: responsive layout, bulk operations, Todoist completion sync, and animation/UI polish. Light mode is out of scope.

---

## 1. Responsive Layout

### Breakpoints

- **Narrow (<900px):** Detail panel replaces meeting list entirely (full-width detail with back button). Filter sidebar collapses to icon-only strip. Nav bar switches to icon-only route links (no text labels). Onboarding wizard and search bar adapt to narrower padding.
- **Standard (900–1400px):** Current split behavior — 320px meeting list + detail panel.
- **Wide (>1400px):** MeetingDetail allows player side-by-side with transcript/tabs instead of vertical stacking.

### Split Panel Animation

Slow the `slide-in` keyframe from 200ms to 400ms with `cubic-bezier(0.4, 0, 0.2, 1)`. Apply the same easing to the `meeting-list-panel` flex transition.

### Settings Two-Column

At >1000px, settings sections flow into two columns. Platform connections (OAuth providers) become a collapsible dropdown with colored status dots (green = connected, gray = disconnected) instead of the current card grid.

### Graph View Resize

Force graph must handle window resize events — re-center simulation, adjust force parameters. Currently does not respond to resize.

### Calendar View

Audit and fix narrow-width overflow.

### Zoom Overflow Bug

A third scrollbar appears at zoomed-in sizes. Root cause: nested overflow containers. Fix by ensuring only the intended scroll containers (meeting list, detail panel) have `overflow-y: auto`, with outer wrappers set to `overflow: hidden`.

---

## 2. Bulk Operations

### Selection UX — Toggle Mode

A "Select" button in the meeting list toolbar enters multi-select mode:
- Checkboxes appear on each MeetingRow
- "Select" button becomes "Cancel"
- Detail panel closes (clicks now toggle checkboxes, not open detail)
- Shift+click selects a range of meetings
- "Select All" checkbox per date group header + global select-all in toolbar

When 1+ meetings are selected, a sticky bottom action bar slides up with: selected count + Reprocess / Fix Speakers / Delete buttons.

### Bulk Delete

Confirmation modal: "Delete N meetings? This removes recordings and all pipeline outputs." Rust handler `delete_meetings(ids: Vec<String>)` deletes meeting folders from disk. Toast notification on completion. Exits select mode and refreshes list.

### Bulk Reprocess

No confirmation needed. Rust handler `reprocess_meetings(ids: Vec<String>)` launches sidecar for each meeting sequentially. Progress via existing pipeline dots. Reprocess button disabled while any reprocessing is in-flight.

### Bulk Speaker Fix

Modal shows unique speaker labels across selected meetings (e.g., "SPEAKER_00 appears in 4 meetings"). User types the real name, clicks apply. Rust handler `bulk_rename_speaker(old_name: String, new_name: String, meeting_ids: Vec<String>)` updates all transcript files. Toast notification on completion.

### New IPC Commands

- `delete_meetings(ids: Vec<String>)` — delete meeting folders
- `reprocess_meetings(ids: Vec<String>)` — launch sidecar per meeting
- `bulk_rename_speaker(old_name: String, new_name: String, meeting_ids: Vec<String>)` — rename across transcripts

---

## 3. Todoist Completion Sync

### Project Structure

Group tasks by company/contact. When creating tasks, look up or create a Todoist project named `Recap: {company_name}`. Fallback to a configurable default project for meetings without a clear company.

Settings UI adds a "Project grouping" dropdown:
- Per company (default)
- Per meeting
- Single project (backward compatible with current behavior)

### Task ID Storage

After creating Todoist tasks, write `todoist_tasks.json` alongside the meeting's `status.json`:

```json
{
  "tasks": [
    {"todoist_id": "123456", "description": "Follow up with Acme on pricing", "project_id": "789"}
  ],
  "last_synced": "2026-03-19T14:30:00Z"
}
```

Separate from vault notes to avoid polluting Obsidian markdown. New tasks only — no backfill of existing tasks.

### Completion Sync

New `sync_completions()` function in `todoist.py`:
- Reads `todoist_tasks.json` for each meeting
- Fetches task status via Todoist API
- Completed tasks: `- [ ]` → `- [x]` in vault note, `completed_at` added to JSON
- Deleted tasks: `- [ ]` → `- [~]` (strikethrough) in vault note to distinguish from incomplete

### Sync Triggers

- **Auto sync:** Rust-side timer, configurable interval (default 15 min), calls sidecar with `--only todoist-sync`
- **Manual sync:** "Sync Now" button in TodoistSettings, shows last sync timestamp

### Rate Limiting

Batch Todoist API requests. Handle 429 responses with exponential backoff.

### Missing Vault Notes — Relink Flow

If a vault note is not found at its expected path during sync:
1. UI shows a "Relink Notes" banner with count
2. User clicks to locate one missing note via file picker
3. System checks if other missing notes exist in the same relative folder structure (like video editor relinking)
4. Auto-relinks matches, remaining unresolved notes stay in the relink list
5. Updated paths stored for future syncs

---

## 4. Animation & UI Polish

### Title Bar Integration

Remove default Tauri window decorations (`decorations: false`). Render custom title bar integrated with the nav bar:
- Logo SVG (concentric circles + three dots, using current theme gold `#C4A84D`) next to "Recap" text
- Custom minimize/maximize/close buttons on the right side of the nav bar
- Drag region on the nav bar for window movement

### Setup Checklist

- Add `setupChecklistDismissed` setting — once closed, never shows again
- Individual items animate out (fly/fade) when completed
- Items disappear from the list when checked off

### Pipeline Dots (MeetingDetail)

- Add text labels next to each stage dot
- Add a subtle chevron/caret indicating dropdown functionality exists

### Graph View

- Subtle CSS grid background with a bottom glow gradient
- Debug and fix center force (not working correctly)
- General force simulation tuning
- Replace settings icon (currently looks like a light mode toggle) with a proper gear/cog

### Route Transitions

Crossfade between pages (Dashboard, MeetingDetail, Calendar, GraphView, Settings).

### List Animations

Svelte `fly` transition on MeetingRow enter/exit during filter changes and new meetings appearing.

### Loading States

Skeleton loaders for meeting list and detail view while data loads.

### Button Micro-interactions

Subtle scale and background transitions on hover/press for all interactive elements.

### Toast Notification System

Slide-in from bottom-right, auto-dismiss after timeout. Used for bulk operation results, sync completion, errors.

### Filter Sidebar

Smooth expand/collapse animation instead of instant show/hide.

### Modal Transitions

Fade + scale-up entrance for all modals (bulk speaker fix, delete confirmation, provider card, etc.).

### Settings Info Popovers

Every dropdown/select in Settings gets a small info icon. On hover, shows a tooltip describing what the setting does.

---

## 5. Bug Fix: Calendar Sync

Calendar is not updating despite Zoho being connected. Debug and fix the Zoho calendar sync flow.

---

## Key Files

| Area | Primary Files |
|------|--------------|
| Responsive | `app.css`, `Dashboard.svelte`, `MeetingDetail.svelte`, `App.svelte`, `FilterSidebar.svelte` |
| Bulk Ops | `MeetingRow.svelte`, `MeetingList.svelte`, `Dashboard.svelte`, `meetings.rs`, `tauri.ts` |
| Todoist | `todoist.py`, `vault.py`, `TodoistSettings.svelte`, `models.py` |
| Animation/UI | `App.svelte`, `SetupChecklist.svelte`, `PipelineDots.svelte`, `GraphView.svelte`, `app.css` |
| Calendar Bug | `calendar.rs`, `App.svelte` |
