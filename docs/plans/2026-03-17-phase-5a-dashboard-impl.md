# Phase 5a: Dashboard UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the dashboard UI — call history list, meeting detail view with notes/transcript/playback, and manual recording controls.

**Architecture:** Rust IPC backend scans the recordings folder for meeting metadata files. Svelte frontend renders list and detail views with vidstack for playback. Tauri's asset protocol serves local media files to the webview.

**Tech Stack:** Tauri v2 (Rust), Svelte 5, Tailwind CSS 4, vidstack, marked

**Design doc:** `docs/plans/2026-03-17-phase-5a-dashboard-ui-design.md`

---

### Task 1: Pipeline Change — Preserve Metadata in Recordings Folder

**Files:**
- Modify: `recap/pipeline.py:85-145` (run_pipeline function)

The pipeline currently saves `status.json` to the temp working directory but doesn't copy it or `meeting.json` alongside the recording in the recordings folder. We need both files there for the dashboard to scan.

**Step 1: Add metadata preservation to pipeline**

After the recording is moved to `recording_dest` (line ~121), copy `meeting.json` alongside it. After each `_save_status` call, also save a copy to the recordings folder. Add this logic after line 121:

```python
    # Copy meeting.json alongside recording for dashboard discovery
    meeting_json_dest = recording_dest.with_suffix(".meeting.json")
    import shutil as _shutil
    _shutil.copy2(str(metadata_path), str(meeting_json_dest))
    results["meeting_json"] = meeting_json_dest
    logger.info("Copied meeting metadata to %s", meeting_json_dest)
```

Also, modify `_save_status` to accept an optional second path, and after each `_save_status(working_dir, status)` call, also save to the recordings folder:

```python
def _save_status(working_dir: pathlib.Path, status: dict, recordings_dir_stem: pathlib.Path | None = None) -> None:
    """Write status.json to working dir and optionally to recordings dir."""
    (working_dir / "status.json").write_text(json.dumps(status, indent=2))
    if recordings_dir_stem is not None:
        recordings_dir_stem.with_suffix(".status.json").write_text(json.dumps(status, indent=2))
```

Update all `_save_status` calls in `run_pipeline` to pass `recording_dest` as the second argument.

**Step 2: Verify with an existing test or manual check**

Run: `python -m pytest tests/ -v -k pipeline 2>&1 | head -30` (if tests exist), or verify the logic is correct by reading the updated file.

**Step 3: Commit**

```bash
git add recap/pipeline.py
git commit -m "feat: preserve meeting.json and status.json in recordings folder for dashboard"
```

---

### Task 2: Rust Data Structures — meetings module

**Files:**
- Create: `src-tauri/src/meetings.rs`
- Modify: `src-tauri/src/lib.rs:3` (add `mod meetings;`)

**Step 1: Create the meetings module with data types**

```rust
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

use crate::recorder::types::PipelineStatus;

/// Summary of a meeting for the list view.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeetingSummary {
    pub id: String,
    pub title: String,
    pub date: String,
    pub platform: String,
    pub participants: Vec<String>,
    pub duration_seconds: Option<f64>,
    pub pipeline_status: PipelineStatus,
    pub has_note: bool,
    pub has_transcript: bool,
    pub has_video: bool,
    pub recording_path: Option<String>,
    pub note_path: Option<String>,
}

/// A single transcript utterance.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Utterance {
    pub speaker: String,
    pub start: f64,
    pub end: f64,
    pub text: String,
}

/// A screenshot with optional caption.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Screenshot {
    pub path: String,
    pub caption: Option<String>,
}

/// Full meeting detail for the detail view.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeetingDetail {
    pub summary: MeetingSummary,
    pub note_content: Option<String>,
    pub transcript: Option<Vec<Utterance>>,
    pub screenshots: Vec<Screenshot>,
}

/// Paginated list response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeetingListResponse {
    pub items: Vec<MeetingSummary>,
    pub next_cursor: Option<String>,
}

/// Meeting metadata from meeting.json (matches Python's MeetingMetadata).
#[derive(Debug, Clone, Deserialize)]
struct MeetingJson {
    title: String,
    date: String,
    participants: Vec<ParticipantJson>,
    platform: String,
}

#[derive(Debug, Clone, Deserialize)]
struct ParticipantJson {
    name: String,
}
```

**Step 2: Add `mod meetings;` to lib.rs**

In `src-tauri/src/lib.rs`, add `mod meetings;` after line 8 (after `mod tray;`).

**Step 3: Verify it compiles**

Run: `cd src-tauri && cargo check 2>&1 | tail -5`

**Step 4: Commit**

```bash
git add src-tauri/src/meetings.rs src-tauri/src/lib.rs
git commit -m "feat: add meetings module with data structures for dashboard"
```

---

### Task 3: Rust IPC — list_meetings command

**Files:**
- Modify: `src-tauri/src/meetings.rs` (add scanning logic + IPC command)
- Modify: `src-tauri/src/lib.rs:53` (register command in invoke_handler)

**Step 1: Implement the scanning and list logic**

Add to `meetings.rs`:

