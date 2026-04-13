# Obsidian Plugin Pivot: Implementation Overview

> **For Claude:** Each phase below is a separate plan document. Execute them in order using superpowers:executing-plans.

**Goal:** Replace the Tauri desktop app with a Python daemon + Obsidian plugin, per the architecture design in `docs/plans/2026-04-13-obsidian-plugin-architecture.md`.

**Branch:** All work on `obsidian-pivot` branch. Do not merge to master until all phases are complete.

---

## Phases

| Phase | Doc | What it builds | Independently useful? |
|-------|-----|---------------|----------------------|
| 0 | `phase-0-repo-cleanup.md` | Feature branch, remove Tauri/Svelte, close stale issues, update README | Yes (clean slate) |
| 1 | `phase-1-daemon-foundation.md` | Config, logging, tray icon, HTTP server skeleton, startup validation | Yes (daemon runs, shows tray) |
| 2 | `phase-2-audio-recording.md` | PyAudioWPatch + pyFLAC capture, silence detection, manual start/stop | Yes (can record meetings) |
| 3 | `phase-3-pipeline.md` | Parakeet + NeMo transcription/diarization, adapted vault writer, FLAC-to-AAC | Yes (record + process meetings end-to-end) |
| 4 | `phase-4-meeting-detection.md` | EnumWindows, extension listener, calendar arming, Signal popup, Teams UIA | Yes (automatic recording) |
| 5 | `phase-5-calendar-oauth.md` | Authlib OAuth, Zoho/Google calendar sync, vault note creation | Yes (calendar in vault) |
| 6 | `phase-6-plugin-core.md` | Plugin scaffold, meeting list, status bar, recording controls, settings | Yes (Obsidian dashboard) |
| 7 | `phase-7-plugin-advanced.md` | Speaker correction, live transcript view, rename processing, notification history | Yes (full plugin features) |
| 8 | `phase-8-streaming.md` | Real-time Parakeet + NeMo, WebSocket feed, skip-batch logic | Yes (live transcription) |
| 9 | `phase-9-packaging.md` | PyInstaller, Task Scheduler auto-start, extension cleanup, E2E testing | Yes (distributable) |

## Dependencies

```
Phase 0 ──→ Phase 1 ──→ Phase 2 ──→ Phase 3
                │                       │
                └──→ Phase 5            └──→ Phase 4
                                              │
                         Phase 6 ◄────────────┘
                           │                  │
                           └──→ Phase 7       └──→ Phase 5 (if not done)
                                  │
                                  └──→ Phase 8
                                         │
                                         └──→ Phase 9
```

Phase 5 (calendar/OAuth) can run in parallel with Phases 2-4. Phase 6 (plugin) needs Phases 1-4 done. Phase 8 (streaming) needs Phase 7. Phase 9 is the final pass.
