# Phase 5b: Wire Frontend to Real Backend Data — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace all dummy data paths with real Tauri IPC calls, add pipeline dot indicators to meeting cards, and wire settings changes to store invalidation.

**Architecture:** The stores (`meetings.ts`) and IPC wrappers (`tauri.ts`) already call real backend commands when `USE_DUMMY_DATA` is false. Main work is: pipeline dot indicators on meeting cards, search debounce, settings→store reactivity, and actionable error states. Minimal new files — mostly modifications to existing components.

**Tech Stack:** Svelte 5, Tauri v2 IPC (`@tauri-apps/api/core`), `tauri-plugin-store`, d3-force (existing)

---

### Task 1: Add reset function to meetings store

The settings store needs to trigger a meetings reload when paths change. Add a `resetMeetings()` export and a graph data store.

**Files:**
- Modify: `src/lib/stores/meetings.ts`

**Step 1: Add reset and graph store exports**

Add these functions after the existing `destroyMeetingsListener` function at line 261:

```typescript
/** Reset meetings state and reload. Called when settings paths change. */
export async function resetMeetings(): Promise<void> {
  meetings.set({ ...initial });
  activeFilters.set({ ...initialFilters });
  filterOptions.set({ companies: [], participants: [], platforms: [] });
  await loadMeetings();
  await loadFilterOptions();
}
```

**Step 2: Verify the store compiles**

Run: `cd "C:\Users\tim\OneDrive\Documents\Projects\recap" && npx tsc --noEmit`
Expected: No new type errors

**Step 3: Commit**

```bash
git add src/lib/stores/meetings.ts
git commit -m "feat(stores): add resetMeetings for settings change reactivity"
```

---

### Task 2: Wire settings changes to store invalidation

When the user changes `recordingsFolder` or `vaultPath` in Settings, the meetings list and filters should refresh.

**Files:**
- Modify: `src/routes/Settings.svelte`

**Step 1: Read Settings.svelte to find the save handlers**

Read `src/routes/Settings.svelte` and locate where `saveSetting` or `saveAllSettings` is called for `recordingsFolder` and `vaultPath`.

**Step 2: Import resetMeetings and call it after path changes**

At the top of Settings.svelte `<script>`, add:

```typescript
import { resetMeetings } from "../lib/stores/meetings";
```

In each save handler for `recordingsFolder` and `vaultPath`, add a call to `resetMeetings()` after the `saveSetting()` call:

```typescript
await saveSetting("recordingsFolder", value);
await resetMeetings();
```

```typescript
await saveSetting("vaultPath", value);
await resetMeetings();
```

**Step 3: Verify it compiles**

Run: `npx tsc --noEmit`
Expected: No new type errors

**Step 4: Commit**

```bash
git add src/routes/Settings.svelte
git commit -m "feat(settings): reload meetings when recordings/vault paths change"
```

---

### Task 3: Add search debounce to Dashboard

Currently search fires on every keystroke. Add 300ms debounce.

**Files:**
- Modify: `src/routes/Dashboard.svelte`

**Step 1: Add debounce to the search handler**

Replace the `handleSearch` function (line 63-69) with:

```typescript
let searchTimer: ReturnType<typeof setTimeout> | null = null;

function handleSearch(query: string) {
  if (searchTimer) clearTimeout(searchTimer);
  if (!query.trim()) {
    clearSearch();
    return;
  }
  searchTimer = setTimeout(() => {
    search(query.trim());
  }, 300);
}
```

Add cleanup in `onDestroy`:

```typescript
onDestroy(() => {
  destroyRecorderListener();
  destroyMeetingsListener();
  if (searchTimer) clearTimeout(searchTimer);
});
```

**Step 2: Verify it compiles**

Run: `npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add src/routes/Dashboard.svelte
git commit -m "feat(dashboard): add 300ms debounce to meeting search"
```

---

### Task 4: Add pipeline dot indicators to MeetingRow

Replace the single `PipelineStatusBadge` on meeting cards with a row of 6 colored dots showing each pipeline stage.

**Files:**
- Create: `src/lib/components/PipelineDots.svelte`
- Modify: `src/lib/components/MeetingRow.svelte`

**Step 1: Create PipelineDots component**