```rust
/// Parse a meeting.json file into a MeetingSummary.
fn parse_meeting_json(path: &Path) -> Option<MeetingSummary> {
    let content = std::fs::read_to_string(path).ok()?;
    let meta: MeetingJson = serde_json::from_str(&content).ok()?;

    let stem = path.file_stem()?.to_str()?;
    // stem is like "2026-03-16-acme-kickoff.meeting" — strip the ".meeting" part
    let id = stem.strip_suffix(".meeting").unwrap_or(stem).to_string();

    let dir = path.parent()?;
    let recording_exts = ["mp4", "mkv", "webm", "wav"];
    let recording_path = recording_exts.iter()
        .map(|ext| dir.join(format!("{}.{}", &id, ext)))
        .find(|p| p.exists());
    let transcript_path = dir.join(format!("{}.transcript.json", &id));
    let status_path = dir.join(format!("{}.status.json", &id));

    let pipeline_status = if status_path.exists() {
        std::fs::read_to_string(&status_path)
            .ok()
            .and_then(|s| serde_json::from_str::<PipelineStatus>(&s).ok())
            .unwrap_or_default()
    } else {
        PipelineStatus::default()
    };

    Some(MeetingSummary {
        id: id.clone(),
        title: meta.title,
        date: meta.date,
        platform: meta.platform,
        participants: meta.participants.into_iter().map(|p| p.name).collect(),
        duration_seconds: None, // could parse from recording later
        pipeline_status,
        has_note: false, // set by caller after vault scan
        has_transcript: transcript_path.exists(),
        has_video: recording_path.is_some(),
        recording_path: recording_path.map(|p| p.to_string_lossy().to_string()),
        note_path: None, // set by caller after vault scan
    })
}

/// Build a MeetingSummary from a recording file that has no meeting.json (edge case 6).
fn summary_from_filename(path: &Path) -> Option<MeetingSummary> {
    let stem = path.file_stem()?.to_str()?.to_string();
    // Try to extract date from stem like "2026-03-16-some-title"
    let (date, title) = if stem.len() >= 10 && stem[..10].chars().filter(|c| *c == '-').count() == 2 {
        let date = stem[..10].to_string();
        let title = stem[11..].replace('-', " ");
        let title = if title.is_empty() { "Untitled Meeting".to_string() } else { title };
        (date, title)
    } else {
        ("".to_string(), stem.replace('-', " "))
    };

    let dir = path.parent()?;
    let id = stem.clone();
    let transcript_path = dir.join(format!("{}.transcript.json", &id));
    let status_path = dir.join(format!("{}.status.json", &id));

    let pipeline_status = if status_path.exists() {
        std::fs::read_to_string(&status_path)
            .ok()
            .and_then(|s| serde_json::from_str::<PipelineStatus>(&s).ok())
            .unwrap_or_default()
    } else {
        PipelineStatus::default()
    };

    Some(MeetingSummary {
        id,
        title,
        date,
        platform: "unknown".to_string(),
        participants: vec![],
        duration_seconds: None,
        pipeline_status,
        has_note: false,
        has_transcript: transcript_path.exists(),
        has_video: true,
        recording_path: Some(path.to_string_lossy().to_string()),
        note_path: None,
    })
}

/// Scan vault meetings dir and return a map of note filename stems to full paths.
fn scan_vault_notes(vault_meetings_dir: &Path) -> std::collections::HashMap<String, PathBuf> {
    let mut notes = std::collections::HashMap::new();
    if let Ok(entries) = std::fs::read_dir(vault_meetings_dir) {
        for entry in entries.filter_map(|e| e.ok()) {
            let path = entry.path();
            if path.extension().map(|e| e == "md").unwrap_or(false) {
                if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                    notes.insert(stem.to_string(), path);
                }
            }
        }
    }
    notes
}

/// Match a MeetingSummary to a vault note by looking for "{date} - {title}.md".
fn match_vault_note(
    summary: &mut MeetingSummary,
    vault_notes: &std::collections::HashMap<String, PathBuf>,
) {
    let expected_stem = format!("{} - {}", summary.date, summary.title);
    if let Some(note_path) = vault_notes.get(&expected_stem) {
        summary.has_note = true;
        summary.note_path = Some(note_path.to_string_lossy().to_string());
    }
}

#[tauri::command]
pub async fn list_meetings(
    recordings_dir: String,
    vault_meetings_dir: String,
    cursor: Option<String>,
    limit: Option<usize>,
) -> Result<MeetingListResponse, String> {
    let recordings_path = PathBuf::from(&recordings_dir);
    let vault_path = PathBuf::from(&vault_meetings_dir);
    let limit = limit.unwrap_or(50);

    if !recordings_path.exists() {
        return Ok(MeetingListResponse { items: vec![], next_cursor: None });
    }

    let vault_notes = scan_vault_notes(&vault_path);

    // Collect all meeting.json files
    let mut summaries: Vec<MeetingSummary> = Vec::new();
    let mut seen_ids: std::collections::HashSet<String> = std::collections::HashSet::new();

    if let Ok(entries) = std::fs::read_dir(&recordings_path) {
        for entry in entries.filter_map(|e| e.ok()) {
            let path = entry.path();
            if path.extension().map(|e| e == "json").unwrap_or(false) {
                if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                    if name.ends_with(".meeting.json") {
                        if let Some(mut summary) = parse_meeting_json(&path) {
                            match_vault_note(&mut summary, &vault_notes);
                            seen_ids.insert(summary.id.clone());
                            summaries.push(summary);
                        }
                    }
                }
            }
        }
    }

    // Also pick up recording files without meeting.json (edge case 6)
    let video_exts = ["mp4", "mkv", "webm"];
    if let Ok(entries) = std::fs::read_dir(&recordings_path) {
        for entry in entries.filter_map(|e| e.ok()) {
            let path = entry.path();
            if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
                if video_exts.contains(&ext) {
                    if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                        if !seen_ids.contains(stem) {
                            if let Some(mut summary) = summary_from_filename(&path) {
                                match_vault_note(&mut summary, &vault_notes);
                                summaries.push(summary);
                            }
                        }
                    }
                }
            }
        }
    }

    // Sort by date descending
    summaries.sort_by(|a, b| b.date.cmp(&a.date));

    // Apply cursor-based pagination
    let start_index = if let Some(ref cursor_id) = cursor {
        summaries.iter().position(|s| s.id == *cursor_id)
            .map(|i| i + 1)
            .unwrap_or(0)
    } else {
        0
    };

    let page: Vec<MeetingSummary> = summaries.into_iter().skip(start_index).take(limit + 1).collect();
    let next_cursor = if page.len() > limit {
        page.get(limit - 1).map(|s| s.id.clone())
    } else {
        None
    };
    let items: Vec<MeetingSummary> = page.into_iter().take(limit).collect();

    Ok(MeetingListResponse { items, next_cursor })
}
```

**Step 2: Register the command in lib.rs**

Add `meetings::list_meetings,` to the `invoke_handler` array in `src-tauri/src/lib.rs`.

**Step 3: Verify it compiles**

Run: `cd src-tauri && cargo check 2>&1 | tail -5`

**Step 4: Commit**

```bash
git add src-tauri/src/meetings.rs src-tauri/src/lib.rs
git commit -m "feat: add list_meetings IPC command with filesystem scanning"
```

---

### Task 4: Rust IPC — get_meeting_detail and search_meetings commands

**Files:**
- Modify: `src-tauri/src/meetings.rs`
- Modify: `src-tauri/src/lib.rs:53` (register commands)

**Step 1: Implement get_meeting_detail**

Add to `meetings.rs`:

```rust
#[tauri::command]
pub async fn get_meeting_detail(
    meeting_id: String,
    recordings_dir: String,
    vault_meetings_dir: String,
    frames_dir: String,
) -> Result<MeetingDetail, String> {
    let recordings_path = PathBuf::from(&recordings_dir);
    let vault_path = PathBuf::from(&vault_meetings_dir);
    let frames_path = PathBuf::from(&frames_dir);

    // Try to load from meeting.json first
    let meeting_json_path = recordings_path.join(format!("{}.meeting.json", &meeting_id));
    let vault_notes = scan_vault_notes(&vault_path);

    let mut summary = if meeting_json_path.exists() {
        parse_meeting_json(&meeting_json_path)
            .ok_or_else(|| format!("Failed to parse meeting.json for {}", meeting_id))?
    } else {
        // Try to build from recording filename
        let video_exts = ["mp4", "mkv", "webm", "wav"];
        let recording_path = video_exts.iter()
            .map(|ext| recordings_path.join(format!("{}.{}", &meeting_id, ext)))
            .find(|p| p.exists());

        match recording_path {
            Some(path) => summary_from_filename(&path)
                .ok_or_else(|| format!("Meeting not found: {}", meeting_id))?,
            None => return Err(format!("Meeting not found: {}", meeting_id)),
        }
    };

    match_vault_note(&mut summary, &vault_notes);

    // Read note content
    let note_content = summary.note_path.as_ref()
        .and_then(|p| std::fs::read_to_string(p).ok());

    // Read transcript
    let transcript_path = recordings_path.join(format!("{}.transcript.json", &meeting_id));
    let transcript: Option<Vec<Utterance>> = if transcript_path.exists() {
        std::fs::read_to_string(&transcript_path)
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
    } else {
        None
    };

    // Scan for screenshots
    let screenshots = scan_screenshots(&meeting_id, &frames_path);

    Ok(MeetingDetail {
        summary,
        note_content,
        transcript,
        screenshots,
    })
}

/// Scan frames directory for screenshots belonging to this meeting.
fn scan_screenshots(meeting_id: &str, frames_dir: &Path) -> Vec<Screenshot> {
    let mut shots = Vec::new();
    if !frames_dir.exists() {
        return shots;
    }
    if let Ok(entries) = std::fs::read_dir(frames_dir) {
        for entry in entries.filter_map(|e| e.ok()) {
            let path = entry.path();
            if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                if name.starts_with(meeting_id) {
                    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
                    if ["png", "jpg", "jpeg"].contains(&ext) {
                        shots.push(Screenshot {
                            path: path.to_string_lossy().to_string(),
                            caption: None,
                        });
                    }
                }
            }
        }
    }
    shots.sort_by(|a, b| a.path.cmp(&b.path));
    shots
}
```

