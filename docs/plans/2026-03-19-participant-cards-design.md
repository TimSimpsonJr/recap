# Participant Contact Cards — Design

## Goal

Add clickable participant names on calendar event cards that open floating contact popovers with name, company, email, and meeting history — plus clickable meeting links on events.

## Architecture

Frontend-only popover component backed by a new Rust IPC command for participant data. The Rust backend builds a participant index from `.meeting.json` files, cached in memory with incremental updates.

## Event Card Changes

- **Meeting link**: Clickable icon next to the platform badge. Opens `meeting_url` via `@tauri-apps/plugin-opener`. Shown whenever `meeting_url` is present, regardless of `detected_platform`.
- **Clickable participant names**: Each participant rendered as a separate clickable span (not comma-separated text). The user's own name (from `userName` setting) is filtered out. Capped at 4 visible names with "+N more" overflow that expands inline. Clicking a name opens the popover.
- **Applies to both upcoming and past event cards** for consistency.

## Participant Popover Card

Floating card anchored near the clicked name, styled like a contact card (dark theme, matches app aesthetic).

**Layout (top to bottom):**
1. **Name** — bold, 15px
2. **Company** — subtitle, clickable (navigates to Meetings tab filtered by company). Source: `.meeting.json` company field first, email domain fallback (e.g. `@disbursecloud.com` → "Disbursecloud").
3. **Email** — with copy-to-clipboard icon button. "Copied!" tooltip on click, fades after 1.5s. Hidden when email is null.
4. **Divider**
5. **Recent meetings** — up to 3 past meetings with this person, each showing title + date. Clickable → navigates to meeting detail. Hidden (including divider) when no past meetings exist.
6. **"See all in Meetings →"** — link that navigates to Meetings tab with participant filter pre-applied. Hidden when no past meetings.

**Behavior:**
- Positioned below the clicked name, flips above if near viewport bottom. Clamped horizontally to viewport.
- Dismissed on click outside or Esc.
- Only one popover open at a time.
- First-time participants (no meeting history): show name, email, domain-based company, no meeting section.

## Data & Infrastructure

### New Rust IPC: `get_participant_info`

Takes a participant name and email, returns:
```json
{
  "name": "Laurie Gorby",
  "email": "laurie.gorby@disbursecloud.com",
  "company": "Disbursecloud",
  "recent_meetings": [
    { "id": "abc123", "title": "Alpine Rio / Disbursecloud Check-In", "date": "2026-03-18T12:00:00Z" }
  ]
}
```

Built by scanning `.meeting.json` files in the recordings directory. Company is extracted from the `company` field in meeting metadata, falling back to email domain.

### Participant Index (Rust-side, in-memory)

- Built once on first `get_participant_info` call (lazy init).
- Stored in Tauri managed state behind a `Mutex`.
- **Incremental update**: When `graphDataVersion` changes (new meeting processed), the frontend calls a new `update_participant_index` command with the meeting ID. Only participants from that meeting are re-indexed — not a full rebuild.
- Index structure: `HashMap<String, ParticipantRecord>` keyed by lowercase name.

### Navigation with Pre-applied Filters

The app's hash routing supports filter parameters:
- `#meetings?participant=Laurie+Gorby` → Meetings tab opens with participant filter active
- `#meetings?company=Disbursecloud` → Meetings tab opens with company filter active

The Meetings tab reads these params on mount and applies them to the FilterSidebar state.

### Copy Feedback

"Copied!" tooltip appears next to the copy button, fades after 1.5s. Uses a simple `setTimeout` + CSS opacity transition.
