# Phase 4: Zoom Auto-Capture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically detect Zoom meetings, capture audio (dual WASAPI: remote + local mic) and video (Windows Graphics Capture API at 30fps), merge into a single MP4, fetch Zoom API metadata, and run the existing pipeline — all triggered from the system tray with configurable auto-record behavior.

**Architecture:** A Rust-side state machine (`recorder.rs`) orchestrates the lifecycle: `monitor.rs` detects Zoom audio sessions via WASAPI, `capture.rs` runs dual audio + video capture on dedicated threads, `zoom.rs` enriches metadata from the Zoom REST API, and `sidecar.rs` (existing) invokes the Python pipeline. The pipeline gains `--from` stage restart support. Settings UI adds recording behavior preferences.

**Tech Stack:** Rust (`windows` crate for WASAPI/Graphics Capture/COM, `tauri-plugin-notification`), ffmpeg (H.265 NVENC merge), Python (existing pipeline with stage checkpointing)

---

## Task 1: Add Windows Crate Dependencies

**Files:**
- Modify: `src-tauri/Cargo.toml`

**Step 1: Write the failing build**

Add the `windows` crate with the required feature flags for WASAPI, Graphics Capture, and process enumeration. Also add `tauri-plugin-notification`.

```toml
# Add to [dependencies] in src-tauri/Cargo.toml:
windows = { version = "0.58", features = [
    "Win32_Media_Audio",
    "Win32_System_Com",
    "Win32_System_Threading",
    "Win32_Foundation",
    "Win32_Security",
    "Graphics_Capture",
    "Graphics_DirectX",
    "Graphics_DirectX_Direct3D11",
    "Graphics_Imaging",
    "Win32_Graphics_Direct3D11",
    "Win32_Graphics_Dxgi",
    "Win32_UI_WindowsAndMessaging",
    "Foundation",
    "Foundation_Collections",
] }
tauri-plugin-notification = "2"
```

**Step 2: Verify build**

Run: `cd src-tauri && cargo check`
Expected: compiles with new deps resolved

**Step 3: Register notification plugin in lib.rs**

Add `.plugin(tauri_plugin_notification::init())` to the Tauri builder in `src-tauri/src/lib.rs` after the existing plugin registrations (around line 12).

**Step 4: Add notification permission**

Add `"notification:default"` to `src-tauri/capabilities/default.json` permissions array.

**Step 5: Verify build again**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 6: Commit**

```bash
git add src-tauri/Cargo.toml src-tauri/src/lib.rs src-tauri/capabilities/default.json
git commit -m "feat: add windows crate + notification plugin for Phase 4 capture"
```

---

## Task 2: Recorder State Machine Types

**Files:**
- Create: `src-tauri/src/recorder/mod.rs`
- Create: `src-tauri/src/recorder/types.rs`
- Modify: `src-tauri/src/lib.rs` (add `mod recorder`)

**Step 1: Define the state types**

Create `src-tauri/src/recorder/types.rs`:

```rust
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::time::Instant;

/// Recording session lifecycle states.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecorderState {
    /// No meeting detected, monitoring for audio sessions.
    Idle,
    /// Meeting audio session detected, awaiting user response or auto-record.
    Detected { process_name: String, pid: u32 },
    /// Actively capturing audio + video.
    Recording,
    /// Capture stopped, merging and processing.
    Processing,
    /// User declined recording for this session.
    Declined,
}

/// What to do when a meeting is detected.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DetectionAction {
    /// Show a notification and ask the user.
    Ask,
    /// Always start recording immediately.
    AlwaysRecord,
    /// Never record (monitoring still runs for manual start).
    NeverRecord,
}

/// What to do when the notification times out.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TimeoutAction {
    Record,
    Skip,
}

/// Configuration for recording behavior. Read from settings store.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecordingConfig {
    pub auto_detect: bool,
    pub detection_action: DetectionAction,
    pub timeout_action: TimeoutAction,
    pub timeout_seconds: u64,
}

impl Default for RecordingConfig {
    fn default() -> Self {
        Self {
            auto_detect: true,
            detection_action: DetectionAction::Ask,
            timeout_action: TimeoutAction::Record,
            timeout_seconds: 60,
        }
    }
}

/// Info about an active recording session.
#[derive(Debug)]
pub struct RecordingSession {
    pub process_name: String,
    pub pid: u32,
    pub started_at: Instant,
    pub working_dir: PathBuf,
    pub remote_audio_path: PathBuf,
    pub local_audio_path: PathBuf,
    pub video_path: PathBuf,
}

/// Pipeline stage for restart support.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PipelineStage {
    Merge,
    Frames,
    Transcribe,
    Diarize,
    Analyze,
    Export,
}

/// Status of a pipeline run, written to status.json.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StageStatus {
    pub completed: bool,
    pub timestamp: Option<String>,
    pub error: Option<String>,
}

/// Full pipeline status for a recording.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PipelineStatus {
    pub merge: StageStatus,
    pub frames: StageStatus,
    pub transcribe: StageStatus,
    pub diarize: StageStatus,
    pub analyze: StageStatus,
    pub export: StageStatus,
}

impl Default for PipelineStatus {
    fn default() -> Self {
        let empty = || StageStatus {
            completed: false,
            timestamp: None,
            error: None,
        };
        Self {
            merge: empty(),
            frames: empty(),
            transcribe: empty(),
            diarize: empty(),
            analyze: empty(),
            export: empty(),
        }
    }
}
```

