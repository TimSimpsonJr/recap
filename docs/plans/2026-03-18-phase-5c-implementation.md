# Phase 5c Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate to Recap Dark theme, add Zoho Calendar integration, implement speaker correction with pipeline pausing, and build pre-meeting briefing notifications via Claude CLI.

**Architecture:** Four independent workstreams sharing the same data layer. Theme migration touches ~30 files (mechanical color replacement). Calendar adds a Rust module + Svelte view. Speaker correction extends the pipeline status model across Python/Rust/TypeScript and adds inline review UI. Briefings build on calendar data + vault notes → Claude CLI → cached JSON.

**Tech Stack:** Svelte 5, Tauri v2 (Rust), Python 3.10+, Claude CLI, Zoho Calendar API, tauri-plugin-notification

**Testing:** Python: pytest. Frontend: manual/visual (no test framework). Rust: compile + manual IPC testing.

---

## Color Mapping Reference

Used by all theme tasks. Old Warm Ink → New Recap Dark:

| Old Hex | New Token | New Value | Notes |
|---------|-----------|-----------|-------|
| `#1A1A18` | `var(--bg)` | `#151921` | Deepest background |
| `#1D1D1B` | `var(--bg)` | `#151921` | App background → same token |
| `#242422` | `var(--surface)` | `#1c2128` | Primary surface |
| `#282826` | `var(--surface)` | `#1c2128` | Form inputs → same as surface |
| `#2B2B28` | `var(--raised)` | `#272d35` | Elevated/hover |
| `#262624` | `var(--border)` | `#363d47` | Subtle borders |
| `#464440` | `var(--border)` | `#363d47` | Secondary borders → same token |
| `#787470` | `var(--border-bright)` | `#4a5260` | Active/highlighted borders (custom, between border and muted) |
| `#D8D5CE` | `var(--text)` | `#d4dae3` | Primary text |
| `#B0ADA5` | `var(--text-secondary)` | `#9ba3af` | Secondary text (between text and muted) |
| `#78756E` | `var(--text-muted)` | `#7a8493` | Muted/disabled |
| `#585650` | `var(--text-faint)` | `#545d6a` | Placeholder/inactive |
| `#A8A078` | `var(--gold)` | `#C4A84D` | Primary accent |
| `#B8B088` | `var(--gold-hover)` | `#d4b85d` | Gold hover state |
| `#B4A882` | `var(--gold-muted)` | `#b09840` | Secondary gold |
| `#D06850` | `var(--red)` | `#ef534a` | Error |
| `#ef4444` | `var(--red)` | `#ef534a` | Alert red → unified |
| `#f59e0b` | `var(--warning)` | `#d4a04a` | Warning |
| `#4ade80` | `var(--green)` | `#4baa55` | Success |
| `#5B8CB8` | `var(--blue)` | `#4d9cf5` | Links/speakers (if used) |

Speaker color arrays (MeetingTranscript, GraphView): replace with new palette based on `--gold`, `--blue`, and derived hues.

---

## Task Group A: Theme Migration (Independent)

### Task A1: Define CSS Custom Properties

**Files:**
- Modify: `src/app.css`

**Step 1: Add CSS custom properties to app.css**

Add `:root` block with all theme tokens before the scrollbar styles. Update scrollbar colors to use the new tokens.

```css
@import "tailwindcss";

:root {
  --bg: #151921;
  --surface: #1c2128;
  --raised: #272d35;
  --border: #363d47;
  --border-bright: #4a5260;
  --text: #d4dae3;
  --text-secondary: #9ba3af;
  --text-muted: #7a8493;
  --text-faint: #545d6a;
  --gold: #C4A84D;
  --gold-hover: #d4b85d;
  --gold-muted: #b09840;
  --blue: #4d9cf5;
  --green: #4baa55;
  --red: #ef534a;
  --warning: #d4a04a;
}

/* ── Global dark scrollbar ── */
* {
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-faint); }
::-webkit-scrollbar-corner { background: transparent; }
```

**Step 2: Verify the app still loads**

Run: `npm run dev` — verify no CSS errors in console.

**Step 3: Commit**

```bash
git add src/app.css
git commit -m "feat(theme): define Recap Dark CSS custom properties"
```

---

### Task A2: Migrate App Shell (App.svelte)

**Files:**
- Modify: `src/App.svelte`

**Step 1: Replace all hardcoded colors in App.svelte**

Apply the color mapping. Key replacements:
- `#1A1A18` → `var(--bg)` (line ~108)
- `#1D1D1B` → `var(--bg)` (line ~93)
- `#262624` → `var(--border)` (line ~109)
- `#D8D5CE` → `var(--text)` (line ~119)
- `#A8A078` → `var(--gold)` (lines ~131, 141, 151)
- `#585650` → `var(--text-faint)` (lines ~97, 132, 142, 152)

**Step 2: Visual check**

Run dev server, verify nav bar renders correctly with new colors. Check all four routes render.

**Step 3: Commit**

```bash
git add src/App.svelte
git commit -m "feat(theme): migrate App.svelte to CSS custom properties"
```

---

### Task A3: Migrate Route Components

**Files:**
- Modify: `src/routes/Dashboard.svelte`
- Modify: `src/routes/GraphView.svelte`
- Modify: `src/routes/MeetingDetail.svelte`
- Modify: `src/routes/Settings.svelte`

