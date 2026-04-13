# Recap

Recap records your meetings, transcribes them locally with NVIDIA Parakeet, runs speaker diarization with NeMo Sortformer, sends transcripts through Claude for analysis, and writes structured notes directly into your Obsidian vault. Everything runs on your machine except the LLM call.

## Architecture

Two components: a Python daemon that handles all the heavy lifting, and an Obsidian plugin that provides the UI.

```
                     Obsidian Vault (_Recap/)
             ┌──────────────────────────────────────┐
             │  Disbursecloud/Meetings/People/Tasks/ │
             │  Personal/Meetings/People/Tasks/      │
             │  Activism/Meetings/People/Tasks/      │
             │  Calendar/Briefings/                  │
             │  .recap/ (config, logs, status)       │
             └──────────┬───────────┬───────────────┘
                        │           │
              writes    │           │  reads
             directly   │           │  (Vault API)
                        │           │
          ┌─────────────▼──┐  HTTP  ┌▼──────────────────┐
          │  recap-daemon  │◄──────►│  Obsidian Plugin   │
          │  (Python)      │  /WS   │  (TypeScript)      │
          │                │  local │                    │
          │  Detection     │  host  │  Meeting list view │
          │  Recording     │        │  Live transcript   │
          │  ML pipeline   │        │  Speaker correction│
          │  Calendar sync │        │  Status bar        │
          │  System tray   │        │  Settings tab      │
          │  OAuth flows   │        │  Recording controls│
          └────────────────┘        └────────────────────┘
```

The daemon is the critical path. It detects meetings, captures audio (WASAPI loopback via PyAudioWPatch), transcribes, diarizes, analyzes, and writes vault notes. None of this requires Obsidian to be open. If the plugin breaks, you lose the dashboard but never lose a recording.

The plugin is the non-critical path. It displays recording state, lets you browse meetings, correct speaker labels, trigger reprocessing, and manage settings. Data flows primarily through the vault filesystem; the HTTP/WebSocket channel handles commands and live state only.

## Status

In development. Actively being built. The Tauri desktop app (Rust + Svelte) has been removed in favor of this architecture.

## Prerequisites

- Python 3.10+
- NVIDIA GPU with CUDA 12.6 (RTX 4070 or equivalent, 12GB VRAM)
- Windows 11
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-cli) installed and authenticated
- Obsidian with [Dataview](https://github.com/blacksmithgu/obsidian-dataview) and [Full Calendar](https://github.com/davish/obsidian-full-calendar) plugins
- SSD for recordings storage (multi-stream audio capture needs the throughput)

## Development Setup

```bash
git clone https://github.com/TimSimpsonJr/recap.git
cd recap
pip install uv
uv sync --extra dev
```

PyTorch CUDA 12.6 wheels are configured in `pyproject.toml`. Full setup instructions will be expanded as implementation progresses.

## Design

See the full architecture design doc: [Obsidian Plugin + Python Daemon Architecture](docs/plans/2026-04-13-obsidian-plugin-architecture.md).

## License

MIT