```svelte
<script lang="ts">
  import type { PipelineStatus } from "../tauri";

  interface Props {
    status: PipelineStatus;
  }

  let { status }: Props = $props();

  const stages = ["merge", "frames", "transcribe", "diarize", "analyze", "export"] as const;

  function dotColor(stage: typeof stages[number]): string {
    const s = status[stage];
    if (s.error) return "#D06850";      // failed — red
    if (s.completed) return "#A8A078";   // done — accent gold
    return "#464440";                     // pending — muted
  }

  function dotTitle(stage: typeof stages[number]): string {
    const s = status[stage];
    if (s.error) return `${stage}: ${s.error}`;
    if (s.completed) return `${stage}: done`;
    return `${stage}: pending`;
  }
</script>

<div
  class="flex items-center gap-1"
  title="Pipeline status"
  role="img"
  aria-label="Pipeline progress: {stages.map(s => `${s} ${status[s].completed ? 'complete' : status[s].error ? 'failed' : 'pending'}`).join(', ')}"
>
  {#each stages as stage}
    <span
      style="
        display: inline-block;
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: {dotColor(stage)};
        flex-shrink: 0;
      "
      title={dotTitle(stage)}
    ></span>
  {/each}
</div>
```

**Step 2: Replace PipelineStatusBadge with PipelineDots in MeetingRow**

In `src/lib/components/MeetingRow.svelte`, change the import (line 3):

```typescript
// Old:
import PipelineStatusBadge from "./PipelineStatusBadge.svelte";
// New:
import PipelineDots from "./PipelineDots.svelte";
```

Replace the component usage (line 103):

```svelte
<!-- Old: -->
<PipelineStatusBadge status={meeting.pipeline_status} />
<!-- New: -->
<PipelineDots status={meeting.pipeline_status} />
```

**Step 3: Verify it compiles**

Run: `npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add src/lib/components/PipelineDots.svelte src/lib/components/MeetingRow.svelte
git commit -m "feat(ui): replace pipeline badge with dot indicators on meeting cards"
```

---

### Task 5: Add expandable pipeline detail to PipelineDots

Make the dots clickable to expand an inline detail panel showing stage names, timestamps, errors, and retry buttons.

**Files:**
- Modify: `src/lib/components/PipelineDots.svelte`

**Step 1: Add expandable detail**

Rewrite `PipelineDots.svelte` to add click-to-expand behavior:

```svelte
<script lang="ts">
  import type { PipelineStatus } from "../tauri";
  import { retryProcessing } from "../tauri";

  interface Props {
    status: PipelineStatus;
    recordingPath?: string | null;
  }

  let { status, recordingPath = null }: Props = $props();

  let expanded = $state(false);
  let retrying = $state<string | null>(null);

  const stages = ["merge", "frames", "transcribe", "diarize", "analyze", "export"] as const;

  function dotColor(stage: typeof stages[number]): string {
    const s = status[stage];
    if (s.error) return "#D06850";
    if (s.completed) return "#A8A078";
    return "#464440";
  }

  function dotTitle(stage: typeof stages[number]): string {
    const s = status[stage];
    if (s.error) return `${stage}: ${s.error}`;
    if (s.completed) return `${stage}: done`;
    return `${stage}: pending`;
  }

  function statusIcon(stage: typeof stages[number]): string {
    const s = status[stage];
    if (s.error) return "\u2717";   // cross mark
    if (s.completed) return "\u2713"; // check mark
    return "\u2022";                  // bullet
  }

  function formatTimestamp(ts: string | null): string {
    if (!ts) return "";
    try {
      return new Date(ts).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
    } catch {
      return "";
    }
  }

  async function retryFrom(stage: string) {
    if (!recordingPath || retrying) return;
    retrying = stage;
    try {
      await retryProcessing(recordingPath, stage);
    } catch (e) {
      console.error("Retry failed:", e);
    } finally {
      retrying = null;
    }
  }

  function handleDotsClick(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    expanded = !expanded;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      expanded = !expanded;
    }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div style="display: flex; flex-direction: column; align-items: flex-end;">
  <button
    class="dots-row"
    onclick={handleDotsClick}
    onkeydown={handleKeydown}
    title="Click to {expanded ? 'collapse' : 'expand'} pipeline details"
    aria-expanded={expanded}
    aria-label="Pipeline progress: {stages.map(s => `${s} ${status[s].completed ? 'complete' : status[s].error ? 'failed' : 'pending'}`).join(', ')}"
  >
    {#each stages as stage}
      <span
        class="dot"
        style="background: {dotColor(stage)};"
        title={dotTitle(stage)}
      ></span>
    {/each}
  </button>

  {#if expanded}
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div
      class="pipeline-detail"
      onclick={(e) => e.stopPropagation()}
    >
      {#each stages as stage}
        {@const s = status[stage]}
        <div class="stage-row">
          <span class="stage-icon" style="color: {dotColor(stage)};">{statusIcon(stage)}</span>
          <span class="stage-name">{stage}</span>
          {#if s.completed && s.timestamp}
            <span class="stage-time">{formatTimestamp(s.timestamp)}</span>
          {/if}
          {#if s.error}
            <span class="stage-error">{s.error}</span>
            {#if recordingPath}
              <button
                class="retry-btn"
                onclick={() => retryFrom(stage)}
                disabled={retrying !== null}
              >
                {retrying === stage ? "..." : "Retry"}
              </button>
            {/if}
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .dots-row {
    display: flex;
    align-items: center;
    gap: 3px;
    padding: 4px 6px;
    border-radius: 4px;
    border: none;
    background: transparent;
    cursor: pointer;
    transition: background 120ms ease;
  }

  .dots-row:hover {
    background: rgba(168, 160, 120, 0.08);
  }

  .dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .pipeline-detail {
    margin-top: 6px;
    padding: 8px 10px;
    border-radius: 6px;
    background: #1A1A18;
    font-family: 'DM Sans', sans-serif;
    font-size: 12px;
    min-width: 200px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .stage-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .stage-icon {
    font-size: 11px;
    width: 14px;
    text-align: center;
    flex-shrink: 0;
  }

  .stage-name {
    color: #B0ADA5;
    font-weight: 500;
    min-width: 70px;
  }

  .stage-time {
    color: #585650;
    font-size: 11px;
  }

  .stage-error {
    color: #D06850;
    font-size: 11px;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .retry-btn {
    padding: 1px 8px;
    border-radius: 4px;
    border: none;
    background: rgba(200, 80, 60, 0.15);
    color: #D06850;
    font-family: 'DM Sans', sans-serif;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    flex-shrink: 0;
  }

  .retry-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }
</style>
```

