# Participant Contact Cards Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add clickable participant names on calendar event cards that open floating contact popovers with name, company, email, meeting history, and clickable meeting links on events.

**Architecture:** New Rust IPC command (`get_participant_info`) backed by an in-memory participant index built from `.meeting.json` files. New `ParticipantPopover.svelte` component anchored to clicked names. Event cards updated with meeting link icons and clickable participant names. Navigation enhanced to support pre-applied filters via hash parameters.

**Tech Stack:** Rust (Tauri IPC, serde, chrono), Svelte 5 (runes), TypeScript, `@tauri-apps/plugin-opener`

---

### Task 1: Rust — Participant Index Types and State

**Files:**
- Create: `src-tauri/src/participants.rs`
- Modify: `src-tauri/src/lib.rs`

**Step 1: Create the participants module with types and managed state**

Create `src-tauri/src/participants.rs`:

```rust
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/// A single meeting record associated with a participant.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParticipantMeeting {
    pub id: String,
    pub title: String,
    pub date: String,
}

/// Full participant info returned to the frontend.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParticipantInfo {
    pub name: String,
    pub email: Option<String>,
    pub company: Option<String>,
    pub recent_meetings: Vec<ParticipantMeeting>,
}

/// Internal index entry — accumulates data across meetings.
#[derive(Debug, Clone)]
struct ParticipantRecord {
    name: String,
    email: Option<String>,
    company: Option<String>,
    meetings: Vec<ParticipantMeeting>,
}

/// In-memory participant index, keyed by lowercase name.
pub struct ParticipantIndex {
    records: HashMap<String, ParticipantRecord>,
    initialized: bool,
}

impl ParticipantIndex {
    pub fn new() -> Self {
        Self {
            records: HashMap::new(),
            initialized: false,
        }
    }
}

/// Tauri managed state wrapper.
pub type ParticipantIndexState = Mutex<ParticipantIndex>;
```

**Step 2: Register the module and managed state in lib.rs**

In `src-tauri/src/lib.rs`, add:
- `mod participants;` with the other module declarations
- `app.manage(participants::ParticipantIndexState::new(participants::ParticipantIndex::new()));` in the `setup` closure, after `credentials::init_secret_store(app)?;`

**Step 3: Verify it compiles**

Run: `cargo check --manifest-path src-tauri/Cargo.toml`
Expected: Compiles with existing warnings only

**Step 4: Commit**

```bash
git add src-tauri/src/participants.rs src-tauri/src/lib.rs
git commit -m "feat: add participant index types and managed state"
```

---

### Task 2: Rust — Build Index from `.meeting.json` Files

**Files:**
- Modify: `src-tauri/src/participants.rs`

**Step 1: Add the index-building function**

Add to `participants.rs`:

```rust
/// Extract company name from an email domain.
/// "laurie.gorby@disbursecloud.com" → "Disbursecloud"
fn company_from_email(email: &str) -> Option<String> {
    let domain = email.split('@').nth(1)?;
    let name = domain.split('.').next()?;
    if ["gmail", "yahoo", "hotmail", "outlook", "icloud", "aol", "protonmail", "live"].contains(&name) {
        return None; // Generic email providers aren't companies
    }
    let mut chars = name.chars();
    let first = chars.next()?.to_uppercase().to_string();
    Some(first + chars.as_str())
}

/// Scan all `.meeting.json` files in a directory and build the participant index.
fn build_index(recordings_dir: &Path) -> HashMap<String, ParticipantRecord> {
    let mut records: HashMap<String, ParticipantRecord> = HashMap::new();

    let entries = match std::fs::read_dir(recordings_dir) {
        Ok(e) => e,
        Err(_) => return records,
    };

    for entry in entries.flatten() {
        let path = entry.path();
        let is_meeting_json = path
            .file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.ends_with(".meeting.json"))
            .unwrap_or(false);
        if !is_meeting_json {
            continue;
        }

        let content = match std::fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let meta: serde_json::Value = match serde_json::from_str(&content) {
            Ok(m) => m,
            Err(_) => continue,
        };

        let meeting_id = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .replace(".meeting", "")
            .to_string();

        let title = meta
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("Untitled")
            .to_string();

        let date = meta
            .get("date")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        let company_from_meta = meta
            .get("company")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let participants = meta
            .get("participants")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();

        let meeting_entry = ParticipantMeeting {
            id: meeting_id,
            title,
            date,
        };

        for participant_name in &participants {
            let key = participant_name.to_lowercase();
            let record = records.entry(key).or_insert_with(|| ParticipantRecord {
                name: participant_name.clone(),
                email: None,
                company: company_from_meta.clone(),
                meetings: Vec::new(),
            });

            // Update company if not yet set
            if record.company.is_none() {
                record.company = company_from_meta.clone();
            }

            record.meetings.push(meeting_entry.clone());
        }
    }

    // Sort meetings by date descending for each participant
    for record in records.values_mut() {
        record.meetings.sort_by(|a, b| b.date.cmp(&a.date));
    }

    records
}
```