**Step 2: Create the module file**

Create `src-tauri/src/recorder/mod.rs`:

```rust
pub mod types;
```

**Step 3: Register the module in lib.rs**

Add `mod recorder;` to `src-tauri/src/lib.rs` after the existing mod declarations (after line 6).

**Step 4: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 5: Commit**

```bash
git add src-tauri/src/recorder/
git commit -m "feat: add recorder state machine types and pipeline stage definitions"
```

---

## Task 3: Process Monitor (monitor.rs)

**Files:**
- Create: `src-tauri/src/recorder/monitor.rs`
- Modify: `src-tauri/src/recorder/mod.rs`

**Step 1: Implement the process monitor**

Create `src-tauri/src/recorder/monitor.rs`. This module polls for known meeting processes with active audio sessions using WASAPI audio session enumeration.

The monitor should:
1. Use `IAudioSessionManager2` to enumerate audio sessions on the default audio render endpoint
2. Match sessions by process name against a known list: `Zoom.exe`, `Teams.exe`, `msedge.exe`, `chrome.exe`, etc.
3. For browser-based meetings (Edge, Chrome), this is a heuristic — for now, only match `Zoom.exe` and `Teams.exe` directly
4. On startup, check for **already-active** sessions (in case Recap starts mid-meeting)
5. Return the process name and PID when a match is found

Key APIs:
- `IMMDeviceEnumerator::GetDefaultAudioEndpoint`
- `IMMDevice::Activate` → `IAudioSessionManager2`
- `IAudioSessionManager2::GetSessionEnumerator`
- `IAudioSessionControl2::GetProcessId`
- `OpenProcess` + `QueryFullProcessImageNameW` to get process name from PID

The monitor runs on a background thread, polling every 2 seconds. It sends events through a `tokio::sync::mpsc` channel:
- `MonitorEvent::MeetingDetected { process_name, pid }`
- `MonitorEvent::MeetingEnded { pid }`

Provide a `start_monitoring(tx: mpsc::Sender<MonitorEvent>) -> JoinHandle` function and a `stop_monitoring()` via a shared `AtomicBool`.

**Step 2: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS (no tests yet — WASAPI requires a real audio device)

**Step 3: Commit**

```bash
git add src-tauri/src/recorder/monitor.rs src-tauri/src/recorder/mod.rs
git commit -m "feat: add WASAPI audio session monitor for meeting detection"
```

---

## Task 4: Audio Capture (capture.rs — audio portion)

**Files:**
- Create: `src-tauri/src/recorder/capture.rs`
- Modify: `src-tauri/src/recorder/mod.rs`

**Step 1: Implement dual audio capture**

Create `src-tauri/src/recorder/capture.rs`. This module handles:

**Remote audio (other participants):**
- Use `ActivateAudioInterfaceAsync` with `AUDIOCLIENT_ACTIVATION_PARAMS` specifying the target PID and `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE`
- This captures only Zoom's audio output (other participants' voices)
- Write PCM data to a WAV file