**Step 2: Pass recordingPath to PipelineDots in MeetingRow**

In `MeetingRow.svelte`, update the PipelineDots usage:

```svelte
<PipelineDots status={meeting.pipeline_status} recordingPath={meeting.recording_path} />
```

**Step 3: Verify it compiles**

Run: `npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add src/lib/components/PipelineDots.svelte src/lib/components/MeetingRow.svelte
git commit -m "feat(ui): add expandable pipeline stage detail to dot indicators"
```

---

### Task 6: Improve error states with actionable messages

Add clear error messages when settings aren't configured, with links to Settings.

**Files:**
- Modify: `src/routes/Dashboard.svelte`
- Modify: `src/routes/GraphView.svelte`

**Step 1: Add configure-settings banner to Dashboard**

In `Dashboard.svelte`, after the existing error block (line 171-183), add a no-recordings-dir banner. Read the settings store to detect unconfigured state.

Add import at top:
```typescript
import { settings } from "../lib/stores/settings";
```

After the error div (line 183), add:

```svelte
{#if !$settings.recordingsFolder}
  <div
    class="mt-4 p-4 rounded-lg"
    style="
      background: rgba(180,165,130,0.08);
      font-family: 'DM Sans', sans-serif;
      font-size: 14.5px;
      color: #B4A882;
      text-align: center;
    "
  >
    <p style="margin: 0 0 8px 0;">No recordings folder configured</p>
    <a
      href="#settings"
      style="
        color: #A8A078;
        text-decoration: underline;
        font-weight: 600;
      "
    >
      Configure in Settings
    </a>
  </div>
{/if}
```

**Step 2: Add same pattern to GraphView**

In `GraphView.svelte`, the error state already shows "No recordings folder configured" (line 431). Make it a clickable link to Settings:

Replace lines 511-512:
```svelte
<!-- Old: -->
<div class="graph-message graph-error">{error}</div>
<!-- New: -->
<div class="graph-message graph-error">
  {error}
  {#if error?.includes("No recordings folder")}
    <br />
    <a href="#settings" style="color: #A8A078; text-decoration: underline; font-weight: 600; margin-top: 8px; display: inline-block;">
      Configure in Settings
    </a>
  {/if}
</div>
```

**Step 3: Verify it compiles**

Run: `npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add src/routes/Dashboard.svelte src/routes/GraphView.svelte
git commit -m "feat(ui): add actionable error states with Settings links"
```

---

### Task 7: Verify real IPC path end-to-end

Confirm that with `VITE_DUMMY_DATA` unset (or set to false), the app correctly calls IPC and handles empty/error responses gracefully.

**Files:**
- Modify: `.env.development` (temporarily)

**Step 1: Disable dummy data**

In `.env.development`, comment out or set to false:

```
# VITE_DUMMY_DATA=true
VITE_DUMMY_DATA=false
```

**Step 2: Start the dev server**

Run: `cd "C:\Users\tim\OneDrive\Documents\Projects\recap" && npm run tauri dev`