**Step 2: Verify it compiles**

Run: `cargo check --manifest-path src-tauri/Cargo.toml`
Expected: Compiles (warnings about unused functions are fine)

**Step 3: Commit**

```bash
git add src-tauri/src/participants.rs
git commit -m "feat: participant index builder from .meeting.json files"
```

---

### Task 3: Rust — IPC Commands

**Files:**
- Modify: `src-tauri/src/participants.rs`
- Modify: `src-tauri/src/lib.rs`

**Step 1: Add Tauri commands to participants.rs**

```rust
use tauri_plugin_store::StoreExt;

/// Get participant info by name and optional email.
/// Lazily initializes the index on first call.
#[tauri::command]
pub async fn get_participant_info(
    app: tauri::AppHandle,
    name: String,
    email: Option<String>,
) -> Result<ParticipantInfo, String> {
    let recordings_dir = {
        let store = app
            .store("settings.json")
            .map_err(|e| format!("Failed to open settings store: {}", e))?;
        store
            .get("recordingsFolder")
            .and_then(|v| v.as_str().map(|s| s.to_string()))
            .ok_or("Recordings folder not configured")?
    };

    let index = app.state::<ParticipantIndexState>();
    let mut index = index.lock().map_err(|e| format!("Index lock failed: {}", e))?;

    if !index.initialized {
        index.records = build_index(Path::new(&recordings_dir));
        index.initialized = true;
    }

    let key = name.to_lowercase();
    let info = if let Some(record) = index.records.get(&key) {
        let company = record.company.clone()
            .or_else(|| email.as_deref().and_then(company_from_email));
        ParticipantInfo {
            name: record.name.clone(),
            email: email.or(record.email.clone()),
            company,
            recent_meetings: record.meetings.iter().take(3).cloned().collect(),
        }
    } else {
        // No meeting history — return basic info from calendar data
        let company = email.as_deref().and_then(company_from_email);
        ParticipantInfo {
            name,
            email,
            company,
            recent_meetings: Vec::new(),
        }
    };

    Ok(info)
}

/// Incrementally update the participant index for a single meeting.
/// Called when a new meeting is processed (graphDataVersion changes).
#[tauri::command]
pub async fn update_participant_index(
    app: tauri::AppHandle,
    meeting_id: String,
) -> Result<(), String> {
    let recordings_dir = {
        let store = app
            .store("settings.json")
            .map_err(|e| format!("Failed to open settings store: {}", e))?;
        store
            .get("recordingsFolder")
            .and_then(|v| v.as_str().map(|s| s.to_string()))
            .ok_or("Recordings folder not configured")?
    };

    let json_path = PathBuf::from(&recordings_dir).join(format!("{}.meeting.json", meeting_id));
    if !json_path.exists() {
        return Ok(());
    }

    let content = std::fs::read_to_string(&json_path)
        .map_err(|e| format!("Failed to read meeting file: {}", e))?;
    let meta: serde_json::Value = serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse meeting file: {}", e))?;

    let title = meta.get("title").and_then(|v| v.as_str()).unwrap_or("Untitled").to_string();
    let date = meta.get("date").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let company = meta.get("company").and_then(|v| v.as_str()).map(|s| s.to_string());

    let participants: Vec<String> = meta
        .get("participants")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect())
        .unwrap_or_default();

    let meeting_entry = ParticipantMeeting {
        id: meeting_id,
        title,
        date,
    };

    let index = app.state::<ParticipantIndexState>();
    let mut index = index.lock().map_err(|e| format!("Index lock failed: {}", e))?;

    for participant_name in &participants {
        let key = participant_name.to_lowercase();
        let record = index.records.entry(key).or_insert_with(|| ParticipantRecord {
            name: participant_name.clone(),
            email: None,
            company: company.clone(),
            meetings: Vec::new(),
        });

        // Avoid duplicate entries for the same meeting
        if !record.meetings.iter().any(|m| m.id == meeting_entry.id) {
            record.meetings.insert(0, meeting_entry.clone());
        }
        if record.company.is_none() {
            record.company = company.clone();
        }
    }

    Ok(())
}
```