**Step 1: Replace colors in all four route files**

Apply the color mapping to each file. For GraphView.svelte, also update:
- Company color array (line ~12): replace with new palette derived from theme hues
- SVG link colors: `#464440` → `var(--border)`, `#787470` → `var(--border-bright)`

New company color array for GraphView:
```javascript
const COMPANY_COLORS = ['#5e9e96', '#8e6e9e', '#9e826e', '#6e829e', '#9e6e7e', '#7e9e6e', '#9e9e6e'];
```

**Step 2: Visual check each route**

Navigate to Dashboard, Graph, Meeting Detail, Settings — verify colors.

**Step 3: Commit**

```bash
git add src/routes/
git commit -m "feat(theme): migrate route components to CSS custom properties"
```

---

### Task A4: Migrate Core Components (Batch 1 — Layout)

**Files:**
- Modify: `src/lib/components/FilterSidebar.svelte`
- Modify: `src/lib/components/DetailPanel.svelte`
- Modify: `src/lib/components/MeetingList.svelte`
- Modify: `src/lib/components/MeetingRow.svelte`
- Modify: `src/lib/components/MeetingHeader.svelte`
- Modify: `src/lib/components/SearchBar.svelte`
- Modify: `src/lib/components/Modal.svelte`

**Step 1: Replace colors in all files using the mapping table**

**Step 2: Visual check**

Open Dashboard, select a meeting, verify list rendering, detail panel, sidebar, search bar.

**Step 3: Commit**

```bash
git add src/lib/components/FilterSidebar.svelte src/lib/components/DetailPanel.svelte src/lib/components/MeetingList.svelte src/lib/components/MeetingRow.svelte src/lib/components/MeetingHeader.svelte src/lib/components/SearchBar.svelte src/lib/components/Modal.svelte
git commit -m "feat(theme): migrate layout components to CSS custom properties"
```

---

### Task A5: Migrate Core Components (Batch 2 — Meeting Content)

**Files:**
- Modify: `src/lib/components/MeetingNotes.svelte`
- Modify: `src/lib/components/MeetingTranscript.svelte`
- Modify: `src/lib/components/MeetingPlayer.svelte`
- Modify: `src/lib/components/ScreenshotGallery.svelte`
- Modify: `src/lib/components/PipelineDots.svelte`
- Modify: `src/lib/components/PipelineStatusBadge.svelte`
- Modify: `src/lib/components/RetryBanner.svelte`

For MeetingTranscript.svelte, update the speaker colors array (line ~12-13):
```javascript
const SPEAKER_COLORS = ['var(--gold)', '#5e9e96', '#8e6e9e', '#9e826e', '#6e829e', '#9e6e7e', '#7e9e6e', '#9e9e6e'];
```

**Step 1: Replace colors in all files**

**Step 2: Visual check**

Open a meeting detail, check Notes tab, Transcript tab, Player, Screenshots, pipeline dots.

**Step 3: Commit**

```bash
git add src/lib/components/MeetingNotes.svelte src/lib/components/MeetingTranscript.svelte src/lib/components/MeetingPlayer.svelte src/lib/components/ScreenshotGallery.svelte src/lib/components/PipelineDots.svelte src/lib/components/PipelineStatusBadge.svelte src/lib/components/RetryBanner.svelte
git commit -m "feat(theme): migrate meeting content components to CSS custom properties"
```

---

### Task A6: Migrate Core Components (Batch 3 — Graph)

**Files:**
- Modify: `src/lib/components/GraphControls.svelte`
- Modify: `src/lib/components/GraphSidebar.svelte`

**Step 1: Replace colors in both files**

**Step 2: Visual check**

Open Graph view, verify controls panel, sidebar, node/edge rendering.

**Step 3: Commit**

```bash
git add src/lib/components/GraphControls.svelte src/lib/components/GraphSidebar.svelte
git commit -m "feat(theme): migrate graph components to CSS custom properties"
```

---

### Task A7: Migrate Core Components (Batch 4 — Settings & Status)

**Files:**
- Modify: `src/lib/components/ProviderCard.svelte`
- Modify: `src/lib/components/ProviderStatusCard.svelte`
- Modify: `src/lib/components/SettingsSection.svelte`
- Modify: `src/lib/components/GeneralSettings.svelte`
- Modify: `src/lib/components/RecordingSettings.svelte`
- Modify: `src/lib/components/RecordingBehaviorSettings.svelte`
- Modify: `src/lib/components/RecordingStatusBar.svelte`
- Modify: `src/lib/components/VaultSettings.svelte`
- Modify: `src/lib/components/WhisperXSettings.svelte`
- Modify: `src/lib/components/TodoistSettings.svelte`
- Modify: `src/lib/components/AboutSection.svelte`

**Step 1: Replace colors in all files**

**Step 2: Visual check**

Open Settings page, check all provider cards, recording settings, vault settings, about section.

**Step 3: Commit**

```bash
git add src/lib/components/ProviderCard.svelte src/lib/components/ProviderStatusCard.svelte src/lib/components/SettingsSection.svelte src/lib/components/GeneralSettings.svelte src/lib/components/RecordingSettings.svelte src/lib/components/RecordingBehaviorSettings.svelte src/lib/components/RecordingStatusBar.svelte src/lib/components/VaultSettings.svelte src/lib/components/WhisperXSettings.svelte src/lib/components/TodoistSettings.svelte src/lib/components/AboutSection.svelte
git commit -m "feat(theme): migrate settings and status components to CSS custom properties"
```

