# Phase 6: Recording Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand recording to all meeting platforms (Google Meet, Teams, Zoho Meet) via a browser extension + multi-platform detection, add per-platform API enrichment with screenshot-based fallback, screen share capture switching, and auto-record from calendar events.

**Architecture:** A lightweight Manifest V3 Chrome/Edge extension detects browser-based meetings and signals Recap via localhost HTTP. The Rust recorder gains platform-aware detection (WASAPI + extension), screen share source switching, and post-recording enrichment routing to platform-specific API clients. Calendar events can arm the recorder for automatic recording. Screenshot-based participant extraction via Claude vision serves as universal fallback.

**Tech Stack:** Svelte 5, Tauri v2 (Rust), Chrome Extension (Manifest V3), Python 3.10+, Claude CLI (vision), Google Meet API, Zoho Meeting API, Microsoft Graph API (limited)

**Testing:** Python: pytest. Frontend: manual/visual. Rust: compile + manual IPC testing. Extension: manual load + test.

---

## Group 1: Browser Extension

### Task 1: Extension Manifest and Background Service Worker

**Files:**
- Create: `extension/manifest.json`
- Create: `extension/background.js`
- Create: `extension/icons/icon-16.png` (placeholder)
- Create: `extension/icons/icon-48.png` (placeholder)
- Create: `extension/icons/icon-128.png` (placeholder)

**Step 1: Create extension directory**

Run: `mkdir -p extension/icons`

**Step 2: Write manifest.json**

```json
{
  "manifest_version": 3,
  "name": "Recap Meeting Detector",
  "version": "1.0.0",
  "description": "Detects browser-based meetings and notifies Recap for recording",
  "permissions": ["tabs", "storage"],
  "host_permissions": ["http://localhost/*"],
  "background": {
    "service_worker": "background.js"
  },
  "content_scripts": [
    {
      "matches": [
        "https://meet.google.com/*",
        "https://teams.microsoft.com/*",
        "https://meeting.zoho.com/*",
        "https://meeting.zoho.eu/*",
        "https://meeting.zoho.in/*",
        "https://meeting.zoho.com.au/*",
        "https://meeting.tranzpay.io/*"
      ],
      "js": ["content.js"],
      "run_at": "document_idle"
    }
  ],
  "options_page": "options.html",
  "icons": {
    "16": "icons/icon-16.png",
    "48": "icons/icon-48.png",
    "128": "icons/icon-128.png"
  },
  "action": {
    "default_icon": {
      "16": "icons/icon-16.png",
      "48": "icons/icon-48.png"
    },
    "default_title": "Recap — Not connected"
  }
}
```

**Step 3: Write background.js**

```javascript
const RECAP_PORT_START = 17839;
const RECAP_PORT_END = 17845;
const HEALTH_CHECK_INTERVAL_MS = 30000;

const DEFAULT_MEETING_PATTERNS = [
  { pattern: "meet.google.com/", platform: "google_meet", excludeExact: "meet.google.com/" },
  { pattern: "teams.microsoft.com/", platform: "teams", requirePath: ["meetup-join", "pre-join"] },
  { pattern: "meeting.zoho.com/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.eu/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.in/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.com.au/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.tranzpay.io/", platform: "zoho_meet" },
];

let recapPort = null;
let activeMeetingTabs = new Map();

async function findRecapPort() {
  for (let port = RECAP_PORT_START; port <= RECAP_PORT_END; port++) {
    try {
      const resp = await fetch(`http://localhost:${port}/health`, {
        signal: AbortSignal.timeout(1000),
      });
      if (resp.ok) {
        recapPort = port;
        chrome.action.setBadgeBackgroundColor({ color: "#4baa55" });
        chrome.action.setBadgeText({ text: "ON" });
        chrome.action.setTitle({ title: "Recap — Connected" });
        return port;
      }
    } catch (_) {}
  }
  recapPort = null;
  chrome.action.setBadgeBackgroundColor({ color: "#7a8493" });
  chrome.action.setBadgeText({ text: "" });
  chrome.action.setTitle({ title: "Recap — Not connected" });
  return null;
}

async function getMeetingPatterns() {
  const result = await chrome.storage.local.get("meetingPatterns");
  return result.meetingPatterns || DEFAULT_MEETING_PATTERNS;
}