**Step 2: Register the commands in lib.rs**

Add `participants::get_participant_info` and `participants::update_participant_index` to the `.invoke_handler(tauri::generate_handler![...])` list in `src-tauri/src/lib.rs`.

**Step 3: Verify it compiles**

Run: `cargo check --manifest-path src-tauri/Cargo.toml`
Expected: Compiles

**Step 4: Commit**

```bash
git add src-tauri/src/participants.rs src-tauri/src/lib.rs
git commit -m "feat: get_participant_info and update_participant_index IPC commands"
```

---

### Task 4: TypeScript — IPC Wrappers and Types

**Files:**
- Modify: `src/lib/tauri.ts`

**Step 1: Add types and IPC wrappers**

Add after the briefing types section in `src/lib/tauri.ts`:

```typescript
// Participant types (matches Rust ParticipantInfo, ParticipantMeeting)
export interface ParticipantMeeting {
  id: string;
  title: string;
  date: string;
}

export interface ParticipantInfo {
  name: string;
  email: string | null;
  company: string | null;
  recent_meetings: ParticipantMeeting[];
}

// Participant IPC
export async function getParticipantInfo(
  name: string,
  email: string | null
): Promise<ParticipantInfo> {
  return invoke("get_participant_info", { name, email });
}

export async function updateParticipantIndex(
  meetingId: string
): Promise<void> {
  return invoke("update_participant_index", { meetingId });
}
```

**Step 2: Commit**

```bash
git add src/lib/tauri.ts
git commit -m "feat: participant info TypeScript types and IPC wrappers"
```

---

### Task 5: ParticipantPopover Component

**Files:**
- Create: `src/lib/components/ParticipantPopover.svelte`

**Step 1: Create the popover component**

Create `src/lib/components/ParticipantPopover.svelte`:

```svelte
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { getParticipantInfo, type ParticipantInfo } from "../tauri";
  import { writeText } from "@tauri-apps/plugin-clipboard-manager";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { activeFilters } from "../stores/meetings";

  interface Props {
    name: string;
    email: string | null;
    anchorRect: DOMRect;
    onclose: () => void;
  }

  let { name, email, anchorRect, onclose }: Props = $props();

  let info: ParticipantInfo | null = $state(null);
  let loading = $state(true);
  let copied = $state(false);
  let popoverEl: HTMLDivElement | undefined = $state();

  // Position: below anchor, flip up if near bottom
  let top = $state(0);
  let left = $state(0);

  function updatePosition() {
    if (!popoverEl) return;
    const rect = popoverEl.getBoundingClientRect();
    const viewportH = window.innerHeight;
    const viewportW = window.innerWidth;

    let t = anchorRect.bottom + 6;
    let l = anchorRect.left;

    // Flip up if not enough space below
    if (t + rect.height > viewportH - 16) {
      t = anchorRect.top - rect.height - 6;
    }
    // Clamp horizontally
    if (l + rect.width > viewportW - 16) {
      l = viewportW - rect.width - 16;
    }
    if (l < 16) l = 16;

    top = t;
    left = l;
  }

  onMount(async () => {
    try {
      info = await getParticipantInfo(name, email);
    } catch (err) {
      console.warn("Failed to load participant info:", err);
      info = { name, email, company: null, recent_meetings: [] };
    } finally {
      loading = false;
    }

    // Position after render
    requestAnimationFrame(updatePosition);

    // Close on Escape
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onclose();
    };
    window.addEventListener("keydown", handleKey);

    // Close on click outside
    const handleClick = (e: MouseEvent) => {
      if (popoverEl && !popoverEl.contains(e.target as Node)) {
        onclose();
      }
    };
    // Delay to avoid the opening click from immediately closing
    setTimeout(() => window.addEventListener("click", handleClick), 0);

    return () => {
      window.removeEventListener("keydown", handleKey);
      window.removeEventListener("click", handleClick);
    };
  });

  async function copyEmail() {
    if (!info?.email) return;
    try {
      await writeText(info.email);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch (err) {
      console.warn("Failed to copy email:", err);
    }
  }

  function navigateToParticipant() {
    if (!info) return;
    activeFilters.set({
      companies: [],
      participants: [info.name],
      platforms: [],
    });
    window.location.hash = "#dashboard";
    onclose();
  }

  function navigateToCompany() {
    if (!info?.company) return;
    activeFilters.set({
      companies: [info.company],
      participants: [],
      platforms: [],
    });
    window.location.hash = "#dashboard";
    onclose();
  }

  function navigateToMeeting(meetingId: string) {
    window.location.hash = `#meeting/${meetingId}`;
    onclose();
  }

  function formatShortDate(iso: string): string {
    if (!iso) return "";
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  }
</script>

