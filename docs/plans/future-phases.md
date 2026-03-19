# Future Phases — Deferred Features

Features explicitly deferred from current phases, organized into planned phases.

## Phase 6: Recording Expansion

**Dependencies:** Phase 5c calendar integration (for auto-record)

### Non-Zoom Platform Recording

**Deferred from:** App shell design

Local audio/screen capture for Teams, Google Meet, Zoho Meet. Requires WASAPI or virtual audio cable strategy. See app-shell design doc for full context.

### Auto-Record from Calendar

**Deferred from:** Phase 5c

Per-event or per-series auto-record flag stored in calendar cache. When a matching calendar event is approaching and auto-record is on, the recorder prepares capture automatically. Depends on recording expansion — auto-record is most useful once multiple platforms are supported, not just Zoom (which already has meeting detection).

## Phase 7: Onboarding Flow (First-Run Experience)

**Deferred from:** Phase 5b
**Blocked by:** Phase 6 — onboarding should cover all recording integrations, not just Zoom

When Settings aren't configured (no vault path, no recordings directory, no calendar connected), the dashboard is empty with no guidance. A first-run onboarding flow should:

- Detect unconfigured state on app launch
- Walk the user through: recordings directory selection, Obsidian vault path, Zoho Calendar OAuth, platform OAuth (Zoom, Teams, etc.)
- Show progress indicators for each setup step
- Allow skipping optional integrations (calendar, platforms) with a "configure later" option
- After completion, transition smoothly into the main dashboard
- Re-accessible from Settings ("Re-run setup wizard")

**Design note:** Should feel lightweight and integrated — not a blocking modal wizard. Consider an inline setup checklist that lives in the dashboard until all steps are complete or dismissed.

## Phase 8: Polish

### Responsive Layout

**Deferred from:** Phase 5a

At narrow widths, the detail view player stacks above the tabbed content (no side-by-side). At wider widths, player could sit alongside transcript. Currently fixed layout only.

### Bulk Operations

**Deferred from:** Phase 5b

- Delete multiple meetings at once (checkbox select + bulk delete)
- Reprocess all failed meetings in one action
- Bulk speaker label correction (apply corrections across multiple meetings)

### Todoist Completion Sync

**Deferred from:** Phase 2 (core pipeline design)

Sync task completion status back from Todoist to vault notes. Currently one-way only (vault → Todoist).

### Light Mode

**Deferred from:** Phase 5a

Optional light mode toggle. Phase 5a/5c are dark-mode only. CSS custom properties in app.css make this straightforward — define a second set of token values under a `.light` class or `prefers-color-scheme` media query.