function matchesMeetingUrl(url, patterns) {
  try {
    const parsed = new URL(url);
    const fullUrl = parsed.hostname + parsed.pathname;
    for (const rule of patterns) {
      if (!fullUrl.includes(rule.pattern)) continue;
      if (rule.excludeExact && fullUrl === rule.excludeExact) continue;
      if (rule.requirePath && !rule.requirePath.some((p) => parsed.pathname.includes(p))) continue;
      return rule.platform;
    }
  } catch (_) {}
  return null;
}

async function notifyRecap(endpoint, data) {
  if (!recapPort) await findRecapPort();
  if (!recapPort) return;
  try {
    await fetch(`http://localhost:${recapPort}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  } catch (_) {
    recapPort = null;
  }
}

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url) return;
  const patterns = await getMeetingPatterns();
  const platform = matchesMeetingUrl(tab.url, patterns);
  if (platform && !activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.set(tabId, { url: tab.url, title: tab.title, platform });
    await notifyRecap("/meeting-detected", {
      url: tab.url,
      title: tab.title || "Meeting",
      platform,
      tabId,
    });
  } else if (!platform && activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.delete(tabId);
    await notifyRecap("/meeting-ended", { tabId });
  }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  if (activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.delete(tabId);
    await notifyRecap("/meeting-ended", { tabId });
  }
});

setInterval(findRecapPort, HEALTH_CHECK_INTERVAL_MS);
findRecapPort();
```

**Step 4: Create placeholder icons**

Use the existing `static/icon-source.svg` as reference. For now, create minimal 16x16, 48x48, 128x128 PNGs (can be solid colored squares — will be replaced with proper icons later).

**Step 5: Verify extension loads**

Manual: Open `chrome://extensions`, enable Developer mode, click "Load unpacked", select `extension/` folder. Verify no errors in the extension's service worker console.

**Step 6: Commit**

```bash
git add extension/
git commit -m "feat: add Chrome/Edge meeting detector extension with URL matching"
```

---

### Task 2: Content Script for Screen Share Detection

**Files:**
- Create: `extension/content.js`

**Step 1: Write content.js**

```javascript
// Screen share detection for meeting pages.
// Injected into meeting domains via manifest content_scripts.
// Watches for platform-specific DOM indicators of "you are sharing".

const RECAP_PORT_START = 17839;
const RECAP_PORT_END = 17845;

let sharing = false;
let recapPort = null;

async function findPort() {
  for (let port = RECAP_PORT_START; port <= RECAP_PORT_END; port++) {
    try {
      const resp = await fetch(`http://localhost:${port}/health`, {
        signal: AbortSignal.timeout(1000),
      });
      if (resp.ok) return (recapPort = port);
    } catch (_) {}
  }
  return null;
}