**Step 2: Implement search_meetings**

```rust
#[tauri::command]
pub async fn search_meetings(
    query: String,
    recordings_dir: String,
    vault_meetings_dir: String,
    limit: Option<usize>,
) -> Result<Vec<MeetingSummary>, String> {
    let result = list_meetings(recordings_dir, vault_meetings_dir, None, Some(1000)).await?;
    let query_lower = query.to_lowercase();
    let limit = limit.unwrap_or(50);

    let filtered: Vec<MeetingSummary> = result.items.into_iter()
        .filter(|s| {
            s.title.to_lowercase().contains(&query_lower)
                || s.participants.iter().any(|p| p.to_lowercase().contains(&query_lower))
                || s.date.contains(&query_lower)
        })
        .take(limit)
        .collect();

    Ok(filtered)
}
```

**Step 3: Register both commands in lib.rs**

Add `meetings::get_meeting_detail,` and `meetings::search_meetings,` to the invoke_handler.

**Step 4: Verify it compiles**

Run: `cd src-tauri && cargo check 2>&1 | tail -5`

**Step 5: Commit**

```bash
git add src-tauri/src/meetings.rs src-tauri/src/lib.rs
git commit -m "feat: add get_meeting_detail and search_meetings IPC commands"
```

---

### Task 5: Emit pipeline-completed event from Rust

**Files:**
- Modify: `src-tauri/src/recorder/recorder.rs:462-498` (the spawn block in stop_recording)

**Step 1: Add event emission after pipeline sidecar completes**

In the `tauri::async_runtime::spawn` block inside `stop_recording`, after the success notification (line ~478), emit an event so the frontend can refresh:

```rust
let _ = app_clone.emit("pipeline-completed", serde_json::json!({
    "success": true,
}));
```

And in the failure branches (~485 and ~494), emit:

```rust
let _ = app_clone.emit("pipeline-completed", serde_json::json!({
    "success": false,
}));
```

**Step 2: Verify it compiles**

Run: `cd src-tauri && cargo check 2>&1 | tail -5`

**Step 3: Commit**

```bash
git add src-tauri/src/recorder/recorder.rs
git commit -m "feat: emit pipeline-completed event for dashboard auto-refresh"
```

---

### Task 6: Asset Protocol Configuration

**Files:**
- Modify: `src-tauri/tauri.conf.json`
- Modify: `src-tauri/capabilities/default.json`

**Step 1: Enable asset protocol scope**

In `tauri.conf.json`, inside the `"app"` → `"security"` section, add asset protocol scope. Since recording paths are user-configured and dynamic, use a broad scope scoped to the user's drives:

```json
"security": {
  "csp": null,
  "assetProtocol": {
    "enable": true,
    "scope": {
      "allow": ["**/*"],
      "deny": []
    }
  }
}
```

Note: Tauri v2 uses `convertFileSrc` from `@tauri-apps/api` which requires the `core:default` permission (already present). The asset protocol scope in tauri.conf.json controls which paths are accessible. We use a broad scope since the user controls which folders are configured in settings.

**Step 2: Verify it compiles**

Run: `cd src-tauri && cargo check 2>&1 | tail -5`

**Step 3: Commit**

```bash
git add src-tauri/tauri.conf.json
git commit -m "feat: enable asset protocol for serving local media files to webview"
```

---

### Task 7: Install Frontend Dependencies

**Files:**
- Modify: `package.json`

**Step 1: Install vidstack and marked**

Run:
```bash
npm install vidstack marked
```

**Step 2: Commit**

```bash
git add package.json package-lock.json
git commit -m "feat: add vidstack and marked dependencies for dashboard"
```

---

### Task 8: TypeScript Types and IPC Wrappers

**Files:**
- Modify: `src/lib/tauri.ts`
- Create: `src/lib/assets.ts`

**Step 1: Add meeting types and IPC wrappers to tauri.ts**

Append to `src/lib/tauri.ts`:

```typescript
// Meeting types
export interface PipelineStageStatus {
  completed: boolean;
  timestamp: string | null;
  error: string | null;
}

export interface PipelineStatus {
  merge: PipelineStageStatus;
  frames: PipelineStageStatus;
  transcribe: PipelineStageStatus;
  diarize: PipelineStageStatus;
  analyze: PipelineStageStatus;
  export: PipelineStageStatus;
}

export interface MeetingSummary {
  id: string;
  title: string;
  date: string;
  platform: string;
  participants: string[];
  duration_seconds: number | null;
  pipeline_status: PipelineStatus;
  has_note: boolean;
  has_transcript: boolean;
  has_video: boolean;
  recording_path: string | null;
  note_path: string | null;
}

export interface Utterance {
  speaker: string;
  start: number;
  end: number;
  text: string;
}

export interface Screenshot {
  path: string;
  caption: string | null;
}

export interface MeetingDetail {
  summary: MeetingSummary;
  note_content: string | null;
  transcript: Utterance[] | null;
  screenshots: Screenshot[];
}

export interface MeetingListResponse {
  items: MeetingSummary[];
  next_cursor: string | null;
}

// Meeting IPC
export async function listMeetings(
  recordingsDir: string,
  vaultMeetingsDir: string,
  cursor?: string,
  limit?: number
): Promise<MeetingListResponse> {
  return invoke("list_meetings", { recordingsDir, vaultMeetingsDir, cursor, limit });
}

export async function getMeetingDetail(
  meetingId: string,
  recordingsDir: string,
  vaultMeetingsDir: string,
  framesDir: string
): Promise<MeetingDetail> {
  return invoke("get_meeting_detail", { meetingId, recordingsDir, vaultMeetingsDir, framesDir });
}

export async function searchMeetings(
  query: string,
  recordingsDir: string,
  vaultMeetingsDir: string,
  limit?: number
): Promise<MeetingSummary[]> {
  return invoke("search_meetings", { query, recordingsDir, vaultMeetingsDir, limit });
}

// Recorder IPC
export async function getRecorderState(): Promise<string> {
  return invoke("get_recorder_state");
}

export async function startRecording(): Promise<void> {
  return invoke("start_recording");
}

export async function stopRecording(): Promise<void> {
  return invoke("stop_recording");
}

export async function cancelRecording(): Promise<void> {
  return invoke("cancel_recording");
}

export async function retryProcessing(
  recordingDir: string,
  fromStage?: string
): Promise<void> {
  return invoke("retry_processing", { recordingDir, fromStage });
}
```

