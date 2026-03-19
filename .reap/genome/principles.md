# Project Principles

## Architecture

- **Three-layer desktop app: Svelte UI → Tauri/Rust IPC → Python ML sidecar** — keeps UI responsive, leverages Rust for system access, and Python for the ML ecosystem (WhisperX, Pyannote). Each layer communicates through well-defined boundaries.
- **Offline-first, local-data ownership** — recordings, transcripts, and analysis stay on the user's machine. No cloud storage dependency. Vault notes live in the user's Obsidian vault.
- **Pipeline stages are independently retryable** — each ML pipeline stage writes status.json progress, supporting `--from`/`--only` flags so failures don't require full re-runs.

## Code Quality

- **Optimize for integration, not standalone use** — Recap is being built as a full desktop app; don't over-engineer individual components for reuse outside this context.
- **Evaluate caching/concurrency before proposing** — don't add by default, but always consider whether they'd benefit the recommendation.

## User Experience

- **Dark mode first** — top nav bar, collapsible filter sidebar. Theme colors are evolving but dark mode is the baseline.
- **SSD-aware recording** — warn users when selecting HDD for recordings storage since multi-stream capture needs SSD throughput.
