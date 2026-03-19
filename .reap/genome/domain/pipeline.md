# Domain: Pipeline

## Responsibility

Python ML pipeline that processes meeting recordings into transcripts, analysis, vault notes, and tasks. Runs as a Tauri sidecar — invoked by the app, not interactive.

## Key Entities

- **Pipeline stages** — transcribe (WhisperX), frames (video extraction), analyze (Claude), vault (Obsidian note writer), todoist (task sync)
- **status.json** — per-meeting progress file; written after each stage, read by the app frontend for pipeline dots
- **config.yaml** — YAML config for paths, API keys, model settings; loaded by `config.py`
- **Models** (`models.py`) — data classes shared across stages (transcript segments, analysis results, etc.)

## Boundaries

- Launched as a sidecar by the Rust backend — no direct IPC with the frontend
- Communicates results via filesystem only (status.json, output files, vault notes)
- Owns Obsidian vault note generation — the app reads but never writes vault notes
- `--from` / `--only` CLI flags allow the app to retry individual stages without re-running everything
