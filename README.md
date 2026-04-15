# Recap

Recap records your meetings, transcribes them locally with NVIDIA Parakeet, runs speaker diarization with NeMo Sortformer, sends transcripts through Claude for analysis, and writes structured notes directly into your Obsidian vault. Everything runs on your machine except the LLM call.

## Architecture

Two components: a Python daemon that handles all the heavy lifting, and an Obsidian plugin that provides the UI.

```
                     Obsidian Vault (_Recap/)
             +--------------------------------------+
             |  Disbursecloud/Meetings/People/Tasks/ |
             |  Personal/Meetings/People/Tasks/      |
             |  Activism/Meetings/People/Tasks/      |
             |  Calendar/Briefings/                  |
             |  .recap/ (config, logs, status)       |
             +----------+-----------+---------------+
                        |           |
              writes    |           |  reads
             directly   |           |  (Vault API)
                        |           |
          +-------------v--+  HTTP  +v------------------+
          |  recap-daemon  |<------>|  Obsidian Plugin   |
          |  (Python)      |  /WS   |  (TypeScript)      |
          |                |  local |                    |
          |  Detection     |  host  |  Meeting list view |
          |  Recording     |        |  Live transcript   |
          |  ML pipeline   |        |  Speaker correction|
          |  Calendar sync |        |  Status bar        |
          |  System tray   |        |  Settings tab      |
          |  OAuth flows   |        |  Recording controls|
          |  Streaming     |        |  Notifications     |
          +----------------+        +--------------------+
```

The daemon is the critical path. It detects meetings via window titles and browser extension signals, captures audio (WASAPI loopback via PyAudioWPatch), streams real-time transcription and diarization, runs the full ML pipeline post-meeting, and writes vault notes. None of this requires Obsidian to be open. If the plugin breaks, you lose the dashboard but never lose a recording.

The plugin is the non-critical path. It displays recording state, lets you browse meetings, correct speaker labels, trigger reprocessing, and manage settings. Data flows primarily through the vault filesystem; the HTTP/WebSocket channel handles commands and live state only.

## Status

Active development. The daemon, plugin, calendar sync, and browser-extension flows are working, and the current stabilization pass has the repo back to a green test/build baseline. Packaging and scheduled briefing automation are still not implemented.

## Prerequisites

- Python 3.10+
- NVIDIA GPU with CUDA 12.6 (RTX 4070 or equivalent, 12GB VRAM)
- Windows 11
- ffmpeg on PATH (for AAC audio conversion)
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-cli) installed and authenticated
- Obsidian
- SSD for recordings storage (multi-stream audio capture needs the throughput)

## Development Setup

```bash
git clone https://github.com/TimSimpsonJr/recap.git
cd recap
pip install uv
uv sync --extra dev
```

This is enough for tests and codebase work.

To run the daemon locally, install the daemon runtime extras too:

```bash
uv sync --extra dev --extra daemon
```

PyTorch CUDA 12.6 wheels are configured in `pyproject.toml`. Install `--extra ml` when you want to run the full local transcription/diarization stack.

### Running the daemon

```bash
uv run python -m recap.daemon config.yaml
```

### Installing the Obsidian plugin

```bash
cd obsidian-recap
npm install
npm run build
```

Copy `obsidian-recap/main.js`, `obsidian-recap/manifest.json`, and `obsidian-recap/styles.css` into your vault's `.obsidian/plugins/recap/` directory. Restart Obsidian and enable the plugin.

### Running tests

```bash
uv run pytest -q
```

48 test modules covering daemon, pipeline, recorder, streaming, calendar, and plugin integration.

## Project Structure

- `recap/daemon/` -- Python daemon: HTTP/WebSocket server, system tray, meeting detection, audio recording, calendar sync, OAuth, streaming transcription/diarization
- `recap/pipeline/` -- Post-meeting ML pipeline: Parakeet transcription, NeMo diarization, AAC conversion
- `recap/` (top-level modules) -- Analysis (Claude CLI), vault writer, config, models, errors
- `obsidian-recap/` -- Obsidian plugin: meeting list, live transcript, speaker correction, status bar, settings
- `extension/` -- Chrome/Edge MV3 extension for meeting URL detection
- `prompts/` -- Claude prompt templates for analysis and briefings
- `tests/` -- Pytest suite (48 test modules)
- `docs/plans/` -- Design docs and phase implementation plans

## Design

See the full architecture design doc: [Obsidian Plugin + Python Daemon Architecture](docs/plans/2026-04-13-obsidian-plugin-architecture.md).

## License

MIT