**Step 3: Verify behaviors**

Check each view manually:
- **Dashboard:** Should show "No recordings folder configured" banner (or empty list if folder is set but empty)
- **Graph:** Should show appropriate error/empty message
- **Settings:** Should load and save without errors
- **Search:** Should debounce (type quickly, only one IPC call)
- **Filter sidebar:** Should show empty filter options (no recordings to scan)

**Step 4: Restore dummy data and commit**

Set `.env.development` back:
```
VITE_DUMMY_DATA=true
```

No code changes to commit from this task — it's a verification step.

---

### Task 8: Wire PipelineDots into DetailPanel

The DetailPanel already shows `PipelineStatusBadge` — replace it with `PipelineDots` for consistency.

**Files:**
- Modify: `src/lib/components/DetailPanel.svelte`

**Step 1: Replace badge with dots in DetailPanel**

Change the import (line 12):
```typescript
// Old:
import PipelineStatusBadge from "./PipelineStatusBadge.svelte";
// New:
import PipelineDots from "./PipelineDots.svelte";
```

Replace the usage (line 109):
```svelte
<!-- Old: -->
<PipelineStatusBadge status={detail.summary.pipeline_status} />
<!-- New: -->
<PipelineDots status={detail.summary.pipeline_status} recordingPath={detail.summary.recording_path} />
```

**Step 2: Verify it compiles**

Run: `npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add src/lib/components/DetailPanel.svelte
git commit -m "feat(detail): use pipeline dots in detail panel for consistency"
```

---

### Task 9: Verify type alignment between frontend and backend

Confirm that all TypeScript interfaces in `tauri.ts` match the actual Rust struct serialization.

**Files:**
- Read: `src/lib/tauri.ts`
- Read: `src-tauri/src/meetings.rs`
- Read: `src-tauri/src/recorder/types.rs`

**Step 1: Compare TypeScript types to Rust structs**

Read `src-tauri/src/meetings.rs` and `src-tauri/src/recorder/types.rs`. For each Rust struct with `#[derive(Serialize)]`, verify the TypeScript interface in `tauri.ts` has matching field names (Rust uses snake_case, Tauri serializes to camelCase by default unless `#[serde(rename_all = "snake_case")]` is used — check which convention is in use).

**Step 2: Fix any mismatches**

If any fields are missing or named differently, update `tauri.ts` to match. Pay special attention to:
- `PipelineStatus` and `PipelineStageStatus` (field names)
- `MeetingSummary` (all optional fields)
- `RecorderState` (enum variant serialization)

**Step 3: Commit any fixes**

```bash
git add src/lib/tauri.ts
git commit -m "fix(types): align TypeScript interfaces with Rust struct serialization"
```

If no fixes needed, skip this commit.

---

### Task 10: Final integration test and cleanup

Run the full app with dummy data enabled and verify all changes work together.

**Files:**
- No modifications expected

**Step 1: Run the dev server**

```bash
cd "C:\Users\tim\OneDrive\Documents\Projects\recap" && npm run tauri dev
```

**Step 2: Test each feature**

- [ ] Meeting list loads with dummy data
- [ ] Pipeline dots appear on each meeting card (6 dots, colored by stage)
- [ ] Clicking dots expands stage detail inline
- [ ] Retry buttons appear for failed stages in expanded detail
- [ ] Search debounces (type quickly, results don't flicker)
- [ ] Detail panel shows pipeline dots instead of badge
- [ ] Graph view loads
- [ ] Filter sidebar works
- [ ] Settings page loads, changing recordings folder triggers meetings reload

**Step 3: Run type check**

```bash
npx tsc --noEmit
```

Expected: No errors

**Step 4: Commit if any final tweaks needed**

---

### Summary

| Task | Description | New Files | Modified Files |
|------|-------------|-----------|----------------|
| 1 | Reset function in meetings store | — | `meetings.ts` |
| 2 | Settings→store reactivity | — | `Settings.svelte` |
| 3 | Search debounce | — | `Dashboard.svelte` |
| 4 | Pipeline dots component | `PipelineDots.svelte` | `MeetingRow.svelte` |
| 5 | Expandable dot detail | — | `PipelineDots.svelte`, `MeetingRow.svelte` |
| 6 | Actionable error states | — | `Dashboard.svelte`, `GraphView.svelte` |
| 7 | End-to-end IPC verification | — | `.env.development` (temp) |
| 8 | Detail panel dots | — | `DetailPanel.svelte` |
| 9 | Type alignment check | — | `tauri.ts` (if needed) |
| 10 | Integration test | — | — |
