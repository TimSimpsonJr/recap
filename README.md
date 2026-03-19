# Recap

A desktop app that records your meetings, transcribes them, pulls out the important stuff, and writes it all up as Obsidian vault notes. Runs entirely on your machine.

Recap sits in your system tray, detects when a meeting starts (Zoom, Google Meet, Teams, Zoho Meet), captures audio and video, then runs the recording through WhisperX for transcription and Claude for analysis. The output is structured Obsidian notes with action items, key decisions, and participant context, plus optional Todoist task sync.

## What it does

- **Auto-detects meetings** from desktop apps (WASAPI audio monitoring) and browser tabs (Chrome/Edge extension)
- **Records dual-stream audio + screen video** via Windows WASAPI and Graphics Capture API, encoded to H.265 with NVENC
- **Switches capture to your shared screen** when you start presenting (detected via Win32 toolbar monitoring or extension DOM observation)
- **Transcribes with speaker diarization** using WhisperX + Pyannote 3.1
- **Analyzes transcripts** with Claude to extract summaries, decisions, action items, and follow-ups
- **Writes Obsidian vault notes** with wikilinks between participants, meetings, and topics
- **Syncs action items to Todoist** with configurable project mapping
- **Arms the recorder from calendar events** so meetings start recording automatically
- **Enriches recordings with participant data** from platform APIs (Zoom, Google Meet, Zoho) or screenshot extraction via Claude vision

## Requirements

- Windows 11
- NVIDIA GPU (for ffmpeg H.265 NVENC encoding)
- SSD for the recordings directory (simultaneous audio + video capture needs the throughput)
- Python 3.10+ with CUDA 12.1 (for WhisperX)
- Node.js 18+
- Rust toolchain (for Tauri v2)
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-cli) installed and authenticated
- ffmpeg on PATH

## Getting started

### 1. Clone and install dependencies

```bash
git clone https://github.com/TimSimpsonJr/recap.git
cd recap
npm install
```

### 2. Set up the Python pipeline

```bash
pip install uv
uv sync --extra ml --extra todoist --extra dev
```

PyTorch CUDA 12.1 wheels are pulled automatically from the PyTorch index (configured in `pyproject.toml`).

### 3. Configure the pipeline

Copy `config.example.yaml` to `config.yaml` and fill in your paths:

```yaml
vault_path: "C:/Users/you/path/to/vault"
recordings_path: "C:/Users/you/recap-data/recordings"
frames_path: "C:/Users/you/recap-data/frames"
user_name: "Your Name"

whisperx:
  model: "large-v3"
  device: "cuda"
  language: "en"

huggingface_token: "hf_your_token_here"  # for Pyannote speaker diarization

todoist:
  api_token: "your_todoist_api_token"  # optional
  default_project: "Recap"

claude:
  command: "claude"
```

Required: `vault_path`, `recordings_path`, `frames_path`, `user_name`.
Everything else has defaults or is optional.

### 4. Run the app

```bash
npm run tauri dev
```

First build takes a few minutes (compiling the Rust backend). After that, the app window opens and you can configure OAuth providers, vault paths, and recording settings in Settings.

### 5. Install the browser extension (optional)

For detecting Google Meet, Teams web, and Zoho Meet in the browser:

1. Open Chrome or Edge, go to `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked**, select the `extension/` folder
4. The extension icon should show a green "ON" badge when Recap is running

## Architecture

Three layers, each with a clear job:

**Svelte 5 frontend** (`src/`) handles the UI: dashboard with meeting list, detail views with video player and transcript, calendar integration, participant graph, and settings. Talks to Rust via Tauri IPC.

**Rust backend** (`src-tauri/src/`) handles system-level stuff: WASAPI audio capture, Graphics Capture screen recording, process monitoring, OAuth flows, credential storage (Stronghold), calendar sync, and the recorder state machine. Also runs a localhost HTTP listener for extension signals.

**Python pipeline** (`recap/`) handles the ML work: WhisperX transcription, Claude analysis, Obsidian vault note generation, and Todoist sync. Runs as a Tauri sidecar, communicates via filesystem (`status.json` per meeting).

The browser extension (`extension/`) is a lightweight MV3 Chrome/Edge extension that detects meeting URLs and screen sharing state, signaling the Rust backend via localhost HTTP.

### Recorder state machine

```
Idle ──(calendar arm)──> Armed ──(meeting detected)──> Recording
 |                         |                              |
 |                         └──(no meeting)──> Idle        | (stops)
 |                                                        v
 ├──(meeting detected)──> Detected ──(accept)──> Recording ──> Processing ──> Idle
 |                           |
 |                           └──(decline)──> Declined ──> Idle
```

During recording, screen share events switch the video capture source between the meeting window and your display without interrupting the session.

### Pipeline stages

Each stage writes progress to `status.json`. If a stage fails, you can retry from that point with `--from`:

```
merge ──> frames ──> transcribe ──> diarize ──> analyze ──> export
```

The analyze stage pauses for speaker review if no participants were found (from API or screenshot extraction). The frontend shows this as a "waiting" state in the pipeline dots.

## Platform support

| Platform    | Detection         | Participants            | Notes                                     |
|-------------|-------------------|-------------------------|-------------------------------------------|
| Zoom        | WASAPI (desktop)  | Zoom API                | Full OAuth + API access                   |
| Google Meet | Extension (browser) | Google Meet API        | Requires Workspace admin                  |
| Zoho Meet   | Extension (browser) | Zoho Meeting API       | Regional endpoints (com/eu/in/com.au)     |
| Teams       | WASAPI or extension | Calendar + window title | Personal accounts can't access meeting API |

When API participant data isn't available, Recap falls back to calendar event attendees, then to screenshot extraction via Claude vision.

## Running tests

```bash
# Python pipeline tests
python -m pytest tests/ -v

# Rust type checking
cd src-tauri && cargo check
```

## Project structure

See [MANIFEST.md](MANIFEST.md) for the full annotated file tree, key relationships between modules, and the recorder state machine documentation.

## License

MIT
