# Domain: Pipeline

## Responsibility

Post-meeting ML pipeline that turns a recorded audio file into a canonical Obsidian note. Launched as a subprocess by the daemon, not interactive.

## Key Entities

- **Stage orchestrator** (`pipeline/__init__.py`) — runs stages in order, writes `status.json` per meeting, supports `--from` and `--only` for targeted retries.
- **Stages:**
  - `transcribe.py` — batch NVIDIA Parakeet ASR.
  - `diarize.py` — NeMo Sortformer speaker diarization.
  - `audio_convert.py` — WAV → AAC (ffmpeg) for the archive format.
  - `analyze.py` (top-level `recap/`) — Claude CLI or Ollama subprocess invocation for meeting analysis; backend chosen per-org by `llm-backend` config.
  - `vault.py` (top-level `recap/`) — writes the canonical note; `write_meeting_note` calls `build_canonical_frontmatter`; upsert updates `EventIndex` via `_update_index_if_applicable`.
- **`PipelineRuntimeConfig`** (`daemon/runtime_config.py`) — projection of `DaemonConfig` + `OrgConfig` + `RecordingMetadata` that the pipeline consumes.
- **`status.json`** — per-meeting progress file; written after each stage; surfaced to the plugin via daemon HTTP endpoints.
- **Shared models** — `models.py` / `errors.py` shared across daemon, pipeline, analysis.

## Boundaries

- Invoked by the daemon, not by the plugin directly.
- Reads recordings from disk and writes vault notes directly (shared helpers in `recap/vault.py` and `recap/artifacts.py`).
- Does not open HTTP sockets, a tray, or any UI — it is headless.
- `--from` / `--only` CLI flags allow the daemon (or a human running `run_pipeline.py`) to retry individual stages without a full rerun.
- Emits to `EventJournal` indirectly: the daemon wraps pipeline launches and records stage failures.
