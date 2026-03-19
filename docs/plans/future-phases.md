# Future Phases — Deferred Features

Features explicitly deferred from current phases, organized into planned phases.

## ~~Phase 6: Recording Expansion~~ (Complete)

Multi-platform recording (Teams, Google Meet, Zoho Meet), browser extension for meeting detection, screen share detection, per-platform metadata enrichment, and calendar-driven auto-record are all implemented.

## ~~Phase 7: Onboarding Flow~~ (Complete)

First-run onboarding wizard (4-step full-screen flow for required config), inline dashboard checklist for optional integrations (OAuth providers, browser extension), Rust-side config.yaml generation from settings store, secret management via Stronghold + env vars, Claude model/CLI settings, and actionable pipeline error messages are all implemented.

## ~~Phase 8: Polish~~ (Complete — except Light Mode)

Responsive layout, bulk operations (delete, reprocess, speaker rename), Todoist bidirectional sync with project grouping, and comprehensive animation/UI polish are all implemented. Light mode remains deferred.

### Light Mode

**Deferred from:** Phase 5a

Optional light mode toggle. Phase 5a/5c are dark-mode only. CSS custom properties in app.css make this straightforward — define a second set of token values under a `.light` class or `prefers-color-scheme` media query.