**Step 2: Create src/lib/assets.ts**

```typescript
import { convertFileSrc } from "@tauri-apps/api/core";

/**
 * Convert a local filesystem path to a URL the webview can load.
 * Uses Tauri's asset protocol via convertFileSrc.
 */
export function assetUrl(path: string): string {
  return convertFileSrc(path);
}
```

**Step 3: Commit**

```bash
git add src/lib/tauri.ts src/lib/assets.ts
git commit -m "feat: add meeting IPC wrappers, recorder commands, and asset URL utility"
```

---

### Task 9: Svelte Stores — meetings and recorder

**Files:**
- Create: `src/lib/stores/meetings.ts`
- Create: `src/lib/stores/recorder.ts`

**Step 1: Create meetings store**

```typescript
// src/lib/stores/meetings.ts
import { writable, get } from "svelte/store";
import { listen } from "@tauri-apps/api/event";
import { listMeetings, searchMeetings } from "../tauri";
import { settings } from "./settings";
import type { MeetingSummary } from "../tauri";

export const meetings = writable<MeetingSummary[]>([]);
export const loading = writable(false);
export const nextCursor = writable<string | null>(null);

function getDirs() {
  const s = get(settings);
  const vaultMeetingsDir = s.vaultPath
    ? `${s.vaultPath}/${s.meetingsFolder}`
    : "";
  return {
    recordingsDir: s.recordingsFolder,
    vaultMeetingsDir,
  };
}

export async function loadMeetings(): Promise<void> {
  const { recordingsDir, vaultMeetingsDir } = getDirs();
  if (!recordingsDir) return;

  loading.set(true);
  try {
    const result = await listMeetings(recordingsDir, vaultMeetingsDir);
    meetings.set(result.items);
    nextCursor.set(result.next_cursor);
  } finally {
    loading.set(false);
  }
}

export async function loadMore(): Promise<void> {
  const cursor = get(nextCursor);
  if (!cursor) return;

  const { recordingsDir, vaultMeetingsDir } = getDirs();
  if (!recordingsDir) return;

  loading.set(true);
  try {
    const result = await listMeetings(recordingsDir, vaultMeetingsDir, cursor);
    meetings.update((current) => [...current, ...result.items]);
    nextCursor.set(result.next_cursor);
  } finally {
    loading.set(false);
  }
}

export async function search(query: string): Promise<void> {
  const { recordingsDir, vaultMeetingsDir } = getDirs();
  if (!recordingsDir) return;

  if (!query.trim()) {
    return loadMeetings();
  }

  loading.set(true);
  try {
    const results = await searchMeetings(query, recordingsDir, vaultMeetingsDir);
    meetings.set(results);
    nextCursor.set(null);
  } finally {
    loading.set(false);
  }
}

export function setupPipelineListener(): () => void {
  let unlisten: (() => void) | null = null;

  listen("pipeline-completed", () => {
    loadMeetings();
  }).then((fn) => {
    unlisten = fn;
  });

  return () => {
    if (unlisten) unlisten();
  };
}
```

**Step 2: Create recorder store**

```typescript
// src/lib/stores/recorder.ts
import { writable } from "svelte/store";
import { listen } from "@tauri-apps/api/event";
import {
  getRecorderState,
  startRecording as ipcStart,
  stopRecording as ipcStop,
  cancelRecording as ipcCancel,
} from "../tauri";

export type RecorderState =
  | { type: "idle" }
  | { type: "detected"; process_name: string; pid: number }
  | { type: "recording" }
  | { type: "processing" }
  | { type: "declined" };

export const recorderState = writable<RecorderState>({ type: "idle" });

function parseState(raw: any): RecorderState {
  if (typeof raw === "string") {
    return { type: raw as "idle" | "recording" | "processing" | "declined" };
  }
  if (raw.detected) {
    return { type: "detected", process_name: raw.detected.process_name, pid: raw.detected.pid };
  }
  return { type: "idle" };
}

export async function initRecorderState(): Promise<void> {
  const raw = await getRecorderState();
  recorderState.set(parseState(raw));
}

export function setupRecorderListener(): () => void {
  let unlisten: (() => void) | null = null;

  listen("recorder-state-changed", (event) => {
    recorderState.set(parseState(event.payload));
  }).then((fn) => {
    unlisten = fn;
  });

  return () => {
    if (unlisten) unlisten();
  };
}

export async function startRecording(): Promise<void> {
  await ipcStart();
}

export async function stopRecording(): Promise<void> {
  await ipcStop();
}

export async function cancelRecording(): Promise<void> {
  await ipcCancel();
}
```

**Step 3: Commit**

```bash
git add src/lib/stores/meetings.ts src/lib/stores/recorder.ts
git commit -m "feat: add meetings and recorder Svelte stores"
```

---

### Task 10: Markdown Rendering Utility

**Files:**
- Create: `src/lib/markdown.ts`

**Step 1: Create marked config with wikilink extension**

```typescript
// src/lib/markdown.ts
import { Marked } from "marked";

const wikiLinkRegex = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g;
const embedRegex = /!\[\[([^\]]+)\]\]/g;

/**
 * Render Obsidian-flavored markdown to HTML.
 * Handles [[wikilinks]], [[link|display text]], and ![[embeds]].
 */
export function renderMarkdown(content: string, assetUrlFn?: (path: string) => string): string {
  // Pre-process Obsidian syntax before passing to marked
  let processed = content;

  // Replace ![[image.png]] with standard markdown image syntax
  processed = processed.replace(embedRegex, (_match, filename: string) => {
    const url = assetUrlFn ? assetUrlFn(filename) : filename;
    return `![${filename}](${url})`;
  });

  // Replace [[link|text]] and [[link]] with HTML spans (no navigation in dashboard)
  processed = processed.replace(wikiLinkRegex, (_match, link: string, display?: string) => {
    return `<span class="wikilink">${display || link}</span>`;
  });

  const marked = new Marked();
  return marked.parse(processed) as string;
}
```

**Step 2: Commit**

```bash
git add src/lib/markdown.ts
git commit -m "feat: add markdown rendering with Obsidian wikilink support"
```

---

### Task 11: Utility Components — PipelineStatusBadge, SearchBar, RecordingStatusBar

**Files:**
- Create: `src/lib/components/PipelineStatusBadge.svelte`
- Create: `src/lib/components/SearchBar.svelte`
- Create: `src/lib/components/RecordingStatusBar.svelte`

**Step 1: Create PipelineStatusBadge**