**Local audio (your microphone):**
- Use standard WASAPI capture on the default recording device
- Listen for device change events via `IMMNotificationClient` — if the default device changes mid-meeting, detach from the old device and re-attach to the new one
- Write PCM data to a separate WAV file

**Interface:**

```rust
pub struct AudioCapture {
    // Internal handles
}

impl AudioCapture {
    /// Start capturing remote audio from the specified process.
    pub fn start_remote(pid: u32, output_path: PathBuf) -> Result<Self, CaptureError>;

    /// Start capturing local microphone audio.
    pub fn start_local(output_path: PathBuf) -> Result<Self, CaptureError>;

    /// Stop capture, finalize WAV header, close file.
    pub fn stop(&mut self) -> Result<(), CaptureError>;
}
```

Both capture streams run on dedicated `std::thread` threads (not async — WASAPI is blocking/event-driven). They receive stop signals via `Arc<AtomicBool>`.

**WAV writing:** Use a minimal WAV writer (write 44-byte header with placeholder size, stream PCM data, seek back to update header on finalize). No external crate needed.

**Error handling:**
- If remote capture fails to attach → return `CaptureError::RemoteAttachFailed`
- If local capture fails (no mic) → return `CaptureError::NoMicrophoneDevice` (caller decides to continue without)
- If device changes mid-capture → log, re-attach, continue seamlessly

**Step 2: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 3: Commit**

```bash
git add src-tauri/src/recorder/capture.rs src-tauri/src/recorder/mod.rs
git commit -m "feat: add dual WASAPI audio capture (remote loopback + local mic)"
```

---

## Task 5: Video Capture (capture.rs — video portion)

**Files:**
- Modify: `src-tauri/src/recorder/capture.rs`

**Step 1: Add video capture to capture.rs**

Extend `capture.rs` with window video capture using the Windows Graphics Capture API:

**Finding the Zoom window:**
- `EnumWindows` to find windows belonging to the target PID
- Filter by window class (`ZPContentViewWndClass` for Zoom meeting view) or pick the largest visible window
- Works even when Zoom is on a different virtual desktop or behind other windows

**Capture mechanism:**
- `GraphicsCaptureItem::CreateFromVisual` or `CreateForWindow` (via interop)
- Create a `Direct3D11CaptureFramePool` with `PixelFormat::B8G8R8A8UIntNormalized`
- Subscribe to `FrameArrived` event at 30fps
- Each frame: acquire ID3D11Texture2D → map → read pixels → encode to H.265

**Encoding:**
- Use ffmpeg as a subprocess for encoding: pipe raw BGRA frames via stdin to `ffmpeg -f rawvideo -pix_fmt bgra -s WxH -r 30 -i pipe:0 -c:v hevc_nvenc -preset p4 -cq 28 output.mp4`
- This offloads encoding to NVENC and avoids needing to link against codec libraries in Rust
- If NVENC is unavailable (no NVIDIA GPU), fall back to `-c:v libx265 -crf 28 -preset fast`

**Interface:**

```rust
pub struct VideoCapture {
    // Internal handles
}

impl VideoCapture {
    /// Start capturing the window belonging to the given PID at 30fps.
    pub fn start(pid: u32, output_path: PathBuf) -> Result<Self, CaptureError>;

    /// Stop capture, close ffmpeg stdin, wait for encoding to finish.
    pub fn stop(&mut self) -> Result<(), CaptureError>;

    /// Check if NVENC is available on this system.
    pub fn nvenc_available() -> bool;
}
```

**Step 2: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 3: Commit**

```bash
git add src-tauri/src/recorder/capture.rs
git commit -m "feat: add 30fps window video capture via Graphics Capture API + NVENC"
```

---

## Task 6: Zoom API Client (zoom.rs)

**Files:**
- Create: `src-tauri/src/recorder/zoom.rs`
- Modify: `src-tauri/src/recorder/mod.rs`

**Step 1: Implement the Zoom REST API client**

Create `src-tauri/src/recorder/zoom.rs`. This module fetches meeting metadata after a meeting ends.

**API calls:**

| Endpoint | Purpose |
|---|---|
| `GET /v2/users/me` | Get user's display name and email (for speaker pre-labeling) |
| `GET /v2/users/me/meetings?type=previous_meetings` | Find the most recent completed meeting |
| `GET /v2/past_meetings/{meetingId}/participants` | Get actual attendees with join/leave times |