---

### Task A8: Update SVG Icon

**Files:**
- Modify: `static/icon-source.svg`

**Step 1: Replace icon colors**

- `#A8A078` → `#C4A84D` (gold accent nodes)
- `#78756E` → `#7a8493` (muted nodes)

**Step 2: Verify icon renders**

Check the app window title bar icon or wherever the icon appears.

**Step 3: Commit**

```bash
git add static/icon-source.svg
git commit -m "feat(theme): update icon to Recap Dark colors"
```

---

### Task A9: Add Zoom Controls

**Files:**
- Modify: `src/App.svelte` (add keyboard/wheel listener)
- Modify: `src/lib/stores/settings.ts` (add zoomLevel setting)

**Step 1: Add zoomLevel to settings store**

In `src/lib/stores/settings.ts`, add `zoomLevel: number` to `AppSettings` interface with default `1.0`.

**Step 2: Add zoom event handlers in App.svelte**

```svelte
<script>
  import { onMount } from 'svelte';
  import { appWindow } from '@tauri-apps/api/window';
  // or use: import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow';

  let currentZoom = $derived(/* settings.zoomLevel */);

  function handleKeydown(e: KeyboardEvent) {
    if (e.ctrlKey && (e.key === '=' || e.key === '+')) {
      e.preventDefault();
      setZoom(currentZoom + 0.1);
    } else if (e.ctrlKey && e.key === '-') {
      e.preventDefault();
      setZoom(currentZoom - 0.1);
    } else if (e.ctrlKey && e.key === '0') {
      e.preventDefault();
      setZoom(1.0);
    }
  }

  function handleWheel(e: WheelEvent) {
    if (e.ctrlKey) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.1 : 0.1;
      setZoom(currentZoom + delta);
    }
  }

  async function setZoom(level: number) {
    const clamped = Math.max(0.5, Math.min(2.0, level));
    // Use Tauri webview API to set zoom
    // await getCurrentWebviewWindow().setZoom(clamped);
    // Or CSS approach: document.documentElement.style.zoom = String(clamped);
    document.documentElement.style.zoom = String(clamped);
    saveSetting('zoomLevel', clamped);
  }

  onMount(() => {
    // Apply saved zoom on launch
    if (settings.zoomLevel !== 1.0) {
      document.documentElement.style.zoom = String(settings.zoomLevel);
    }
  });
</script>

<svelte:window on:keydown={handleKeydown} on:wheel|passive={handleWheel} />
```

Note: Check if `getCurrentWebviewWindow().setZoom()` is available in Tauri v2. If not, use the CSS `zoom` property as fallback. The CSS approach works reliably across webviews.

**Step 3: Test zoom**

Run dev server. Ctrl++ should zoom in, Ctrl+- zoom out, Ctrl+0 reset. Ctrl+scroll should also work. Verify zoom persists across page navigation.

**Step 4: Commit**

```bash
git add src/App.svelte src/lib/stores/settings.ts
git commit -m "feat: add Ctrl+scroll and Ctrl+/-/0 zoom controls with persistence"
```

---

## Task Group B: Pipeline Status Model Extension (Blocks C and D)

### Task B1: Add `waiting` Field to Python Pipeline

**Files:**
- Modify: `recap/pipeline.py`
- Create: `tests/test_pipeline_waiting.py`

**Step 1: Write the failing test**

```python
# tests/test_pipeline_waiting.py
import json
import pathlib
import pytest
from unittest.mock import patch, MagicMock
from recap.pipeline import Pipeline, PIPELINE_STAGES

def test_status_waiting_field_written(tmp_path):
    """Status.json should include waiting field when set."""
    status_file = tmp_path / "status.json"

    # Create a pipeline and manually mark a stage as waiting
    pipeline = Pipeline.__new__(Pipeline)
    pipeline.working_dir = tmp_path
    pipeline.recordings_dir = tmp_path
    pipeline.status = {
        stage: {"completed": False, "timestamp": None, "error": None, "waiting": None}
        for stage in PIPELINE_STAGES
    }

    # Mark diarize as complete, analyze as waiting
    pipeline._mark_stage("diarize", completed=True)
    pipeline._mark_waiting("analyze", "speaker_review")
    pipeline._save_status()

    data = json.loads(status_file.read_text())
    assert data["diarize"]["completed"] is True
    assert data["analyze"]["waiting"] == "speaker_review"
    assert data["analyze"]["completed"] is False
    assert data["analyze"]["error"] is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline_waiting.py -v`
Expected: FAIL — `_mark_waiting` and `_save_status` don't exist yet.

**Step 3: Implement changes in pipeline.py**

1. Update default status dict to include `"waiting": None` for each stage
2. Add `_mark_waiting(stage, reason)` method
3. Ensure `_save_status()` writes the waiting field
4. Ensure `_mark_stage()` clears `waiting` when a stage is marked