```svelte
<!-- src/lib/components/PipelineStatusBadge.svelte -->
<script lang="ts">
  import type { PipelineStatus } from "../tauri";

  let { status }: { status: PipelineStatus } = $props();

  function getState(): { label: string; color: string } {
    const stages = ["merge", "frames", "transcribe", "diarize", "analyze", "export"] as const;

    // Check for failures
    for (const stage of stages) {
      if (status[stage].error) {
        return { label: `Failed: ${stage}`, color: "bg-red-100 text-red-700" };
      }
    }

    // Check if all completed
    const allDone = stages.every((s) => status[s].completed);
    if (allDone) {
      return { label: "Completed", color: "bg-green-100 text-green-700" };
    }

    // Check if any in progress (completed some but not all, no errors)
    const anyCompleted = stages.some((s) => status[s].completed);
    if (anyCompleted) {
      const currentStage = stages.find((s) => !status[s].completed);
      return { label: `Processing: ${currentStage}`, color: "bg-yellow-100 text-yellow-700" };
    }

    return { label: "Pending", color: "bg-gray-100 text-gray-600" };
  }

  let state = $derived(getState());
</script>

<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {state.color}">
  {state.label}
</span>
```

**Step 2: Create SearchBar**

```svelte
<!-- src/lib/components/SearchBar.svelte -->
<script lang="ts">
  let { onSearch }: { onSearch: (query: string) => void } = $props();

  let query = $state("");
  let debounceTimer: ReturnType<typeof setTimeout>;

  function handleInput() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      onSearch(query);
    }, 300);
  }
</script>

<div class="relative">
  <input
    type="text"
    bind:value={query}
    oninput={handleInput}
    placeholder="Search meetings..."
    class="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
  />
  <svg class="absolute left-3 top-2.5 h-4 w-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
  </svg>
</div>
```

**Step 3: Create RecordingStatusBar**

```svelte
<!-- src/lib/components/RecordingStatusBar.svelte -->
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { recorderState, stopRecording, cancelRecording } from "../stores/recorder";

  let elapsed = $state(0);
  let interval: ReturnType<typeof setInterval> | null = null;

  function formatTime(seconds: number): string {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return h > 0
      ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
      : `${m}:${String(s).padStart(2, "0")}`;
  }

  onMount(() => {
    interval = setInterval(() => {
      elapsed += 1;
    }, 1000);
  });

  onDestroy(() => {
    if (interval) clearInterval(interval);
  });
</script>

{#if $recorderState.type === "recording"}
  <div class="bg-red-50 border-b border-red-200 px-4 py-2 flex items-center justify-between">
    <div class="flex items-center gap-3">
      <span class="relative flex h-3 w-3">
        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
        <span class="relative inline-flex rounded-full h-3 w-3 bg-red-500"></span>
      </span>
      <span class="text-sm font-medium text-red-700">Recording</span>
      <span class="text-sm text-red-600 font-mono">{formatTime(elapsed)}</span>
    </div>
    <div class="flex gap-2">
      <button
        onclick={() => stopRecording()}
        class="px-3 py-1 text-xs font-medium bg-red-600 text-white rounded hover:bg-red-700"
      >
        Stop
      </button>
      <button
        onclick={() => cancelRecording()}
        class="px-3 py-1 text-xs font-medium bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
      >
        Cancel
      </button>
    </div>
  </div>
{:else if $recorderState.type === "detected"}
  <div class="bg-yellow-50 border-b border-yellow-200 px-4 py-2 flex items-center justify-between">
    <span class="text-sm text-yellow-700">
      Meeting detected: {$recorderState.process_name}
    </span>
    <button
      onclick={() => import("../stores/recorder").then(m => m.startRecording())}
      class="px-3 py-1 text-xs font-medium bg-yellow-600 text-white rounded hover:bg-yellow-700"
    >
      Start Recording
    </button>
  </div>
{:else if $recorderState.type === "processing"}
  <div class="bg-blue-50 border-b border-blue-200 px-4 py-2 flex items-center gap-2">
    <svg class="animate-spin h-4 w-4 text-blue-600" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
    <span class="text-sm text-blue-700">Processing recording...</span>
  </div>
{/if}
```

**Step 4: Commit**

```bash
git add src/lib/components/PipelineStatusBadge.svelte src/lib/components/SearchBar.svelte src/lib/components/RecordingStatusBar.svelte
git commit -m "feat: add PipelineStatusBadge, SearchBar, and RecordingStatusBar components"
```

---

### Task 12: MeetingRow and MeetingList Components

**Files:**
- Create: `src/lib/components/MeetingRow.svelte`
- Create: `src/lib/components/MeetingList.svelte`

**Step 1: Create MeetingRow**

```svelte
<!-- src/lib/components/MeetingRow.svelte -->
<script lang="ts">
  import type { MeetingSummary } from "../tauri";
  import PipelineStatusBadge from "./PipelineStatusBadge.svelte";

  let { meeting }: { meeting: MeetingSummary } = $props();

  function formatDuration(seconds: number | null): string {
    if (!seconds) return "";
    const m = Math.round(seconds / 60);
    return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`;
  }

  function platformLabel(platform: string): string {
    const labels: Record<string, string> = {
      zoom: "Zoom",
      teams: "Teams",
      google: "Google Meet",
      zoho: "Zoho Meet",
      unknown: "Unknown",
    };
    return labels[platform] || platform;
  }
</script>

<a
  href="#meeting/{meeting.id}"
  class="block px-4 py-3 hover:bg-gray-50 border-b border-gray-100 transition-colors"