**Meeting matching:** Get recent completed meetings, filter to those ending within 5 minutes of recording stop time. If exactly one → use it. Multiple → closest end time. Zero → fallback to minimal metadata.

**Token management:**
- Accept `access_token` and `refresh_token` as parameters
- On 401 response, call `oauth::refresh_token` and retry once
- Return the refreshed tokens alongside the result so the caller can persist them

**Interface:**

```rust
pub struct ZoomClient {
    access_token: String,
    client_id: String,
    client_secret: String,
}

pub struct ZoomMeetingInfo {
    pub title: String,
    pub participants: Vec<ZoomParticipant>,
    pub user_email: String,
    pub user_name: String,
}

pub struct ZoomParticipant {
    pub name: String,
    pub email: Option<String>,
    pub join_time: String,
    pub leave_time: String,
}

impl ZoomClient {
    pub async fn fetch_recent_meeting(
        &self,
        ended_around: chrono::DateTime<chrono::Utc>,
    ) -> Result<Option<ZoomMeetingInfo>, ZoomError>;
}
```

**Fallback:** All errors produce `ZoomError` variants but are non-fatal. The caller catches and falls back to minimal metadata:
```json
{
    "title": "Zoom Meeting",
    "date": "2026-03-17",
    "participants": [],
    "platform": "zoom"
}
```

**Note on free accounts:** Some endpoints may return 403 on Zoom free plans. Treat this the same as any API error — fall back to minimal metadata.

**Step 2: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 3: Commit**

```bash
git add src-tauri/src/recorder/zoom.rs src-tauri/src/recorder/mod.rs
git commit -m "feat: add Zoom REST API client for post-meeting metadata enrichment"
```

---

## Task 7: Recorder Orchestrator (recorder.rs)

**Files:**
- Create: `src-tauri/src/recorder/recorder.rs`
- Modify: `src-tauri/src/recorder/mod.rs`
- Modify: `src-tauri/src/lib.rs`

**Step 1: Implement the orchestrator**

Create `src-tauri/src/recorder/recorder.rs`. This is the central coordinator that ties monitor, capture, zoom, and sidecar together.

**Responsibilities:**
1. Owns the lifecycle state machine (`RecorderState`)
2. Receives events from `monitor.rs` via channel
3. Shows/handles Windows toast notifications via `tauri-plugin-notification`
4. Starts/stops audio + video capture
5. Triggers ffmpeg merge after capture ends
6. Calls `zoom.rs` for metadata
7. Writes `meeting.json` and `status.json`
8. Invokes the sidecar with appropriate `--from` flag if restarting
9. Shows completion/error notification with context

**Notification flow:**
- Meeting detected → check `detection_action` setting
- If `Ask`: show toast with "Record" / "Skip" action buttons, start timeout timer
- If `AlwaysRecord`: skip notification, start recording immediately
- If `NeverRecord`: enter Declined state (user can still manually start from tray)
- On timeout: check `timeout_action` setting