async function notifySharing(started) {
  if (!recapPort) await findPort();
  if (!recapPort) return;
  const endpoint = started ? "/sharing-started" : "/sharing-stopped";
  try {
    await fetch(`http://localhost:${recapPort}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tabId: null }),
    });
  } catch (_) {
    recapPort = null;
  }
}

function detectPlatform() {
  const host = window.location.hostname;
  if (host === "meet.google.com") return "google_meet";
  if (host.includes("teams.microsoft.com")) return "teams";
  if (host.includes("meeting.zoho") || host.includes("meeting.tranzpay.io"))
    return "zoho_meet";
  return null;
}

// Selectors that appear when the user is sharing their screen.
// These are fragile and may need updating when platforms change their UI.
const SHARE_SELECTORS = {
  google_meet: [
    '[data-self-name="You are presenting"]',
    '[aria-label*="presenting"]',
    '[data-is-presenting="true"]',
  ],
  teams: [
    '[data-tid="sharing-indicator"]',
    '.ts-sharing-screen-banner',
    '[aria-label*="sharing"]',
  ],
  zoho_meet: [
    '.screen-share-indicator',
    '[class*="sharing-banner"]',
    '[class*="screen-share-active"]',
  ],
};

function checkSharing(platform) {
  const selectors = SHARE_SELECTORS[platform] || [];
  return selectors.some((sel) => document.querySelector(sel) !== null);
}

const platform = detectPlatform();
if (platform) {
  const observer = new MutationObserver(() => {
    const nowSharing = checkSharing(platform);
    if (nowSharing !== sharing) {
      sharing = nowSharing;
      notifySharing(sharing);
    }
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class", "aria-label", "data-self-name", "data-is-presenting"],
  });

  findPort();
  setTimeout(() => {
    const nowSharing = checkSharing(platform);
    if (nowSharing !== sharing) {
      sharing = nowSharing;
      notifySharing(sharing);
    }
  }, 3000);
}
```

**Step 2: Verify content script loads**

Manual: Reload the extension in `chrome://extensions`. Open a Google Meet URL (or `meeting.tranzpay.io`). Check the page's DevTools console for no errors from the content script.

**Step 3: Commit**

```bash
git add extension/content.js
git commit -m "feat: add content script for screen share detection on meeting pages"
```

---

### Task 3: Extension Options Page

**Files:**
- Create: `extension/options.html`
- Create: `extension/options.js`

**Step 1: Write options.html**

A minimal settings page for managing meeting URL patterns. Uses Recap Dark palette. Pattern rows are built via DOM API methods in options.js (no raw HTML injection).

**Step 2: Write options.js**

```javascript
const DEFAULT_PATTERNS = [
  { pattern: "meet.google.com/", platform: "google_meet" },
  { pattern: "teams.microsoft.com/", platform: "teams", requirePath: ["meetup-join", "pre-join"] },
  { pattern: "meeting.zoho.com/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.eu/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.in/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.com.au/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.tranzpay.io/", platform: "zoho_meet" },
];

const PLATFORMS = ["google_meet", "teams", "zoho_meet", "unknown"];
const container = document.getElementById("patterns");

function createPatternRow(pattern, index) {
  const row = document.createElement("div");
  row.className = "pattern-row";

  const input = document.createElement("input");
  input.type = "text";
  input.value = pattern.pattern;
  input.dataset.index = index;
  input.className = "pattern-input";

  const select = document.createElement("select");
  select.dataset.index = index;
  select.className = "platform-select";
  for (const pl of PLATFORMS) {
    const option = document.createElement("option");
    option.value = pl;
    option.textContent = pl;
    if (pattern.platform === pl) option.selected = true;
    select.appendChild(option);
  }

  const removeBtn = document.createElement("button");
  removeBtn.className = "remove";
  removeBtn.dataset.index = index;
  removeBtn.textContent = "x";

  row.appendChild(input);
  row.appendChild(select);
  row.appendChild(removeBtn);
  return row;
}

function renderPatterns(patterns) {
  container.replaceChildren();
  patterns.forEach((p, i) => container.appendChild(createPatternRow(p, i)));
}

async function load() {
  const result = await chrome.storage.local.get("meetingPatterns");
  renderPatterns(result.meetingPatterns || DEFAULT_PATTERNS);
}

function collectPatterns() {
  const inputs = container.querySelectorAll(".pattern-input");
  const selects = container.querySelectorAll(".platform-select");
  const patterns = [];
  inputs.forEach((input, i) => {
    if (input.value.trim()) {
      patterns.push({ pattern: input.value.trim(), platform: selects[i].value });
    }
  });
  return patterns;
}

document.getElementById("add-btn").addEventListener("click", () => {
  const patterns = collectPatterns();
  patterns.push({ pattern: "", platform: "unknown" });
  renderPatterns(patterns);
});

container.addEventListener("click", (e) => {
  if (e.target.classList.contains("remove")) {
    const patterns = collectPatterns();
    patterns.splice(parseInt(e.target.dataset.index), 1);
    renderPatterns(patterns);
  }
});

document.getElementById("save-btn").addEventListener("click", async () => {
  await chrome.storage.local.set({ meetingPatterns: collectPatterns() });
  const msg = document.getElementById("saved-msg");
  msg.style.display = "inline";
  setTimeout(() => (msg.style.display = "none"), 2000);
});

document.getElementById("reset-btn").addEventListener("click", async () => {
  await chrome.storage.local.set({ meetingPatterns: DEFAULT_PATTERNS });
  renderPatterns(DEFAULT_PATTERNS);
});

load();
```

**Step 3: Verify options page**

Manual: Right-click extension icon, select Options. Verify patterns load, can add/remove, save persists.

**Step 4: Commit**

```bash
git add extension/options.html extension/options.js
git commit -m "feat: add extension options page for custom meeting URL patterns"
```

---

## Group 2: Localhost HTTP Listener

### Task 4: Rust HTTP Listener Module

**Files:**
- Create: `src-tauri/src/recorder/listener.rs`
- Modify: `src-tauri/src/recorder/mod.rs`
- Modify: `src-tauri/Cargo.toml`

**Step 1: Add axum dependency**

Add to `[dependencies]` in `src-tauri/Cargo.toml`:

```toml
axum = "0.8"
```

**Step 2: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS with new dep resolved

**Step 3: Write listener.rs**

Create `src-tauri/src/recorder/listener.rs`:

```rust
use axum::{
    extract::State,
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::sync::mpsc;

use super::monitor::MonitorEvent;
use super::types::MeetingPlatform;

#[derive(Debug, Deserialize)]
pub struct MeetingDetectedPayload {
    pub url: String,
    pub title: String,
    pub platform: String,
    pub tab_id: Option<u32>,
}

#[derive(Debug, Deserialize)]
pub struct MeetingEndedPayload {
    pub tab_id: Option<u32>,
}

#[derive(Debug, Deserialize)]
pub struct SharingPayload {
    pub tab_id: Option<u32>,
}

struct ListenerState {
    tx: mpsc::Sender<MonitorEvent>,
}

/// Start the localhost HTTP listener for browser extension communication.
/// Tries ports 17839-17845. Returns the port that was bound.
pub async fn start_listener(tx: mpsc::Sender<MonitorEvent>) -> Result<u16, String> {
    let state = Arc::new(ListenerState { tx });

    let app = Router::new()
        .route("/health", get(health))
        .route("/meeting-detected", post(meeting_detected))
        .route("/meeting-ended", post(meeting_ended))
        .route("/sharing-started", post(sharing_started))
        .route("/sharing-stopped", post(sharing_stopped))
        .with_state(state);

    for port in 17839..=17845 {
        let addr = SocketAddr::from(([127, 0, 0, 1], port));
        match tokio::net::TcpListener::bind(addr).await {
            Ok(tcp_listener) => {
                log::info!("Recap listener started on port {}", port);
                tokio::spawn(async move {
                    axum::serve(tcp_listener, app)
                        .await
                        .unwrap_or_else(|e| log::error!("Listener error: {}", e));
                });
                return Ok(port);
            }
            Err(_) => continue,
        }
    }

    Err("Could not bind to any port in range 17839-17845".to_string())
}

async fn health() -> impl IntoResponse {
    StatusCode::OK
}

async fn meeting_detected(
    State(state): State<Arc<ListenerState>>,
    Json(payload): Json<MeetingDetectedPayload>,
) -> impl IntoResponse {
    let platform = MeetingPlatform::from_str(&payload.platform);
    let _ = state.tx.send(MonitorEvent::BrowserMeetingDetected {
        url: payload.url,
        title: payload.title,
        platform,
        tab_id: payload.tab_id,
    }).await;
    StatusCode::OK
}

async fn meeting_ended(
    State(state): State<Arc<ListenerState>>,
    Json(payload): Json<MeetingEndedPayload>,
) -> impl IntoResponse {
    let _ = state.tx.send(MonitorEvent::BrowserMeetingEnded {
        tab_id: payload.tab_id,
    }).await;
    StatusCode::OK
}

async fn sharing_started(
    State(state): State<Arc<ListenerState>>,
    Json(_payload): Json<SharingPayload>,
) -> impl IntoResponse {
    let _ = state.tx.send(MonitorEvent::SharingStarted).await;
    StatusCode::OK
}

async fn sharing_stopped(
    State(state): State<Arc<ListenerState>>,
    Json(_payload): Json<SharingPayload>,
) -> impl IntoResponse {
    let _ = state.tx.send(MonitorEvent::SharingStopped).await;
    StatusCode::OK
}
```

**Step 4: Update mod.rs**

Add `pub mod listener;` to `src-tauri/src/recorder/mod.rs`.

**Step 5: Verify build**

Run: `cd src-tauri && cargo check`
Expected: FAIL — `MonitorEvent` variants and `MeetingPlatform` don't exist yet. Expected — they're added in Task 5.

**Step 6: Commit**

```bash
git add src-tauri/src/recorder/listener.rs src-tauri/src/recorder/mod.rs src-tauri/Cargo.toml
git commit -m "feat: add localhost HTTP listener for browser extension communication"
```

---

## Group 3: Multi-Platform Detection

### Task 5: MeetingPlatform Enum and Monitor Event Expansion

**Files:**
- Modify: `src-tauri/src/recorder/types.rs`
- Modify: `src-tauri/src/recorder/monitor.rs`

**Step 1: Add MeetingPlatform to types.rs**

Add after the existing `RecorderState` enum:

```rust
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MeetingPlatform {
    Zoom,
    Teams,
    GoogleMeet,
    ZohoMeet,
    Unknown,
}

impl MeetingPlatform {
    pub fn from_str(s: &str) -> Self {
        match s {
            "zoom" => Self::Zoom,
            "teams" => Self::Teams,
            "google_meet" => Self::GoogleMeet,
            "zoho_meet" => Self::ZohoMeet,
            _ => Self::Unknown,
        }
    }

    pub fn from_process(name: &str) -> Self {
        match name {
            "Zoom.exe" => Self::Zoom,
            "Teams.exe" => Self::Teams,
            _ => Self::Unknown,
        }
    }
}
```

Also add `platform: MeetingPlatform` to `RecordingSession`.

**Step 2: Expand MonitorEvent in monitor.rs**

Add new variants:

```rust
pub enum MonitorEvent {
    MeetingDetected { process_name: String, pid: u32 },
    MeetingEnded { pid: u32 },
    BrowserMeetingDetected { url: String, title: String, platform: MeetingPlatform, tab_id: Option<u32> },
    BrowserMeetingEnded { tab_id: Option<u32> },
    SharingStarted,
    SharingStopped,
}
```

**Step 3: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 4: Commit**

```bash
git add src-tauri/src/recorder/types.rs src-tauri/src/recorder/monitor.rs
git commit -m "feat: add MeetingPlatform enum and expand MonitorEvent for browser detection"
```

---

### Task 6: Screen Share Detection for Desktop Apps

**Files:**
- Create: `src-tauri/src/recorder/share_detect.rs`
- Modify: `src-tauri/src/recorder/mod.rs`

**Step 1: Write share_detect.rs**

Monitor for known screen sharing toolbar windows (Zoom's `ZPToolBarParentWndClass`, Teams share toolbar) via Win32 `EnumWindows`. Poll every 1 second. Emit `MonitorEvent::SharingStarted`/`SharingStopped` through the monitor channel.

Provide `start_share_monitor(tx, target_pid) -> (JoinHandle, Arc<AtomicBool>)` matching the existing monitor pattern.

**Step 2: Update mod.rs**

Add `pub mod share_detect;`.

**Step 3: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 4: Commit**

```bash
git add src-tauri/src/recorder/share_detect.rs src-tauri/src/recorder/mod.rs
git commit -m "feat: add Win32 screen share detection for Zoom and Teams desktop"
```

---

### Task 7: Video Capture Source Switching

**Files:**
- Modify: `src-tauri/src/recorder/capture.rs`
- Modify: `src-tauri/src/recorder/types.rs`

**Step 1: Add CaptureSource enum to types.rs**

```rust
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureSource {
    Window { pid: u32 },
    Display { monitor_index: u32 },
}
```

**Step 2: Add switch_source to VideoCapture**

Add a method that stops the current frame pool, creates a new `GraphicsCaptureItem` for the target (window HWND or monitor HMONITOR), and restarts the frame pool. Follow the existing `start()` pattern but with `CreateForMonitor` instead of `CreateForWindow`.

Also add `screen_share_monitor: u32` to `RecordingConfig` (default: 0).

**Step 3: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 4: Commit**

```bash
git add src-tauri/src/recorder/capture.rs src-tauri/src/recorder/types.rs
git commit -m "feat: add video capture source switching between window and display"
```

---

### Task 8: Wire Listener and Share Detection into Recorder

**Files:**
- Modify: `src-tauri/src/recorder/recorder.rs`
- Modify: `src-tauri/src/lib.rs`

**Step 1: Handle new MonitorEvent variants in recorder.rs**

Add match arms for `BrowserMeetingDetected`, `BrowserMeetingEnded`, `SharingStarted`, `SharingStopped`. Browser detection finds the browser PID from WASAPI, then follows the same flow as desktop detection. Sharing events switch the video capture source.

Dedup logic: if already recording, ignore overlapping detection signals.

**Step 2: Start listener in lib.rs setup**

In `.setup()`, spawn the listener with a cloned monitor channel sender.

**Step 3: Start share detection when recording begins**

For Zoom/Teams desktop recordings, start `share_detect::start_share_monitor` alongside capture. Add `share_monitor_handle` and `share_monitor_stop` fields to `RecorderInner`.

**Step 4: Verify build**

Run: `cd src-tauri && cargo check`
Expected: PASS

**Step 5: Commit**

```bash
git add src-tauri/src/recorder/recorder.rs src-tauri/src/lib.rs
git commit -m "feat: wire extension listener and share detection into recorder orchestrator"
```

---

### Task 9: Screen Share Monitor Settings UI

**Files:**
- Create: `src-tauri/src/display.rs`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src/lib/tauri.ts`
- Modify: `src/lib/stores/settings.ts`
- Modify: `src/lib/components/RecordingBehaviorSettings.svelte`

**Step 1: Create display.rs with list_monitors IPC command**

Enumerate monitors via Win32 `EnumDisplayMonitors` + `GetMonitorInfoW`. Return `Vec<MonitorInfo>` with index, name, width, height, is_primary.

**Step 2: Register in lib.rs, add TypeScript wrapper**

Add `MonitorInfo` interface and `listMonitors()` to `tauri.ts`. Add `screenShareMonitor: number` to settings (default: 0).

**Step 3: Add monitor dropdown to RecordingBehaviorSettings**

Load monitors on mount, show select dropdown below existing settings.

**Step 4: Verify build + dev**

Run: `cd src-tauri && cargo check` then `npm run tauri dev`

**Step 5: Commit**

```bash
git add src-tauri/src/display.rs src-tauri/src/lib.rs src/lib/tauri.ts src/lib/stores/settings.ts src/lib/components/RecordingBehaviorSettings.svelte
git commit -m "feat: add screen share monitor selector to recording settings"
```

---

## Group 4: API Metadata Enrichment

### Task 10: Unified MeetingMetadata Model

**Files:**
- Modify: `src-tauri/src/recorder/types.rs`

**Step 1: Add unified metadata types**

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeetingMetadata {
    pub title: String,
    pub platform: MeetingPlatform,
    pub participants: Vec<Participant>,
    pub user_name: String,
    pub user_email: String,
    pub start_time: String,
    pub end_time: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Participant {
    pub name: String,
    pub email: Option<String>,
    pub join_time: Option<String>,
    pub leave_time: Option<String>,
}
```

**Step 2: Verify build, commit**

```bash
git add src-tauri/src/recorder/types.rs
git commit -m "feat: add unified MeetingMetadata model for cross-platform enrichment"
```

---

### Task 11: Refactor Zoom Client to Unified Model

**Files:**
- Modify: `src-tauri/src/recorder/zoom.rs`
- Modify: `src-tauri/src/recorder/recorder.rs`

Replace `ZoomMeetingInfo`/`ZoomParticipant` return types with `MeetingMetadata`/`Participant`. Keep internal deserialization structs for Zoom API responses, map to unified model in the public `fetch_recent_meeting` method.

**Commit:**

```bash
git add src-tauri/src/recorder/zoom.rs src-tauri/src/recorder/recorder.rs
git commit -m "refactor: align Zoom client with unified MeetingMetadata model"
```

---

### Task 12: Google Meet API Client

**Files:**
- Create: `src-tauri/src/recorder/google_meet.rs`
- Modify: `src-tauri/src/recorder/mod.rs`
- Modify: `src-tauri/src/oauth.rs`

**Step 1: Update Google OAuth scope in oauth.rs**

Add `meetings.space.readonly` to Google scopes:

```rust
scopes: "https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/meetings.space.readonly".into(),
```

**Step 2: Write google_meet.rs**

Follow the zoom.rs pattern. Uses Google Meet REST API v2:
- `GET /v2/conferenceRecords?filter=end_time>"..."` — list recent meetings
- `GET /v2/conferenceRecords/{id}/participants` — actual attendees

Client includes token refresh via `oauth::refresh_token`. Maps responses to `MeetingMetadata`.

**Step 3: Verify build, commit**

```bash
git add src-tauri/src/recorder/google_meet.rs src-tauri/src/recorder/mod.rs src-tauri/src/oauth.rs
git commit -m "feat: add Google Meet API client with Workspace admin participant access"
```

---

### Task 13: Zoho Meeting API Client

**Files:**
- Create: `src-tauri/src/recorder/zoho_meet.rs`
- Modify: `src-tauri/src/recorder/mod.rs`

Follow the zoom.rs pattern. Uses Zoho Meeting API:
- `GET /meeting/api/v1/meetings?status=completed` — list meetings
- `GET /meeting/api/v1/meetings/{id}/attendees` — actual attendees

Regional endpoint handling (`.com`, `.eu`, `.in`, `.com.au`) using the user's configured Zoho region. Maps responses to `MeetingMetadata`.

**Commit:**

```bash
git add src-tauri/src/recorder/zoho_meet.rs src-tauri/src/recorder/mod.rs
git commit -m "feat: add Zoho Meeting API client for post-meeting participant enrichment"
```

---

### Task 14: Teams Metadata Fallback

**Files:**
- Create: `src-tauri/src/recorder/teams.rs`
- Modify: `src-tauri/src/recorder/mod.rs`

Teams personal accounts can't access meeting APIs. This module provides `build_teams_metadata(calendar_match, target_pid, start, end) -> MeetingMetadata`:
- Uses calendar event data for title + participants when available
- Falls back to Win32 `GetWindowText` for meeting title
- Returns `MeetingMetadata` with calendar-sourced participants or empty vec

**Commit:**

```bash
git add src-tauri/src/recorder/teams.rs src-tauri/src/recorder/mod.rs
git commit -m "feat: add Teams metadata fallback via calendar events and window title"
```

---

### Task 15: Screenshot-Based Participant Extraction

**Files:**
- Create: `prompts/participant_extraction.md`
- Modify: `recap/pipeline.py`
- Create: `tests/test_participant_extraction.py`

**Step 1: Write prompt template**

Instructs Claude to extract participant names from meeting window screenshots. Returns JSON array.

**Step 2: Write failing tests**

Test `extract_participants_from_screenshots()`: single screenshot, multiple screenshots (union names), empty input, empty response, Claude error.

**Step 3: Run tests to verify failure**

Run: `python -m pytest tests/test_participant_extraction.py -v`
Expected: FAIL

**Step 4: Implement**

Add `extract_participants_from_screenshots(screenshots: list[Path]) -> list[str]` to pipeline.py. Sends each screenshot to Claude CLI with vision prompt, unions results. Non-fatal — returns empty list on any error.

Also add/update `run_claude_cli(prompt, image_paths=None)` helper.

**Step 5: Run tests to verify pass**

Run: `python -m pytest tests/test_participant_extraction.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add prompts/participant_extraction.md recap/pipeline.py tests/test_participant_extraction.py
git commit -m "feat: add screenshot-based participant extraction via Claude vision"
```

---

### Task 16: Enrichment Routing in Recorder

**Files:**
- Modify: `src-tauri/src/recorder/recorder.rs`

Add `enrich_metadata()` function that routes based on `MeetingPlatform`:
1. Zoom -> `zoom.rs`
2. GoogleMeet -> `google_meet.rs`
3. ZohoMeet -> `zoho_meet.rs`
4. Teams -> `teams.rs` (calendar + window title)
5. Unknown -> calendar match only

Cascade: platform API -> calendar event -> minimal metadata (screenshot extraction happens in pipeline).

If no participants from any source, save early video frames as `participant_frame_*.png` for the pipeline.

**Commit:**

```bash
git add src-tauri/src/recorder/recorder.rs
git commit -m "feat: add platform-aware enrichment routing with cascade fallback"
```

---

### Task 17: Pipeline Integration for Screenshot Extraction

**Files:**
- Modify: `recap/pipeline.py`
- Create: `tests/test_pipeline_screenshot_extraction.py`

**Step 1: Write failing test**

Test that when metadata has no participants and `participant_frame_*.png` files exist in the working directory, the pipeline calls `extract_participants_from_screenshots` and uses the results.

**Step 2: Run test, verify failure**

**Step 3: Implement**

In `run_pipeline()`, after loading metadata and before the analyze-stage pause check, glob for `participant_frame_*.png` and call extraction if participants list is empty.

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add recap/pipeline.py tests/test_pipeline_screenshot_extraction.py
git commit -m "feat: integrate screenshot participant extraction into pipeline"
```

---

## Group 5: Auto-Record from Calendar

### Task 18: Extend Calendar Event Model

**Files:**
- Modify: `src-tauri/src/calendar.rs`
- Modify: `src/lib/tauri.ts`
- Modify: `src-tauri/src/lib.rs`

Add to `CalendarEvent`: `auto_record: bool`, `recurring_series_id: Option<String>`, `meeting_url: Option<String>`, `detected_platform: Option<String>`.

Add `parse_meeting_url()` helper that scans description/location for known meeting URL patterns (zoom.us, meet.google.com, teams.microsoft.com, meeting.tranzpay.io, meeting.zoho.*).

Add IPC commands: `set_auto_record`, `set_series_auto_record`, `get_auto_record_events`.

Update TypeScript types and wrappers.

**Commit:**

```bash
git add src-tauri/src/calendar.rs src-tauri/src/lib.rs src/lib/tauri.ts
git commit -m "feat: extend calendar events with auto-record flags and meeting URL parsing"
```

---

### Task 19: Auto-Record Armed State in Recorder

**Files:**
- Modify: `src-tauri/src/recorder/types.rs`
- Modify: `src-tauri/src/recorder/recorder.rs`

Add `Armed { event_title, expected_platform }` variant to `RecorderState`. Add `arm_for_event()` and `disarm()` methods.

Update meeting detection handler: if state is Armed, skip notification and start recording immediately.

**Commit:**

```bash
git add src-tauri/src/recorder/types.rs src-tauri/src/recorder/recorder.rs
git commit -m "feat: add Armed state for auto-record from calendar events"
```

---

### Task 20: Auto-Record Periodic Check

**Files:**
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/src/recorder/recorder.rs`
- Modify: `src/lib/stores/settings.ts`

Add 60-second periodic check in `.setup()` that compares upcoming auto-record events against lead time. Arms recorder for the nearest qualifying event. Disarms when event passes + 5 min.

On startup, also checks for currently-in-progress events (late startup edge case).

Add `autoRecordAllCalendar: boolean` to settings (default: false).

**Commit:**

```bash
git add src-tauri/src/lib.rs src-tauri/src/recorder/recorder.rs src/lib/stores/settings.ts
git commit -m "feat: add periodic auto-record check with late-startup detection"
```

---

### Task 21: Calendar UI Auto-Record Toggles

**Files:**
- Modify: `src/routes/Calendar.svelte`
- Modify: `src/lib/components/RecordingBehaviorSettings.svelte`

Add per-event record toggle (gold dot) and per-series toggle to Calendar view. Show detected platform badge from parsed meeting URLs.

Add global "Auto-record all calendar meetings" toggle to RecordingBehaviorSettings.

**Commit:**

```bash
git add src/routes/Calendar.svelte src/lib/components/RecordingBehaviorSettings.svelte
git commit -m "feat: add auto-record toggles to calendar events and global settings"
```

---

## Group 6: Integration and Polish

### Task 22: Dummy Data Updates

**Files:**
- Modify: `src/lib/dummy-data.ts`

Add platform variety to existing dummy meetings. Add `DUMMY_CALENDAR_EVENTS` with auto-record flags, meeting URLs, and detected platforms.

**Commit:**

```bash
git add src/lib/dummy-data.ts
git commit -m "feat: update dummy data with multi-platform meetings and calendar auto-record"
```

---

### Task 23: TypeScript RecorderState Update

**Files:**
- Modify: `src/lib/tauri.ts`
- Modify: `src/lib/stores/recorder.ts`
- Modify: `src/lib/components/RecordingStatusBar.svelte`

Add `Armed` variant to `RecorderState` type. Add `MeetingPlatform` type. Update RecordingStatusBar to show armed state with gold indicator.

**Commit:**

```bash
git add src/lib/tauri.ts src/lib/stores/recorder.ts src/lib/components/RecordingStatusBar.svelte
git commit -m "feat: update frontend types for Armed state and multi-platform support"
```

---

### Task 24: Update MANIFEST.md and future-phases.md

**Files:**
- Modify: `MANIFEST.md`
- Modify: `docs/plans/future-phases.md`

Regenerate MANIFEST.md with all new files (extension/, display.rs, listener.rs, share_detect.rs, google_meet.rs, zoho_meet.rs, teams.rs) and key relationships.

Update future-phases.md: mark Phase 6 complete, adjust Phase 7+ numbering.

**Commit:**

```bash
git add MANIFEST.md docs/plans/future-phases.md
git commit -m "docs: update MANIFEST.md and future-phases.md for Phase 6"
```

---

## Key Design Decisions Reference

1. **Lightweight browser extension** — MV3 Chrome/Edge for meeting URL detection. Loaded unpacked. No Web Store.
2. **Localhost HTTP on port 17839** — fixed port with fallback range. Simpler than native messaging.
3. **Accept mixed browser audio** — WASAPI captures all Chrome tabs together. WhisperX handles noise.
4. **Content script for browser share detection** — DOM observation for sharing indicators. Combined with Win32 monitoring for desktop apps.
5. **Scale to 1080p canvas** — fixed resolution regardless of window size.
6. **Google Meet uses Workspace admin API** — `meetings.space.readonly` for actual attendance.
7. **Teams falls back to calendar + window title + screenshots** — personal accounts lack meeting APIs.
8. **Screenshot extraction as universal fallback** — Claude vision reads names from meeting screenshots.
9. **Calendar arms monitor** — auto-record sets Armed state. One-shot per event. Accepts any platform.
10. **`meeting.tranzpay.io` as default Zoho pattern** — ships alongside generic patterns.
11. **Screen share monitor configurable** — user picks display in Recording Settings.