>
  <div class="flex items-start justify-between">
    <div class="min-w-0 flex-1">
      <h3 class="text-sm font-medium text-gray-900 truncate">{meeting.title}</h3>
      <p class="text-xs text-gray-500 mt-0.5">
        {meeting.date}
        {#if meeting.platform !== "unknown"} · {platformLabel(meeting.platform)}{/if}
        {#if meeting.duration_seconds} · {formatDuration(meeting.duration_seconds)}{/if}
        {#if meeting.participants.length > 0}
          · {meeting.participants.length} participant{meeting.participants.length !== 1 ? "s" : ""}
        {/if}
      </p>
    </div>
    <div class="ml-3 flex-shrink-0">
      <PipelineStatusBadge status={meeting.pipeline_status} />
    </div>
  </div>
</a>
```

**Step 2: Create MeetingList**

```svelte
<!-- src/lib/components/MeetingList.svelte -->
<script lang="ts">
  import type { MeetingSummary } from "../tauri";
  import MeetingRow from "./MeetingRow.svelte";

  let {
    meetings,
    hasMore,
    isLoading,
    onLoadMore,
  }: {
    meetings: MeetingSummary[];
    hasMore: boolean;
    isLoading: boolean;
    onLoadMore: () => void;
  } = $props();
</script>

{#if meetings.length === 0 && !isLoading}
  <div class="text-center py-16 px-4">
    <p class="text-gray-500 text-sm">No meetings recorded yet.</p>
    <p class="text-gray-400 text-xs mt-1">Start a Zoom call and Recap will detect it automatically.</p>
  </div>
{:else}
  <div class="divide-y divide-gray-100">
    {#each meetings as meeting (meeting.id)}
      <MeetingRow {meeting} />
    {/each}
  </div>

  {#if hasMore}
    <div class="p-4 text-center">
      <button
        onclick={onLoadMore}
        disabled={isLoading}
        class="text-sm text-blue-600 hover:text-blue-800 disabled:text-gray-400"
      >
        {isLoading ? "Loading..." : "Load more"}
      </button>
    </div>
  {/if}
{/if}
```

**Step 3: Commit**

```bash
git add src/lib/components/MeetingRow.svelte src/lib/components/MeetingList.svelte
git commit -m "feat: add MeetingRow and MeetingList components"
```

---

### Task 13: Dashboard List View

**Files:**
- Modify: `src/routes/Dashboard.svelte` (replace placeholder)

**Step 1: Implement the Dashboard list view**

```svelte
<!-- src/routes/Dashboard.svelte -->
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import SearchBar from "../lib/components/SearchBar.svelte";
  import MeetingList from "../lib/components/MeetingList.svelte";
  import RecordingStatusBar from "../lib/components/RecordingStatusBar.svelte";
  import {
    meetings,
    loading,
    nextCursor,
    loadMeetings,
    loadMore,
    search,
    setupPipelineListener,
  } from "../lib/stores/meetings";
  import { recorderState, initRecorderState, setupRecorderListener } from "../lib/stores/recorder";

  let cleanupPipeline: (() => void) | null = null;
  let cleanupRecorder: (() => void) | null = null;

  onMount(async () => {
    await initRecorderState();
    await loadMeetings();
    cleanupPipeline = setupPipelineListener();
    cleanupRecorder = setupRecorderListener();
  });

  onDestroy(() => {
    if (cleanupPipeline) cleanupPipeline();
    if (cleanupRecorder) cleanupRecorder();
  });

  function handleSearch(query: string) {
    search(query);
  }
</script>

<div class="min-h-screen bg-gray-50">
  <RecordingStatusBar />

  <div class="max-w-3xl mx-auto p-8">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold text-gray-900">Recap</h1>
      <a href="#settings" class="text-gray-400 hover:text-gray-600">
        <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      </a>
    </div>

    <div class="mb-4">
      <SearchBar onSearch={handleSearch} />
    </div>

    <div class="bg-white rounded-lg shadow-sm border border-gray-200">
      <MeetingList
        meetings={$meetings}
        hasMore={$nextCursor !== null}
        isLoading={$loading}
        onLoadMore={loadMore}
      />
    </div>
  </div>
</div>
```

**Step 2: Commit**

```bash
git add src/routes/Dashboard.svelte
git commit -m "feat: implement Dashboard list view with search and pagination"
```

---

### Task 14: Detail View Components — MeetingHeader, RetryBanner

**Files:**
- Create: `src/lib/components/MeetingHeader.svelte`
- Create: `src/lib/components/RetryBanner.svelte`

**Step 1: Create MeetingHeader**

```svelte
<!-- src/lib/components/MeetingHeader.svelte -->
<script lang="ts">
  import type { MeetingSummary } from "../tauri";

  let { meeting }: { meeting: MeetingSummary } = $props();

  function formatDuration(seconds: number | null): string {
    if (!seconds) return "";
    const m = Math.round(seconds / 60);
    return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`;
  }

  function platformLabel(platform: string): string {
    const labels: Record<string, string> = {
      zoom: "Zoom", teams: "Teams", google: "Google Meet",
      zoho: "Zoho Meet", unknown: "Unknown",
    };
    return labels[platform] || platform;
  }
</script>

<div class="mb-6">
  <h1 class="text-xl font-bold text-gray-900">{meeting.title}</h1>
  <p class="text-sm text-gray-500 mt-1">
    {meeting.date}
    {#if meeting.platform !== "unknown"} · {platformLabel(meeting.platform)}{/if}
    {#if meeting.duration_seconds} · {formatDuration(meeting.duration_seconds)}{/if}
    {#if meeting.participants.length > 0}
      · {meeting.participants.join(", ")}
    {/if}
  </p>
</div>
```

**Step 2: Create RetryBanner**

```svelte
<!-- src/lib/components/RetryBanner.svelte -->
<script lang="ts">
  import type { PipelineStatus } from "../tauri";
  import { retryProcessing } from "../tauri";

  let {
    status,
    hasRecording,
    hasNote,
    hasTranscript,
    recordingDir,
  }: {
    status: PipelineStatus;
    hasRecording: boolean;
    hasNote: boolean;
    hasTranscript: boolean;
    recordingDir: string;
  } = $props();

  let retrying = $state(false);

  const stages = ["merge", "frames", "transcribe", "diarize", "analyze", "export"] as const;

  function getFailedStage(): string | null {
    for (const stage of stages) {
      if (status[stage].error) return stage;
    }
    return null;
  }

  let failedStage = $derived(getFailedStage());

  function getRetryActions(): { label: string; fromStage: string }[] {
    const actions: { label: string; fromStage: string }[] = [];

    if (failedStage) {
      actions.push({ label: `Retry from ${failedStage}`, fromStage: failedStage });
    }

    if (hasRecording && !hasTranscript && !failedStage) {
      actions.push({ label: "Re-transcribe", fromStage: "transcribe" });
    }

    if (hasRecording && !hasNote && !failedStage) {
      const analyzeComplete = status.analyze.completed;
      actions.push({
        label: "Generate Note",
        fromStage: analyzeComplete ? "export" : "analyze",
      });
    }

    return actions;
  }

  let retryActions = $derived(getRetryActions());

  async function handleRetry(fromStage: string) {
    retrying = true;
    try {
      await retryProcessing(recordingDir, fromStage);
    } catch (err) {
      console.error("Retry failed:", err);
    } finally {
      retrying = false;
    }
  }
</script>

{#if failedStage}
  <div class="bg-red-50 border border-red-200 rounded-lg p-3 mb-4 flex items-center justify-between">
    <div class="text-sm text-red-700">
      Pipeline failed at <span class="font-medium">{failedStage}</span>
      {#if status[failedStage]?.error}
        <span class="text-red-500 text-xs block mt-0.5">{status[failedStage].error}</span>
      {/if}
    </div>
    <div class="flex gap-2">
      {#each retryActions as action}
        <button
          onclick={() => handleRetry(action.fromStage)}
          disabled={retrying}
          class="px-3 py-1 text-xs font-medium bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
        >
          {retrying ? "Retrying..." : action.label}
        </button>
      {/each}
    </div>
  </div>
{:else if retryActions.length > 0}
  <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-4 flex items-center justify-between">
    <span class="text-sm text-yellow-700">
      {#if !hasTranscript}Transcript unavailable.{/if}
      {#if !hasNote}No meeting note generated.{/if}
    </span>
    <div class="flex gap-2">
      {#each retryActions as action}
        <button
          onclick={() => handleRetry(action.fromStage)}
          disabled={retrying}
          class="px-3 py-1 text-xs font-medium bg-yellow-600 text-white rounded hover:bg-yellow-700 disabled:opacity-50"
        >
          {retrying ? "Processing..." : action.label}
        </button>
      {/each}
    </div>
  </div>
{/if}
```

**Step 3: Commit**

```bash
git add src/lib/components/MeetingHeader.svelte src/lib/components/RetryBanner.svelte
git commit -m "feat: add MeetingHeader and RetryBanner components"
```

---

### Task 15: MeetingPlayer Component (Vidstack)

**Files:**
- Create: `src/lib/components/MeetingPlayer.svelte`

**Step 1: Create vidstack player wrapper**

Consult vidstack docs for the exact Svelte 5 integration API. The component should:

- Accept a `src` prop (asset URL to the recording)
- Accept an `audioOnly` prop (boolean, determines if video or audio layout is used)
- Expose a `seek(time: number)` function for transcript timestamp clicks
- Use vidstack's default UI layout

```svelte
<!-- src/lib/components/MeetingPlayer.svelte -->
<script lang="ts">
  import "vidstack/player/styles/default/theme.css";
  import "vidstack/player/styles/default/layouts/video.css";
  import "vidstack/player/styles/default/layouts/audio.css";
  import "vidstack/player";
  import "vidstack/player/layouts/default";
  import "vidstack/player/ui";

  let { src, audioOnly = false }: { src: string; audioOnly?: boolean } = $props();

  let playerRef: HTMLElement | null = $state(null);

  export function seek(time: number) {
    if (playerRef) {
      const player = playerRef as any;
      if (player.currentTime !== undefined) {
        player.currentTime = time;
      }
    }
  }
</script>

{#if src}
  <div class="rounded-lg overflow-hidden bg-black">
    {#if audioOnly}
      <media-player bind:this={playerRef} {src} class="w-full">
        <media-provider />
        <media-audio-layout />
      </media-player>
    {:else}
      <media-player bind:this={playerRef} {src} class="w-full aspect-video">
        <media-provider />
        <media-video-layout />
      </media-player>
    {/if}
  </div>
{:else}
  <div class="rounded-lg bg-gray-100 flex items-center justify-center py-12">
    <p class="text-sm text-gray-400">Recording file not found</p>
  </div>
{/if}
```

Note: The exact vidstack Svelte 5 API may differ. Check their docs at `https://vidstack.io/docs` during implementation and adjust the imports and component usage accordingly. The key requirements are: (1) plays local files via asset URL, (2) handles audio-only, (3) supports programmatic seeking.

**Step 2: Commit**

```bash
git add src/lib/components/MeetingPlayer.svelte
git commit -m "feat: add MeetingPlayer component wrapping vidstack"
```

---

### Task 16: MeetingNotes and MeetingTranscript Components

**Files:**
- Create: `src/lib/components/MeetingNotes.svelte`
- Create: `src/lib/components/MeetingTranscript.svelte`

**Step 1: Create MeetingNotes**

```svelte
<!-- src/lib/components/MeetingNotes.svelte -->
<script lang="ts">
  import { renderMarkdown } from "../markdown";

  let { content }: { content: string | null } = $props();

  let html = $derived(content ? renderMarkdown(content) : "");
</script>

{#if content}
  <div class="prose prose-sm max-w-none">
    {@html html}
  </div>
{:else}
  <div class="text-center py-8">
    <p class="text-sm text-gray-400">No meeting note generated.</p>
  </div>
{/if}
```

Note: `prose` classes require `@tailwindcss/typography`. If not already installed, add it in this task: `npm install @tailwindcss/typography` and add to Tailwind config.

**Step 2: Create MeetingTranscript**

```svelte
<!-- src/lib/components/MeetingTranscript.svelte -->
<script lang="ts">
  import type { Utterance } from "../tauri";

  let {
    utterances,
    onSeek,
  }: {
    utterances: Utterance[] | null;
    onSeek: (time: number) => void;
  } = $props();

  function formatTimestamp(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  // Assign consistent colors to speakers
  const speakerColors = [
    "text-blue-700", "text-green-700", "text-purple-700",
    "text-orange-700", "text-pink-700", "text-teal-700",
  ];

  function getSpeakerColor(speaker: string, speakers: string[]): string {
    const index = speakers.indexOf(speaker);
    return speakerColors[index % speakerColors.length];
  }

  let speakers = $derived(
    utterances ? [...new Set(utterances.map((u) => u.speaker))] : []
  );
</script>

{#if utterances && utterances.length > 0}
  <div class="space-y-3 max-h-96 overflow-y-auto">
    {#each utterances as utterance}
      <div class="flex gap-3 text-sm">
        <button
          onclick={() => onSeek(utterance.start)}
          class="flex-shrink-0 text-xs text-gray-400 hover:text-blue-600 font-mono pt-0.5 cursor-pointer"
          title="Jump to {formatTimestamp(utterance.start)}"
        >
          {formatTimestamp(utterance.start)}
        </button>
        <div>
          <span class="font-medium {getSpeakerColor(utterance.speaker, speakers)}">
            {utterance.speaker}
          </span>
          <span class="text-gray-700 ml-1">{utterance.text}</span>
        </div>
      </div>
    {/each}
  </div>
{:else}
  <div class="text-center py-8">
    <p class="text-sm text-gray-400">Transcript unavailable.</p>
  </div>
{/if}
```

**Step 3: Commit**

```bash
git add src/lib/components/MeetingNotes.svelte src/lib/components/MeetingTranscript.svelte
git commit -m "feat: add MeetingNotes and MeetingTranscript components"
```

---

### Task 17: ScreenshotGallery Component

**Files:**
- Create: `src/lib/components/ScreenshotGallery.svelte`

**Step 1: Create ScreenshotGallery**

```svelte
<!-- src/lib/components/ScreenshotGallery.svelte -->
<script lang="ts">
  import type { Screenshot } from "../tauri";
  import { assetUrl } from "../assets";

  let { screenshots }: { screenshots: Screenshot[] } = $props();
</script>

{#if screenshots.length > 0}
  <div class="mt-6">
    <h2 class="text-sm font-semibold text-gray-700 mb-3">Screenshots</h2>
    <div class="grid grid-cols-3 gap-3">
      {#each screenshots as screenshot}
        <div class="rounded-lg overflow-hidden border border-gray-200">
          <img
            src={assetUrl(screenshot.path)}
            alt={screenshot.caption || "Meeting screenshot"}
            class="w-full h-auto"
            loading="lazy"
          />
          {#if screenshot.caption}
            <p class="text-xs text-gray-500 p-2">{screenshot.caption}</p>
          {/if}
        </div>
      {/each}
    </div>
  </div>
{/if}
```

**Step 2: Commit**

```bash
git add src/lib/components/ScreenshotGallery.svelte
git commit -m "feat: add ScreenshotGallery component"
```

---

### Task 18: MeetingDetail View

**Files:**
- Create: `src/routes/MeetingDetail.svelte`
- Modify: `src/App.svelte` (add routing for `#meeting/{id}`)

**Step 1: Create MeetingDetail**

```svelte
<!-- src/routes/MeetingDetail.svelte -->
<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { getMeetingDetail } from "../lib/tauri";
  import { settings } from "../lib/stores/settings";
  import { assetUrl } from "../lib/assets";
  import type { MeetingDetail as MeetingDetailType } from "../lib/tauri";
  import MeetingHeader from "../lib/components/MeetingHeader.svelte";
  import MeetingPlayer from "../lib/components/MeetingPlayer.svelte";
  import MeetingNotes from "../lib/components/MeetingNotes.svelte";
  import MeetingTranscript from "../lib/components/MeetingTranscript.svelte";
  import ScreenshotGallery from "../lib/components/ScreenshotGallery.svelte";
  import RetryBanner from "../lib/components/RetryBanner.svelte";

  let { meetingId }: { meetingId: string } = $props();

  let detail = $state<MeetingDetailType | null>(null);
  let error = $state<string | null>(null);
  let activeTab = $state<"notes" | "transcript">("notes");
  let playerComponent: MeetingPlayer | null = $state(null);

  onMount(async () => {
    const s = get(settings);
    const vaultMeetingsDir = s.vaultPath ? `${s.vaultPath}/${s.meetingsFolder}` : "";
    const framesDir = s.recordingsFolder ? `${s.recordingsFolder}/frames` : "";

    try {
      detail = await getMeetingDetail(meetingId, s.recordingsFolder, vaultMeetingsDir, framesDir);
    } catch (err) {
      error = String(err);
    }
  });

  function handleSeek(time: number) {
    if (playerComponent) {
      playerComponent.seek(time);
    }
  }
</script>

<div class="min-h-screen bg-gray-50">
  <div class="max-w-3xl mx-auto p-8">
    <div class="flex items-center justify-between mb-6">
      <a href="#dashboard" class="text-sm text-blue-600 hover:underline">← Back to Dashboard</a>
      <a href="#settings" class="text-gray-400 hover:text-gray-600">
        <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      </a>
    </div>

    {#if error}
      <div class="bg-red-50 border border-red-200 rounded-lg p-4">
        <p class="text-sm text-red-700">Failed to load meeting: {error}</p>
      </div>
    {:else if !detail}
      <p class="text-gray-400 text-center py-16">Loading...</p>
    {:else}
      <MeetingHeader meeting={detail.summary} />

      <RetryBanner
        status={detail.summary.pipeline_status}
        hasRecording={detail.summary.has_video}
        hasNote={detail.summary.has_note}
        hasTranscript={detail.summary.has_transcript}
        recordingDir={detail.summary.recording_path ? detail.summary.recording_path.replace(/[^/\\]+$/, '') : ''}
      />

      <MeetingPlayer
        bind:this={playerComponent}
        src={detail.summary.recording_path ? assetUrl(detail.summary.recording_path) : ""}
        audioOnly={!detail.summary.has_video}
      />

      <!-- Tabs -->
      <div class="mt-6">
        <div class="border-b border-gray-200">
          <nav class="flex gap-6">
            <button
              onclick={() => activeTab = "notes"}
              class="pb-2 text-sm font-medium border-b-2 transition-colors {activeTab === 'notes'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'}"
            >
              Notes
            </button>
            <button
              onclick={() => activeTab = "transcript"}
              class="pb-2 text-sm font-medium border-b-2 transition-colors {activeTab === 'transcript'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'}"
            >
              Transcript
            </button>
          </nav>
        </div>

        <div class="mt-4">
          {#if activeTab === "notes"}
            <MeetingNotes content={detail.note_content} />
          {:else}
            <MeetingTranscript utterances={detail.transcript} onSeek={handleSeek} />
          {/if}
        </div>
      </div>

      <ScreenshotGallery screenshots={detail.screenshots} />
    {/if}
  </div>
</div>
```

**Step 2: Update App.svelte routing**

Modify `src/App.svelte` to handle the `#meeting/{id}` route. Add the import and route logic:

Import `MeetingDetail` alongside the other route imports. Update the route parsing to extract the meeting ID:

```svelte
<script lang="ts">
  // ... existing imports ...
  import MeetingDetail from "./routes/MeetingDetail.svelte";

  let currentRoute = $state("dashboard");
  let routeParams = $state<Record<string, string>>({});
  // ... existing state ...

  onMount(async () => {
    // ... existing init code ...

    const updateRoute = () => {
      const hash = window.location.hash.slice(1) || "dashboard";
      if (hash.startsWith("meeting/")) {
        currentRoute = "meeting";
        routeParams = { id: hash.slice("meeting/".length) };
      } else {
        currentRoute = hash;
        routeParams = {};
      }
    };
    // ... rest of onMount ...
  });
</script>

<main class="min-h-screen bg-gray-50">
  {#if !initialized}
    <div class="flex items-center justify-center h-screen">
      <p class="text-gray-400">Loading...</p>
    </div>
  {:else if currentRoute === "settings"}
    <Settings />
  {:else if currentRoute === "meeting"}
    <MeetingDetail meetingId={routeParams.id} />
  {:else}
    <Dashboard />
  {/if}
</main>
```

**Step 3: Commit**

```bash
git add src/routes/MeetingDetail.svelte src/App.svelte
git commit -m "feat: implement MeetingDetail view with routing"
```

---

### Task 19: Install @tailwindcss/typography (if needed for prose classes)

**Step 1: Check if @tailwindcss/typography is needed**

The MeetingNotes component uses `prose` classes from Tailwind Typography. Check if Tailwind CSS v4 includes typography by default or if it needs a separate plugin.

If needed:

```bash
npm install @tailwindcss/typography
```

And add the import to `src/app.css`:

```css
@import "tailwindcss";
@import "@tailwindcss/typography";
```

**Step 2: Commit (if changes made)**

```bash
git add package.json package-lock.json src/app.css
git commit -m "feat: add tailwind typography plugin for meeting notes rendering"
```

---

### Task 20: Integration Smoke Test

**Step 1: Build and verify everything compiles**

Run:
```bash
cd src-tauri && cargo check 2>&1 | tail -10
```

Then:
```bash
npm run build 2>&1 | tail -10
```

Fix any compilation errors.

**Step 2: Launch dev mode and verify basic functionality**

Run: `npm run tauri dev`

Verify:
- App launches, shows dashboard (empty state since no recordings exist)
- Settings link works
- No console errors
- Search bar is rendered
- Recording status bar is hidden (no active recording)

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve integration issues from Phase 5a dashboard implementation"
```

---

### Task 21: Update MANIFEST.md

**Files:**
- Modify: `MANIFEST.md`

**Step 1: Update the structural map**

Add the new files to the Structure section and update Key Relationships to reflect:
- `meetings.rs` scans filesystem and exposes IPC commands
- `meetings.ts` store wraps IPC calls, listens for pipeline-completed events
- `recorder.ts` store wraps recorder state events
- `MeetingDetail.svelte` coordinates player seeking from transcript clicks
- `App.svelte` now routes to three views (dashboard, meeting detail, settings)

**Step 2: Commit**

```bash
git add MANIFEST.md
git commit -m "docs: update MANIFEST.md with Phase 5a dashboard components"
```

---

Plan complete and saved to `docs/plans/2026-03-17-phase-5a-dashboard-impl.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints

Which approach?