<div
  bind:this={popoverEl}
  style="
    position: fixed;
    top: {top}px;
    left: {left}px;
    width: 300px;
    background: var(--raised, var(--surface));
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    z-index: 300;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    font-family: 'DM Sans', sans-serif;
  "
>
  {#if loading}
    <div style="color: var(--text-muted); font-size: 13px;">Loading...</div>
  {:else if info}
    <!-- Name -->
    <div style="font-size: 15px; font-weight: 600; color: var(--text);">
      {info.name}
    </div>

    <!-- Company -->
    {#if info.company}
      <button
        onclick={navigateToCompany}
        style="
          display: block;
          font-size: 13px;
          color: var(--text-muted);
          margin-top: 2px;
          background: none;
          border: none;
          padding: 0;
          cursor: pointer;
          font-family: 'DM Sans', sans-serif;
          text-decoration: underline;
          text-decoration-color: var(--border);
          text-underline-offset: 2px;
        "
      >{info.company}</button>
    {/if}

    <!-- Email -->
    {#if info.email}
      <div style="display: flex; align-items: center; gap: 6px; margin-top: 8px;">
        <span style="font-size: 13px; color: var(--text-secondary, var(--text-muted));">
          {info.email}
        </span>
        <button
          onclick={copyEmail}
          title="Copy email"
          style="
            background: none;
            border: none;
            cursor: pointer;
            padding: 2px;
            color: var(--text-muted);
            font-size: 13px;
            position: relative;
          "
        >
          {copied ? "✓" : "⧉"}
          {#if copied}
            <span
              style="
                position: absolute;
                top: -24px;
                left: 50%;
                transform: translateX(-50%);
                font-size: 11px;
                color: var(--green);
                white-space: nowrap;
              "
            >Copied!</span>
          {/if}
        </button>
      </div>
    {/if}

    <!-- Recent meetings -->
    {#if info.recent_meetings.length > 0}
      <div
        style="
          border-top: 1px solid var(--border);
          margin-top: 12px;
          padding-top: 10px;
        "
      >
        {#each info.recent_meetings as meeting}
          <button
            onclick={() => navigateToMeeting(meeting.id)}
            style="
              display: block;
              width: 100%;
              text-align: left;
              background: none;
              border: none;
              padding: 4px 0;
              cursor: pointer;
              font-family: 'DM Sans', sans-serif;
            "
          >
            <span style="font-size: 13px; color: var(--text);">
              {meeting.title}
            </span>
            <span style="font-size: 12px; color: var(--text-faint); margin-left: 6px;">
              {formatShortDate(meeting.date)}
            </span>
          </button>
        {/each}

        <button
          onclick={navigateToParticipant}
          style="
            display: block;
            font-size: 12.5px;
            color: var(--gold);
            margin-top: 6px;
            background: none;
            border: none;
            padding: 0;
            cursor: pointer;
            font-family: 'DM Sans', sans-serif;
          "
        >See all in Meetings →</button>
      </div>
    {/if}
  {/if}
</div>
```

**Step 2: Verify it compiles**

Run: `npx svelte-check` (or just build — HMR will catch syntax errors)

**Step 3: Commit**

```bash
git add src/lib/components/ParticipantPopover.svelte
git commit -m "feat: ParticipantPopover component with contact card UI"
```

---

### Task 6: Calendar Event Card — Meeting Link and Clickable Participants

**Files:**
- Modify: `src/routes/Calendar.svelte`

**Step 1: Add imports and popover state**

At the top of the `<script>` block in `Calendar.svelte`, add:

```typescript
import ParticipantPopover from "../lib/components/ParticipantPopover.svelte";
import { openUrl } from "@tauri-apps/plugin-opener";
import { settings } from "../lib/stores/settings";
import { get } from "svelte/store";
```

Note: `get` and `settings` are already imported — just add `ParticipantPopover` and `openUrl`.

Add popover state variables after the existing state declarations:

```typescript
let popoverParticipant: { name: string; email: string | null; rect: DOMRect } | null = $state(null);
let showAllParticipants: Record<string, boolean> = $state({});
```

Add helper functions:

```typescript
function openPopover(name: string, email: string | null, e: MouseEvent) {
    e.stopPropagation();
    const target = e.currentTarget as HTMLElement;
    popoverParticipant = { name, email, rect: target.getBoundingClientRect() };
}

function closePopover() {
    popoverParticipant = null;
}

function getVisibleParticipants(event: CalendarEvent): CalendarParticipant[] {
    const s = get(settings);
    const userName = (s.userName || "").toLowerCase();
    const filtered = event.participants.filter(
        (p) => p.name.toLowerCase() !== userName
    );
    if (showAllParticipants[event.id]) return filtered;
    return filtered.slice(0, 4);
}

function getOverflowCount(event: CalendarEvent): number {
    const s = get(settings);
    const userName = (s.userName || "").toLowerCase();
    const total = event.participants.filter(
        (p) => p.name.toLowerCase() !== userName
    ).length;
    return Math.max(0, total - 4);
}

function openMeetingLink(url: string, e: MouseEvent) {
    e.stopPropagation();
    openUrl(url);
}
```

**Step 2: Update the upcoming event card participant display**

Replace the current participant line in the upcoming section (lines ~429-433):

```svelte
{#if event.participants.length > 0}
  <div style="font-size: 12.5px; color: var(--text-faint); margin-top: 3px;">
    {event.participants.map(p => p.name).join(", ")}
  </div>
{/if}
```

With:

```svelte
{@const visible = getVisibleParticipants(event)}
{@const overflow = getOverflowCount(event)}
{#if visible.length > 0}
  <div style="font-size: 12.5px; color: var(--text-faint); margin-top: 3px; display: flex; flex-wrap: wrap; gap: 0;">
    {#each visible as participant, i}
      <button
        onclick={(e) => openPopover(participant.name, participant.email, e)}
        style="
          background: none;
          border: none;
          padding: 0;
          cursor: pointer;
          font-family: 'DM Sans', sans-serif;
          font-size: 12.5px;
          color: var(--text-faint);
          text-decoration: underline;
          text-decoration-color: transparent;
          text-underline-offset: 2px;
        "
        onmouseenter={(e) => { (e.currentTarget as HTMLElement).style.textDecorationColor = 'var(--text-faint)'; }}
        onmouseleave={(e) => { (e.currentTarget as HTMLElement).style.textDecorationColor = 'transparent'; }}
      >{participant.name}{i < visible.length - 1 || overflow > 0 ? ',\u00A0' : ''}</button>
    {/each}
    {#if overflow > 0 && !showAllParticipants[event.id]}
      <button
        onclick={(e) => { e.stopPropagation(); showAllParticipants = { ...showAllParticipants, [event.id]: true }; }}
        style="
          background: none;
          border: none;
          padding: 0;
          cursor: pointer;
          font-family: 'DM Sans', sans-serif;
          font-size: 12.5px;
          color: var(--text-muted);
        "
      >+{overflow} more</button>
    {/if}
  </div>
{/if}
```

**Step 3: Add meeting link icon to the upcoming event title row**

In the title row (after the platform badge, before/alongside the matched recording link), add a meeting link icon. Find the `{#if matchedId}` block and add before it:

```svelte
{#if event.meeting_url}
  <button
    onclick={(e) => openMeetingLink(event.meeting_url!, e)}
    title="Join meeting"
    style="
      background: none;
      border: none;
      padding: 0;
      cursor: pointer;
      font-size: 13px;
      color: var(--blue, var(--gold));
      flex-shrink: 0;
    "
  >↗</button>
{/if}
```

**Step 4: Apply the same changes to the past events section**

Replace the past events participant display (lines ~517-521):

```svelte
{#if event.participants.length > 0}
  <div style="font-size: 12.5px; color: var(--text-faint); margin-top: 2px;">
    {event.participants.map(p => p.name).join(", ")}
  </div>
{/if}
```

With the same clickable participant pattern (identical to the upcoming section code from Step 2).

Add the meeting link icon to the past event title row as well (same pattern as Step 3).

**Step 5: Render the popover at the bottom of the template**

Just before the closing `</div>` of the Calendar component, add:

```svelte
{#if popoverParticipant}
  <ParticipantPopover
    name={popoverParticipant.name}
    email={popoverParticipant.email}
    anchorRect={popoverParticipant.rect}
    onclose={closePopover}
  />
{/if}
```

**Step 6: Verify it compiles and renders**

Run the app with `npx tauri dev`, navigate to Calendar, verify:
- Meeting link icons appear next to platform badges
- Participant names are individually clickable
- User's own name is filtered out
- "+N more" appears when > 4 participants
- Clicking a name opens the popover with contact info

**Step 7: Commit**

```bash
git add src/routes/Calendar.svelte
git commit -m "feat: clickable participant names and meeting links on calendar events"
```

---

### Task 7: Clipboard Permission

**Files:**
- Modify: `src-tauri/capabilities/default.json`

**Step 1: Add clipboard write permission**

The `ParticipantPopover` uses `writeText` from `@tauri-apps/plugin-clipboard-manager`. Check if the clipboard plugin is already in `Cargo.toml` and `default.json`. If not:

Add to `src-tauri/capabilities/default.json` permissions array:
```json
"clipboard-manager:allow-write-text"
```

Check `src-tauri/Cargo.toml` for `tauri-plugin-clipboard-manager`. If missing, add it:
```bash
cd src-tauri && cargo add tauri-plugin-clipboard-manager
```

And register in `lib.rs` setup:
```rust
.plugin(tauri_plugin_clipboard_manager::init())
```

**Step 2: Verify it compiles**

Run: `cargo check --manifest-path src-tauri/Cargo.toml`

**Step 3: Commit**

```bash
git add src-tauri/capabilities/default.json src-tauri/Cargo.toml src-tauri/src/lib.rs
git commit -m "feat: add clipboard plugin for email copy"
```

---

### Task 8: Remove Debug Logging from calendar.rs

**Files:**
- Modify: `src-tauri/src/calendar.rs`

**Step 1: Remove the debug eprintln**

Find and remove this line from `zoho_calendar_request`:
```rust
eprintln!("[Zoho Calendar] Response (first 1000 chars): {}", &body[..body.len().min(1000)]);
```

**Step 2: Commit**

```bash
git add src-tauri/src/calendar.rs
git commit -m "chore: remove debug logging from Zoho calendar sync"
```

---

### Task 9: Manual Testing Checklist

Test the following scenarios:

1. **Upcoming event with participants**: Names appear as clickable links, user's name filtered out
2. **Click participant name**: Popover appears below the name with contact info
3. **Popover positioning**: Near bottom of screen, popover flips above
4. **Copy email**: Click copy button → "Copied!" tooltip appears and fades
5. **Company from meeting metadata**: Participant who appeared in past meetings shows correct company
6. **Company from email domain**: New participant with corporate email shows domain-based company
7. **Generic email**: Participant with gmail/yahoo shows no company
8. **Recent meetings in popover**: Shows up to 3 past meetings, clickable → navigates to meeting detail
9. **"See all in Meetings →"**: Navigates to dashboard with participant filter pre-applied
10. **Company click**: Navigates to dashboard with company filter pre-applied
11. **Meeting link icon**: Appears next to platform badge, opens meeting URL in browser
12. **"+N more"**: Events with > 4 participants show overflow count, clicking expands
13. **Past events**: Same clickable participants and meeting link icons
14. **Popover dismissal**: Click outside closes it, Escape closes it
15. **Only one popover at a time**: Opening a new one closes the previous
16. **No past meetings**: Popover shows name/email/company but no meeting section
17. **Events load from cache on restart**: Upcoming events appear immediately on app open