**Post-meeting processing sequence:**
1. Stop all capture streams
2. Spawn ffmpeg merge: `ffmpeg -i video.mp4 -i remote.wav -i local.wav -filter_complex "[1:a][2:a]amerge=inputs=2[a]" -map 0:v -map "[a]" -c:v copy -c:a aac recording.mp4`
3. Delete temp files (WAVs + raw video) only after successful merge
4. Query Zoom API for metadata (async, don't block on failure)
5. Write `meeting.json` to working directory
6. Move `recording.mp4` to `recordings_path`
7. Write initial `status.json` with all stages pending
8. Invoke sidecar: `recap-pipeline process <recording.mp4> <meeting.json>`
9. On success → notification: "Meeting note ready — click to open" (opens Obsidian via `obsidian://open?vault=...&file=...`)
10. On failure → notification with specific error context (e.g., "Transcription failed — out of memory") and a "Retry" action

**Manual start flow (auto-detect off):**
When user clicks "Start Recording" from tray:
1. Scan for known meeting processes with active audio sessions
2. If exactly one found → target it automatically
3. If multiple found → show picker notification: "What are you recording?" with detected options
4. If none found → offer "System audio" or "Mic only" fallback
5. Proceed with capture targeting the selected process

**Concurrency:** Only one recording session at a time. If a new meeting is detected while processing the previous one, queue the detection notification until processing completes.

**Stop recording:** When "Stop Recording" is clicked from tray menu:
- Stop all capture immediately
- Delete temp files (no merge, no pipeline)
- Return to Idle state

**Interface (IPC commands):**

```rust
#[tauri::command]
pub async fn get_recorder_state(state: State<'_, RecorderHandle>) -> Result<RecorderState, String>;

#[tauri::command]
pub async fn start_recording(state: State<'_, RecorderHandle>) -> Result<(), String>;

#[tauri::command]
pub async fn stop_recording(state: State<'_, RecorderHandle>) -> Result<(), String>;

#[tauri::command]
pub async fn retry_processing(
    state: State<'_, RecorderHandle>,
    recording_dir: String,
    from_stage: Option<String>,
) -> Result<(), String>;
```

**Step 2: Wire into lib.rs**

- Add `RecorderHandle` as Tauri managed state (`.manage(recorder_handle)`)
- Register IPC commands in `invoke_handler`
- Start the monitor in `.setup()` if `auto_detect` is enabled

**Step 3: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 4: Commit**

```bash
git add src-tauri/src/recorder/recorder.rs src-tauri/src/recorder/mod.rs src-tauri/src/lib.rs
git commit -m "feat: add recorder orchestrator with notification flow and lifecycle management"
```

---

## Task 8: Tray Menu Integration

**Files:**
- Modify: `src-tauri/src/tray.rs`

**Step 1: Wire tray menu items to recorder**

Update `tray.rs` to:
1. Enable/disable "Start Recording" and "Stop Recording" based on `RecorderState`
2. Handle "Start Recording" click → call `recorder.start_recording()`
3. Handle "Stop Recording" click → call `recorder.stop_recording()`
4. Update tray icon to show recording state (red dot overlay when recording)
5. Add the `start_recording` and `stop_recording` match arms to `on_menu_event`

The tray should dynamically update menu item enabled states when recorder state changes. Use Tauri's event system: recorder emits `recorder-state-changed` events, and the tray listens.

**Step 2: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 3: Commit**

```bash
git add src-tauri/src/tray.rs
git commit -m "feat: wire tray menu to recorder start/stop with dynamic state"
```

---

## Task 9: Pipeline Stage Restart Support (Python)

**Files:**
- Modify: `recap/cli.py`
- Modify: `recap/pipeline.py`
- Modify: `recap/config.py`

**Step 1: Add `--from` and `--only` CLI arguments**

In `recap/cli.py`, add to the `process` subparser:

```python
process_parser.add_argument(
    "--from", dest="from_stage",
    choices=["merge", "frames", "transcribe", "diarize", "analyze", "export"],
    help="Restart from this stage (skip earlier completed stages)",
)
process_parser.add_argument(
    "--only",
    choices=["merge", "frames", "transcribe", "diarize", "analyze", "export"],
    help="Re-run only this single stage",
)
```

**Step 2: Add status.json reading/writing to pipeline.py**

Add helper functions to `recap/pipeline.py`:

```python
def _load_status(working_dir: pathlib.Path) -> dict:
    """Load status.json from working dir, or return default."""
    status_path = working_dir / "status.json"
    if status_path.exists():
        return json.loads(status_path.read_text())
    return {
        stage: {"completed": False, "timestamp": None, "error": None}
        for stage in ["merge", "frames", "transcribe", "diarize", "analyze", "export"]
    }

def _save_status(working_dir: pathlib.Path, status: dict) -> None:
    """Write status.json to working dir."""
    (working_dir / "status.json").write_text(json.dumps(status, indent=2))

def _mark_stage(status: dict, stage: str, completed: bool, error: str | None = None) -> None:
    """Update a stage's status."""
    from datetime import datetime
    status[stage] = {
        "completed": completed,
        "timestamp": datetime.now().isoformat() if completed else None,
        "error": error,
    }
```

**Step 3: Refactor `run_pipeline` to support stage skipping**

Modify `run_pipeline` to accept optional `from_stage` and `only_stage` parameters. Each stage checks whether it should run:

```python
def _should_run(stage: str, status: dict, from_stage: str | None, only_stage: str | None) -> bool:
    stages = ["merge", "frames", "transcribe", "diarize", "analyze", "export"]
    if only_stage:
        return stage == only_stage
    if from_stage:
        return stages.index(stage) >= stages.index(from_stage)
    return not status[stage]["completed"]
```

Wrap each pipeline stage in a try/except that updates `status.json` on success or failure with a descriptive error message.

**Step 4: Update sidecar.rs to pass `--from` flag**

In `src-tauri/src/sidecar.rs`, modify `run_pipeline` to accept an optional `from_stage` parameter and pass it as `--from <stage>` to the sidecar CLI.

**Step 5: Verify Python CLI**

Run: `python -m recap process --help`
Expected: Shows `--from` and `--only` options

**Step 6: Commit**

```bash
git add recap/cli.py recap/pipeline.py src-tauri/src/sidecar.rs
git commit -m "feat: add pipeline stage restart with --from and --only flags"
```

---

## Task 10: Settings UI — Recording Behavior

**Files:**
- Create: `src/lib/components/RecordingBehaviorSettings.svelte`
- Modify: `src/lib/stores/settings.ts`
- Modify: `src/routes/Settings.svelte`

**Step 1: Add new settings to the store**

In `src/lib/stores/settings.ts`, extend `AppSettings` interface and defaults:

```typescript
// Add to AppSettings interface:
autoDetectMeetings: boolean;
detectionAction: "ask" | "always_record" | "never_record";
timeoutAction: "record" | "skip";
notificationTimeoutSeconds: number;

// Add to defaults:
autoDetectMeetings: true,
detectionAction: "ask",
timeoutAction: "record",
notificationTimeoutSeconds: 60,
```

**Step 2: Create RecordingBehaviorSettings.svelte**

Create `src/lib/components/RecordingBehaviorSettings.svelte`:

```svelte
<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
</script>

<div class="space-y-4">
  <!-- Auto-detect toggle -->
  <label class="flex items-center justify-between">
    <span class="text-sm text-gray-600">Auto-detect Zoom meetings</span>
    <input
      type="checkbox"
      checked={$settings.autoDetectMeetings}
      onchange={(e) => saveSetting("autoDetectMeetings", e.currentTarget.checked)}
      class="rounded"
    />
  </label>

  <!-- Detection action dropdown -->
  <label class="block">
    <span class="block text-sm text-gray-600 mb-1">When meeting detected</span>
    <select
      value={$settings.detectionAction}
      onchange={(e) => saveSetting("detectionAction", e.currentTarget.value)}
      class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
    >
      <option value="ask">Ask me</option>
      <option value="always_record">Always record</option>
      <option value="never_record">Never record</option>
    </select>
  </label>

  <!-- Conditional: timeout settings (only when "ask") -->
  {#if $settings.detectionAction === "ask"}
    <label class="block">
      <span class="block text-sm text-gray-600 mb-1">When notification times out</span>
      <select
        value={$settings.timeoutAction}
        onchange={(e) => saveSetting("timeoutAction", e.currentTarget.value)}
        class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
      >
        <option value="record">Start recording</option>
        <option value="skip">Skip recording</option>
      </select>
    </label>

    <label class="block">
      <span class="block text-sm text-gray-600 mb-1">Notification timeout (seconds)</span>
      <input
        type="number"
        min="10"
        max="300"
        value={$settings.notificationTimeoutSeconds}
        onblur={(e) => saveSetting("notificationTimeoutSeconds", parseInt(e.currentTarget.value))}
        class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
      />
    </label>
  {/if}
</div>
```

**Step 3: Add to Settings.svelte**

In `src/routes/Settings.svelte`, import and add `RecordingBehaviorSettings` inside the existing Recording `SettingsSection` (around line 35-37), below the existing `RecordingSettings`:

```svelte
<SettingsSection title="Recording">
  <RecordingSettings />
  <div class="mt-4 pt-4 border-t border-gray-200">
    <RecordingBehaviorSettings />
  </div>
</SettingsSection>
```

**Step 4: Verify dev build**

Run: `npm run dev` (Tauri dev mode)
Expected: Settings page shows new recording behavior controls

**Step 5: Commit**

```bash
git add src/lib/components/RecordingBehaviorSettings.svelte src/lib/stores/settings.ts src/routes/Settings.svelte
git commit -m "feat: add recording behavior settings UI (auto-detect, timeout, action)"
```

---

## Task 11: About Section — NVENC and ffmpeg Status

**Files:**
- Modify: `src/lib/components/AboutSection.svelte`
- Modify: `src/lib/tauri.ts`
- Create: `src-tauri/src/diagnostics.rs`
- Modify: `src-tauri/src/lib.rs`

**Step 1: Create diagnostics IPC commands**

Create `src-tauri/src/diagnostics.rs`:

```rust
use std::process::Command;

#[tauri::command]
pub async fn check_nvenc() -> Result<String, String> {
    // Run: ffmpeg -hide_banner -encoders 2>&1 | findstr hevc_nvenc
    let output = Command::new("ffmpeg")
        .args(["-hide_banner", "-encoders"])
        .output()
        .map_err(|_| "ffmpeg not found".to_string())?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    if stdout.contains("hevc_nvenc") {
        Ok("Available".to_string())
    } else {
        Ok("Not available — software encoding will be used".to_string())
    }
}

#[tauri::command]
pub async fn check_ffmpeg() -> Result<bool, String> {
    match Command::new("ffmpeg").arg("-version").output() {
        Ok(output) => Ok(output.status.success()),
        Err(_) => Ok(false),
    }
}
```

**Step 2: Register commands in lib.rs**

Add `mod diagnostics;` and register `diagnostics::check_nvenc` and `diagnostics::check_ffmpeg` in the `invoke_handler`.

**Step 3: Add typed wrappers in tauri.ts**

```typescript
export async function checkNvenc(): Promise<string> {
  return invoke("check_nvenc");
}

export async function checkFfmpeg(): Promise<boolean> {
  return invoke("check_ffmpeg");
}
```

**Step 4: Update AboutSection.svelte**

Add NVENC and ffmpeg status rows below the existing sidecar status, using the same pattern (check on mount, display result).

**Step 5: Verify dev build**

Run: `npm run dev`
Expected: About section shows NVENC and ffmpeg status

**Step 6: Commit**

```bash
git add src-tauri/src/diagnostics.rs src-tauri/src/lib.rs src/lib/tauri.ts src/lib/components/AboutSection.svelte
git commit -m "feat: add NVENC and ffmpeg diagnostics to About section"
```

---

## Task 12: Update sidecar.rs for Phase 4

**Files:**
- Modify: `src-tauri/src/sidecar.rs`

**Step 1: Extend `run_pipeline` to support metadata and stage restart**

Update the `run_pipeline` command signature and implementation:

```rust
#[tauri::command]
pub async fn run_pipeline(
    app: tauri::AppHandle,
    recording_path: String,
    metadata_path: String,
    config_path: String,
    from_stage: Option<String>,
) -> Result<SidecarResult, String> {
    let mut args = vec![
        "process".to_string(),
        recording_path,
        metadata_path,
        "--config".to_string(),
        config_path,
    ];

    if let Some(stage) = from_stage {
        args.push("--from".to_string());
        args.push(stage);
    }

    let sidecar = app
        .shell()
        .sidecar("recap-pipeline")
        .map_err(|e| format!("Failed to create sidecar command: {}", e))?
        .args(&args);

    let output = sidecar
        .output()
        .await
        .map_err(|e| format!("Sidecar execution failed: {}", e))?;

    Ok(SidecarResult {
        success: output.status.success(),
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
    })
}
```

**Step 2: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 3: Commit**

```bash
git add src-tauri/src/sidecar.rs
git commit -m "feat: update sidecar invocation to support metadata path and --from stage restart"
```

---

## Task 13: Integration Testing — Manual Walkthrough

**Files:**
- No new files — manual testing

**Step 1: Build the full app**

Run: `npm run tauri dev`

**Step 2: Verify Settings UI**

- Navigate to Settings
- Confirm Recording section shows new behavior controls
- Toggle auto-detect, change detection action, verify conditional fields appear/hide
- Check About section shows NVENC and ffmpeg status

**Step 3: Verify tray menu state**

- With no meeting: "Start Recording" should be disabled (no target process)
- Launch a Zoom test meeting
- Verify notification appears (or auto-records based on setting)
- If recording: "Stop Recording" should be enabled, "Start Recording" disabled
- Click "Stop Recording" → verify cleanup

**Step 4: Verify capture output**

- After a short test recording, check the working directory for:
  - `*-remote.wav` (Zoom audio)
  - `*-local.wav` (mic audio)
  - `*-video.mp4` (window capture)
- After merge: single `*-recording.mp4` with both audio tracks and video

**Step 5: Verify pipeline restart**

- Manually corrupt or delete `transcript.json` in a recording directory
- Run: `recap-pipeline process <recording.mp4> <meeting.json> --from transcribe`
- Verify it skips merge and frames, runs transcription onwards
- Check `status.json` is updated correctly

**Step 6: Commit any fixes from testing**

```bash
git add -A
git commit -m "fix: address issues found during Phase 4 integration testing"
```

---

## Task 14: Update MANIFEST.md

**Files:**
- Modify: `MANIFEST.md`

**Step 1: Regenerate MANIFEST.md**

Update the structural map to reflect all new files:

**New entries in Structure:**

```
src-tauri/src/
├── recorder/
│   ├── mod.rs              # Recorder module root — re-exports submodules
│   ├── types.rs            # State machine types, pipeline stages, recording config
│   ├── monitor.rs          # WASAPI audio session monitor — detects Zoom/Teams processes
│   ├── capture.rs          # Dual audio (WASAPI loopback + mic) + video (Graphics Capture) capture
│   ├── zoom.rs             # Zoom REST API client — post-meeting metadata enrichment
│   └── recorder.rs         # Orchestrator — lifecycle state machine, notifications, merge, sidecar
├── diagnostics.rs          # NVENC/ffmpeg availability checks for Settings UI
```

**New entries in Key Relationships:**

- `recorder.rs` orchestrates `monitor.rs` → `capture.rs` → ffmpeg merge → `zoom.rs` → `sidecar.rs`
- `monitor.rs` detects audio sessions → sends events to `recorder.rs` via mpsc channel
- `capture.rs` writes three temp files → `recorder.rs` merges via ffmpeg → single MP4 to pipeline
- `zoom.rs` uses `oauth.rs::refresh_token` for token refresh on 401
- `tray.rs` listens for `recorder-state-changed` events to update menu item enabled states
- Pipeline `status.json` enables `--from` restart: `recorder.rs` reads it for retry notifications

**Step 2: Commit**

```bash
git add MANIFEST.md
git commit -m "docs: update MANIFEST.md with Phase 4 recorder modules"
```

---

## Key Design Decisions Reference

These decisions were made during brainstorming and should not be revisited during implementation:

1. **No meeting bots** — we use local WASAPI capture, not cloud meeting bots. This avoids hosting costs, latency, and per-platform bot development. Trade-off: requires the desktop app to be running during meetings.

2. **Dual WASAPI streams** — remote audio via per-process loopback, local audio via default mic capture. Separate channels improve diarization accuracy.

3. **H.265 NVENC encoding** — lighter than H.264 at equivalent quality. Falls back to software `libx265` if no NVIDIA GPU.

4. **30fps full video** — not periodic screenshots. Enables scene detection in `frames.py` and full meeting replay.

5. **ffmpeg as subprocess** — for both video encoding (piped frames during capture) and post-capture merge. Avoids linking codec libraries into the Rust binary.

6. **Pipeline stage restart** — `status.json` tracks completion per stage. `--from` flag skips completed stages. Recordings and intermediates are preserved on failure.

7. **Zoom API is soft dependency** — capture + pipeline works without it. API provides enrichment (meeting title, real participant names) but falls back to minimal metadata.

8. **Auto-record as default** — both "notification timeout" and "always record" default to recording. Better to have an unwanted recording than to miss an important one.

9. **Manual start scans for processes** — when auto-detect is off and user clicks "Start Recording", monitor scans for known meeting processes. Single match → auto-target. Multiple → show picker. None → offer system audio fallback.

10. **Device switching handled** — mic capture re-attaches on default device change via `IMMNotificationClient`.

11. **HDD warning deferred** — storage path picker should warn on HDD selection. Implementation deferred (see memory note `project_hdd_warning.md`).