```python
def _mark_waiting(self, stage: str, reason: str) -> None:
    self.status[stage]["waiting"] = reason
    self._save_status()

def _mark_stage(self, stage: str, completed: bool, error: str | None = None) -> None:
    self.status[stage] = {
        "completed": completed,
        "timestamp": datetime.now().isoformat() if completed else None,
        "error": error,
        "waiting": None,  # Clear waiting when stage is marked
    }
    self._save_status()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline_waiting.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add recap/pipeline.py tests/test_pipeline_waiting.py
git commit -m "feat(pipeline): add waiting field to pipeline status model"
```

---

### Task B2: Add `waiting` Field to Rust Types

**Files:**
- Modify: `src-tauri/src/recorder/types.rs` (lines ~73-120)

**Step 1: Add `waiting` field to `StageStatus`**

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StageStatus {
    pub completed: bool,
    pub timestamp: Option<String>,
    pub error: Option<String>,
    pub waiting: Option<String>,  // NEW
}
```

Update the `Default` impl to include `waiting: None`.

**Step 2: Verify it compiles**

Run: `cd src-tauri && cargo check`

**Step 3: Commit**

```bash
git add src-tauri/src/recorder/types.rs
git commit -m "feat(backend): add waiting field to StageStatus"
```

---

### Task B3: Add `waiting` Field to TypeScript Types + PipelineDots

**Files:**
- Modify: `src/lib/tauri.ts` (lines ~59-74)
- Modify: `src/lib/components/PipelineDots.svelte`

**Step 1: Update TypeScript interface**

```typescript
export interface PipelineStageStatus {
  completed: boolean;
  timestamp: string | null;
  error: string | null;
  waiting: string | null;  // NEW
}
```

**Step 2: Update PipelineDots dot state logic**

In `PipelineDots.svelte`, update the function that determines dot color to handle the `waiting` state. The dot should pulse gold when `waiting` is set:

```svelte
<!-- Dot state logic -->
{#if stage.completed}
  <!-- done: solid gold -->
{:else if stage.waiting}
  <!-- waiting: pulsing gold with CSS animation -->
{:else if stage.error}
  <!-- error: solid red -->
{:else}
  <!-- pending: solid gray -->
{/if}
```

Add a CSS animation for the pulsing state:
```css
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.dot-waiting { animation: pulse 2s infinite; }
```

Also update the expandable detail section to show "Awaiting speaker review" instead of an error message when `waiting` is set.

**Step 3: Visual check**

Set up dummy data with a `waiting` stage and verify the pulsing dot renders.

**Step 4: Commit**

```bash
git add src/lib/tauri.ts src/lib/components/PipelineDots.svelte
git commit -m "feat(ui): add waiting state to pipeline dots with pulsing animation"
```

---

## Task Group C: Speaker Correction (Depends on B)

### Task C1: Add Pipeline Pause Logic in Python

**Files:**
- Modify: `recap/pipeline.py`
- Create: `tests/test_pipeline_pause.py`

**Step 1: Write the failing test**

```python
# tests/test_pipeline_pause.py
def test_pipeline_pauses_when_no_participants(tmp_path):
    """Pipeline should pause at analyze when no participants are available."""
    # Setup: create a meeting.json with empty participants
    # Run pipeline through diarize stage
    # Assert: analyze stage has waiting="speaker_review"
    # Assert: pipeline exited without running analyze or export
```

**Step 2: Run test to verify it fails**

**Step 3: Implement pause logic in pipeline.py**

In `run_pipeline()`, after the diarize stage completes, check if `MeetingMetadata.participants` is empty. If so, mark analyze as waiting and return early:

```python
# After diarize stage completes:
if not metadata.participants:
    self._mark_waiting("analyze", "speaker_review")
    logger.info("No participants available — pausing for speaker review")
    return {"paused": True, "waiting_at": "analyze"}
```

**Step 4: Run test to verify it passes**

**Step 5: Commit**

```bash
git add recap/pipeline.py tests/test_pipeline_pause.py
git commit -m "feat(pipeline): pause at analyze when no participant list available"
```

---

### Task C2: Add Speaker Label Resume Logic in Python

**Files:**
- Modify: `recap/pipeline.py`
- Modify: `recap/analyze.py`
- Create: `tests/test_speaker_labels.py`

**Step 1: Write the failing test**

```python
# tests/test_speaker_labels.py
def test_speaker_labels_applied_to_transcript():
    """speaker_labels.json corrections should be applied to transcript before analysis."""
    # Setup: transcript with SPEAKER_00, SPEAKER_01
    # Create speaker_labels.json: {"SPEAKER_00": "Tim", "SPEAKER_01": "Sarah"}
    # Call the label application function
    # Assert: transcript utterances now have "Tim" and "Sarah" as speaker names
```

**Step 2: Run test to verify it fails**

**Step 3: Implement label application**

Add to `pipeline.py` (or a helper in `analyze.py`):

```python
def _apply_speaker_labels(transcript: TranscriptResult, labels_path: pathlib.Path) -> TranscriptResult:
    if not labels_path.exists():
        return transcript
    labels = json.loads(labels_path.read_text())
    for utterance in transcript.utterances:
        if utterance.speaker in labels:
            utterance.speaker = labels[utterance.speaker]
    return transcript
```

In `run_pipeline()`, before calling `analyze()`, check for `speaker_labels.json` and apply:

```python
labels_path = self.working_dir / "speaker_labels.json"
transcript = self._apply_speaker_labels(transcript, labels_path)
```

**Step 4: Run test to verify it passes**

**Step 5: Commit**

```bash
git add recap/pipeline.py recap/analyze.py tests/test_speaker_labels.py
git commit -m "feat(pipeline): apply speaker_labels.json corrections on resume"
```

---

### Task C3: Add Rust IPC Commands for Speaker Correction

**Files:**
- Modify: `src-tauri/src/meetings.rs` (add `update_speaker_labels` and `get_known_participants` commands)
- Modify: `src-tauri/src/lib.rs` (register new commands)

**Step 1: Implement `get_known_participants`**

Scan all `.meeting.json` files in the recordings directory, collect unique participant names, sort and return.

```rust
#[tauri::command]
pub async fn get_known_participants(recordings_dir: String) -> Result<Vec<String>, String> {
    // Walk recordings_dir, parse each .meeting.json, collect participant names
    // Return sorted, deduplicated list
}
```

**Step 2: Implement `update_speaker_labels`**

```rust
#[tauri::command]
pub async fn update_speaker_labels(
    recording_dir: String,
    corrections: std::collections::HashMap<String, String>,
) -> Result<(), String> {
    let dir = PathBuf::from(&recording_dir);
    let labels_path = dir.join("speaker_labels.json");
    let json = serde_json::to_string_pretty(&corrections)
        .map_err(|e| e.to_string())?;
    std::fs::write(&labels_path, json)
        .map_err(|e| e.to_string())?;
    Ok(())
}
```

**Step 3: Register commands in lib.rs**

Add `get_known_participants` and `update_speaker_labels` to the `invoke_handler` in `lib.rs`.

**Step 4: Verify it compiles**

Run: `cd src-tauri && cargo check`

**Step 5: Commit**

```bash
git add src-tauri/src/meetings.rs src-tauri/src/lib.rs
git commit -m "feat(backend): add speaker label correction and known participants IPC commands"
```

---

### Task C4: Add TypeScript IPC Wrappers

**Files:**
- Modify: `src/lib/tauri.ts`

**Step 1: Add wrapper functions**

```typescript
export async function getKnownParticipants(recordingsDir: string): Promise<string[]> {
  return invoke('get_known_participants', { recordingsDir });
}

export async function updateSpeakerLabels(
  recordingDir: string,
  corrections: Record<string, string>
): Promise<void> {
  return invoke('update_speaker_labels', { recordingDir, corrections });
}
```

**Step 2: Commit**

```bash
git add src/lib/tauri.ts
git commit -m "feat(ipc): add speaker label correction TypeScript wrappers"
```

---

### Task C5: Build Speaker Review UI Component

**Files:**
- Create: `src/lib/components/SpeakerReview.svelte`

**Step 1: Build the component**

Props: `status: PipelineStatus`, `recordingPath: string`, `transcript: Utterance[]`, `calendarParticipants: string[]`

Component structure:
1. Warning banner: "N of M speakers could not be identified..."
2. Speaker mapping rows: each SPEAKER_XX with utterance count + searchable dropdown
3. Dropdown: calendar participants first, then known participants (fetched via `getKnownParticipants`), then "Add new name..." option
4. Action buttons: "Apply & Resume Pipeline" and "Skip — Use Generic Labels"

"Apply" calls `updateSpeakerLabels()` then `retryProcessing(recordingDir, 'analyze')`.
"Skip" calls `retryProcessing(recordingDir, 'analyze')` directly (no labels file written).

Use the Recap Dark theme tokens throughout (`var(--gold)`, `var(--blue)`, etc.).

**Step 2: Visual check with dummy data**

**Step 3: Commit**

```bash
git add src/lib/components/SpeakerReview.svelte
git commit -m "feat(ui): add SpeakerReview component with searchable participant dropdown"
```

---

### Task C6: Integrate Speaker Review into MeetingDetail and DetailPanel

**Files:**
- Modify: `src/routes/MeetingDetail.svelte`
- Modify: `src/lib/components/DetailPanel.svelte`
- Modify: `src/lib/components/MeetingRow.svelte` (add "Review Speakers" badge)

**Step 1: Add SpeakerReview to Transcript tab**

In both MeetingDetail and DetailPanel, when the Transcript tab is active and the pipeline has a `waiting === 'speaker_review'` stage, render the SpeakerReview component above the transcript.

**Step 2: Add badge to MeetingRow**

When `pipeline_status.analyze.waiting === 'speaker_review'`, show a gold "Review Speakers" badge next to the pipeline dots.

**Step 3: Visual check**

Set up dummy data with a waiting pipeline state and verify the full flow: badge on meeting row → click → transcript tab shows review UI.

**Step 4: Commit**

```bash
git add src/routes/MeetingDetail.svelte src/lib/components/DetailPanel.svelte src/lib/components/MeetingRow.svelte
git commit -m "feat(ui): integrate SpeakerReview into meeting detail and list views"
```

---

## Task Group D: Calendar Integration (Independent of C)

### Task D1: Create Calendar Rust Module

**Files:**
- Create: `src-tauri/src/calendar.rs`
- Modify: `src-tauri/src/lib.rs` (add module + register commands)

**Step 1: Implement calendar module**

Key structures and commands:

```rust
mod calendar {
    use serde::{Deserialize, Serialize};
    use std::path::PathBuf;

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct CalendarEvent {
        pub id: String,
        pub title: String,
        pub description: Option<String>,
        pub start: String,  // ISO 8601
        pub end: String,
        pub participants: Vec<CalendarParticipant>,
        pub location: Option<String>,
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct CalendarParticipant {
        pub name: String,
        pub email: Option<String>,
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct CalendarCache {
        pub events: Vec<CalendarEvent>,
        pub last_synced: String,  // ISO 8601
    }

    #[tauri::command]
    pub async fn fetch_calendar_events(/* app handle, date range */) -> Result<Vec<CalendarEvent>, String>;

    #[tauri::command]
    pub async fn get_upcoming_meetings(hours_ahead: f64) -> Result<Vec<CalendarEvent>, String>;

    #[tauri::command]
    pub async fn sync_calendar(/* app handle */) -> Result<CalendarCache, String>;
}
```

The `fetch_calendar_events` command:
1. Gets Zoho OAuth tokens from Stronghold
2. Calls Zoho Calendar API with `Accept: application/json+large` header
3. Parses response into `CalendarEvent` structs
4. Writes to cache file in app data dir
5. Returns events

Cache file location: `{app_data_dir}/calendar_cache.json`

**Step 2: Register module and commands in lib.rs**

**Step 3: Verify it compiles**

Run: `cd src-tauri && cargo check`

**Step 4: Commit**

```bash
git add src-tauri/src/calendar.rs src-tauri/src/lib.rs
git commit -m "feat(backend): add Zoho Calendar module with cache and sync commands"
```

---

### Task D2: Add Calendar-Recording Matching

**Files:**
- Modify: `src-tauri/src/calendar.rs`
- Modify: `src-tauri/src/meetings.rs`

**Step 1: Implement matching logic**

Add to calendar.rs:

```rust
pub fn match_event_to_recording(event: &CalendarEvent, meeting: &MeetingSummary) -> bool {
    // Parse event start/end and meeting date + duration
    // Check for time overlap (event window vs recording window)
    // Return true if overlap exceeds threshold (e.g., 5 minutes)
}

#[tauri::command]
pub async fn get_calendar_matches(recordings_dir: String) -> Result<HashMap<String, String>, String> {
    // Returns: { calendar_event_id: meeting_id } for all matched pairs
}
```

**Step 2: Verify it compiles**

**Step 3: Commit**

```bash
git add src-tauri/src/calendar.rs src-tauri/src/meetings.rs
git commit -m "feat(backend): add calendar-recording time overlap matching"
```

---

### Task D3: Add Calendar TypeScript Wrappers

**Files:**
- Modify: `src/lib/tauri.ts`

**Step 1: Add types and wrappers**

```typescript
export interface CalendarEvent {
  id: string;
  title: string;
  description: string | null;
  start: string;
  end: string;
  participants: { name: string; email: string | null }[];
  location: string | null;
}

export interface CalendarCache {
  events: CalendarEvent[];
  last_synced: string;
}

export async function fetchCalendarEvents(startDate: string, endDate: string): Promise<CalendarEvent[]> {
  return invoke('fetch_calendar_events', { startDate, endDate });
}

export async function getUpcomingMeetings(hoursAhead: number): Promise<CalendarEvent[]> {
  return invoke('get_upcoming_meetings', { hoursAhead });
}

export async function syncCalendar(): Promise<CalendarCache> {
  return invoke('sync_calendar');
}

export async function getCalendarMatches(recordingsDir: string): Promise<Record<string, string>> {
  return invoke('get_calendar_matches', { recordingsDir });
}
```

**Step 2: Commit**

```bash
git add src/lib/tauri.ts
git commit -m "feat(ipc): add calendar TypeScript types and wrappers"
```

---

### Task D4: Build Calendar View

**Files:**
- Create: `src/routes/Calendar.svelte`
- Modify: `src/App.svelte` (add `#calendar` route + nav item)

**Step 1: Build the Calendar route component**

Sections:
1. Header with "Calendar" title + last-synced timestamp + "Sync Now" button
2. Upcoming meetings list (next 7 days) — each with title, time, participants, matched recording link
3. Past events section — linked to recordings when matched
4. Empty state: "Connect Zoho Calendar in Settings to see upcoming meetings"

Auto-sync on mount: call `syncCalendar()` if last sync was >15 min ago.

**Step 2: Add route to App.svelte**

Add `#calendar` case to the router. Add "Calendar" nav item.

**Step 3: Visual check**

Navigate to Calendar tab. Without Zoho connected, should show empty state.

**Step 4: Commit**

```bash
git add src/routes/Calendar.svelte src/App.svelte
git commit -m "feat(ui): add Calendar view with upcoming/past events and sync"
```

---

### Task D5: Add App-Focus Calendar Sync

**Files:**
- Modify: `src/App.svelte`

**Step 1: Add focus-based sync**

```svelte
<script>
  let lastCalendarSync = 0;

  function handleWindowFocus() {
    const now = Date.now();
    const fifteenMinutes = 15 * 60 * 1000;
    if (now - lastCalendarSync > fifteenMinutes) {
      lastCalendarSync = now;
      syncCalendar().catch(console.error);
    }
  }
</script>

<svelte:window on:focus={handleWindowFocus} />
```

**Step 2: Commit**

```bash
git add src/App.svelte
git commit -m "feat: auto-sync calendar on app focus (debounced 15 min)"
```

---

## Task Group E: Meeting Notifications + Briefings (Depends on D)

### Task E1: Create Briefing Prompt Template

**Files:**
- Create: `prompts/meeting_briefing.md`

**Step 1: Write the prompt**

```markdown
You are preparing a pre-meeting briefing. Given notes from past meetings with the same company or participants, produce a structured JSON prep brief.

## Upcoming Meeting

Title: {{title}}
Participants: {{participants}}
Time: {{time}}

## Past Meeting Notes

{{past_notes}}

## Instructions

Produce a JSON object with exactly these fields:

1. **topics** — array of strings: ongoing discussion threads and recurring themes across past meetings. Focus on what's still active/unresolved.

2. **action_items** — array of {assignee, description, from_meeting} objects: open items attributed to upcoming meeting attendees. from_meeting is the meeting title where the item was assigned.

3. **context** — string: meeting frequency, how long you've been meeting with these people, any notable patterns.

4. **relationship_summary** — string: working relationship dynamics, communication style, what this person/group cares about most.

5. **first_meeting** — boolean: true if no past meeting notes were provided.

Keep each field concise. Use bullet points within strings, not paragraphs. Focus on what's actionable for the upcoming meeting.

Output ONLY valid JSON. No markdown fences, no explanation, no preamble.
```

**Step 2: Commit**

```bash
git add prompts/meeting_briefing.md
git commit -m "feat: add meeting briefing prompt template for Claude CLI"
```

---

### Task E2: Add Briefing Generation to Rust Backend

**Files:**
- Create: `src-tauri/src/briefing.rs`
- Modify: `src-tauri/src/lib.rs`

**Step 1: Implement briefing module**

```rust
mod briefing {
    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct Briefing {
        pub topics: Vec<String>,
        pub action_items: Vec<BriefingActionItem>,
        pub context: String,
        pub relationship_summary: String,
        pub first_meeting: bool,
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct BriefingActionItem {
        pub assignee: String,
        pub description: String,
        pub from_meeting: String,
    }

    #[derive(Debug, Clone, Serialize, Deserialize)]
    struct BriefingCache {
        pub event_id: String,
        pub briefing: Briefing,
        pub generated_at: String,
    }

    #[tauri::command]
    pub async fn generate_briefing(
        event_id: String,
        title: String,
        participants: Vec<String>,
        time: String,
        recordings_dir: String,
        vault_meetings_dir: Option<String>,
        event_description: Option<String>,
    ) -> Result<Briefing, String> {
        // 1. Check cache: {app_data_dir}/briefing_cache/{event_id}.json
        // 2. If cached and not invalidated, return cached briefing
        // 3. Otherwise:
        //    a. Find past meetings matching participants/company
        //    b. Read vault notes for matched meetings (lookback: 4 meetings or 3 months)
        //    c. Build prompt from template + past notes
        //    d. Call: claude --print --output-format json (via subprocess)
        //    e. Parse JSON response into Briefing struct
        //    f. Cache result
        //    g. Return briefing
    }

    #[tauri::command]
    pub async fn invalidate_briefing_cache(participant_names: Vec<String>) -> Result<(), String> {
        // Called when a new meeting completes processing
        // Delete cached briefings where participants overlap
    }
}
```

Key detail: the Rust side calls `claude --print --output-format json` as a subprocess (same pattern as the Python sidecar uses, but directly from Rust). The prompt template is read from `prompts/meeting_briefing.md`.

**Step 2: Register module and commands**

**Step 3: Verify it compiles**

**Step 4: Commit**

```bash
git add src-tauri/src/briefing.rs src-tauri/src/lib.rs
git commit -m "feat(backend): add briefing generation via Claude CLI with caching"
```

---

### Task E3: Add Notification Trigger Logic

**Files:**
- Modify: `src-tauri/src/lib.rs` or create `src-tauri/src/notifications.rs`

**Step 1: Implement meeting notification check**

On app focus (or periodic timer), check upcoming meetings against lead time setting:

```rust
pub async fn check_upcoming_notifications(app: &AppHandle) {
    // 1. Get upcoming meetings within lead_time_minutes
    // 2. For each, check if notification already sent (track sent IDs)
    // 3. If not sent, fire notification:
    //    app.notification()
    //       .builder()
    //       .title(&format!("Upcoming: {}", event.title))
    //       .body(&format!("In {} min — {}", minutes_until, participants_text))
    //       .show();
    // 4. Mark as sent
}
```

**Step 2: Add lead time setting to settings store**

In `src/lib/stores/settings.ts`, add:
- `meetingNotifications: boolean` (default: true)
- `meetingLeadTimeMinutes: number` (default: 10)

**Step 3: Commit**

```bash
git add src-tauri/src/lib.rs src/lib/stores/settings.ts
git commit -m "feat(backend): add pre-meeting notification trigger with lead time setting"
```

---

### Task E4: Add TypeScript Briefing Wrappers

**Files:**
- Modify: `src/lib/tauri.ts`

**Step 1: Add types and wrappers**

```typescript
export interface Briefing {
  topics: string[];
  action_items: { assignee: string; description: string; from_meeting: string }[];
  context: string;
  relationship_summary: string;
  first_meeting: boolean;
}

export async function generateBriefing(
  eventId: string,
  title: string,
  participants: string[],
  time: string,
  recordingsDir: string,
  vaultMeetingsDir?: string,
  eventDescription?: string
): Promise<Briefing> {
  return invoke('generate_briefing', {
    eventId, title, participants, time, recordingsDir, vaultMeetingsDir, eventDescription
  });
}
```

**Step 2: Commit**

```bash
git add src/lib/tauri.ts
git commit -m "feat(ipc): add briefing TypeScript types and wrapper"
```

---

### Task E5: Build Briefing Panel UI

**Files:**
- Create: `src/lib/components/BriefingPanel.svelte`

**Step 1: Build the component**

Props: `eventId: string`, `title: string`, `participants: string[]`, `time: string`

Sections rendered from `Briefing` response:
1. **Topics** — bulleted list of ongoing threads
2. **Open Action Items** — table with assignee, description, source meeting
3. **Context** — meeting frequency and history summary
4. **Relationship Summary** — working dynamics

Loading state while Claude CLI runs. Error state with retry.

First-meeting state: "This is your first meeting with these participants" + calendar description if available.

**Step 2: Integrate into Calendar view**

In `Calendar.svelte`, clicking an upcoming meeting expands to show the BriefingPanel.

**Step 3: Visual check**

**Step 4: Commit**

```bash
git add src/lib/components/BriefingPanel.svelte src/routes/Calendar.svelte
git commit -m "feat(ui): add BriefingPanel with topics, actions, context, and relationship summary"
```

---

### Task E6: Add Notification Settings UI

**Files:**
- Modify: `src/lib/components/GeneralSettings.svelte`

**Step 1: Add notification settings**

Add below the existing "Pipeline completion" checkbox:
- Toggle: "Pre-meeting notifications" (meetingNotifications)
- Select: "Lead time" with options 5, 10, 15 minutes (meetingLeadTimeMinutes)

**Step 2: Visual check**

Open Settings, verify new controls appear and persist.

**Step 3: Commit**

```bash
git add src/lib/components/GeneralSettings.svelte
git commit -m "feat(ui): add pre-meeting notification settings"
```

---

## Task Group F: Final Integration + Cleanup

### Task F1: Wire Calendar Participants into Speaker Review

**Files:**
- Modify: `src/lib/components/SpeakerReview.svelte`

**Step 1: Connect calendar data**

When a meeting has a matched calendar event, pass `CalendarEvent.participants` names to the SpeakerReview dropdown as the top section of suggestions.

**Step 2: Commit**

```bash
git add src/lib/components/SpeakerReview.svelte
git commit -m "feat(ui): populate speaker dropdown with calendar participants"
```

---

### Task F2: Invalidate Briefing Cache on Pipeline Completion

**Files:**
- Modify: `src/lib/stores/meetings.ts`

**Step 1: On pipeline-completed event, call invalidation**

In `initMeetingsListener()`, when the "pipeline-completed" event fires, call `invalidateBriefingCache()` with the participant names from the completed meeting.

**Step 2: Commit**

```bash
git add src/lib/stores/meetings.ts
git commit -m "feat: invalidate briefing cache when new meeting processing completes"
```

---

### Task F3: Update Dummy Data for New Features

**Files:**
- Modify: `src/lib/dummy-data.ts`

**Step 1: Add dummy data**

- Add `waiting` field to pipeline status dummy data (one meeting with `speaker_review` waiting state)
- Add dummy calendar events
- Add dummy briefing response

**Step 2: Verify with `VITE_DUMMY_DATA=true`**

**Step 3: Commit**

```bash
git add src/lib/dummy-data.ts
git commit -m "feat(dummy): add speaker review, calendar, and briefing dummy data"
```

---

### Task F4: Regenerate MANIFEST.md

**Files:**
- Modify: `MANIFEST.md`

**Step 1: Regenerate to reflect new files**

Update Structure section to include:
- `src-tauri/src/calendar.rs`
- `src-tauri/src/briefing.rs`
- `src/routes/Calendar.svelte`
- `src/lib/components/SpeakerReview.svelte`
- `src/lib/components/BriefingPanel.svelte`
- `prompts/meeting_briefing.md`

Update Key Relationships to note:
- Calendar → recording matching feeds into briefings
- SpeakerReview reads `waiting` field from PipelineStatus
- BriefingPanel calls Claude CLI via Rust backend

**Step 2: Commit**

```bash
git add MANIFEST.md
git commit -m "docs: regenerate MANIFEST.md for Phase 5c changes"
```

---

## Execution Order

Tasks can be parallelized within groups. Groups must respect dependencies:

```
A (Theme)          ──────────────────────────────> F3, F4
B (Status Model)   ──> C (Speaker Correction) ──> F1, F3, F4
                   ──> D (Calendar) ──> E (Briefings) ──> F2, F3, F4
```

**Recommended serial order:**
A1 → A2 → A3 → A4 → A5 → A6 → A7 → A8 → A9 → B1 → B2 → B3 → C1 → C2 → C3 → C4 → C5 → C6 → D1 → D2 → D3 → D4 → D5 → E1 → E2 → E3 → E4 → E5 → E6 → F1 → F2 → F3 → F4

**Parallel option:** Run A in parallel with B+C, then D+E sequentially after B.
