# Future Phases — Deferred Features

Features explicitly deferred from current phases, organized into planned phases.

## ~~Phase 6: Recording Expansion~~ (Complete)

Multi-platform recording (Teams, Google Meet, Zoho Meet), browser extension for meeting detection, screen share detection, per-platform metadata enrichment, and calendar-driven auto-record are all implemented.

## ~~Phase 7: Onboarding Flow~~ (Complete)

First-run onboarding wizard (4-step full-screen flow for required config), inline dashboard checklist for optional integrations (OAuth providers, browser extension), Rust-side config.yaml generation from settings store, secret management via Stronghold + env vars, Claude model/CLI settings, and actionable pipeline error messages are all implemented.

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
