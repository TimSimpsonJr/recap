# Test Readiness — Design

**Goal:** Get Recap running end-to-end — from Python pipeline standalone testing through a live Teams meeting with full automated capture.

## Current State

**Available:** Python 3.12, Node 25, Rust 1.94, ffmpeg 8, RTX 4070, npm deps installed, Rust has been built.

**Missing:**
- PyTorch has no CUDA support (CPU-only install)
- WhisperX / pyannote.audio not installed
- PyInstaller not installed (needed for sidecar rebuild)
- Claude CLI not in system PATH (exists at `%APPDATA%/Claude/claude-code/<version>/claude.exe`)
- HuggingFace token needed for pyannote gated models
- No test recording or metadata file
- No test vault directory

## Approach: Pipeline-First

Validate the Python pipeline standalone before testing through the Tauri app. This isolates the ML stack (the most complex part) from the desktop layer.

## Phase 1: Python Environment

Create a virtual environment to isolate the heavy ML dependency stack.

```
python -m venv .venv
.venv\Scripts\activate
```

Install dependencies (order matters — WhisperX pins specific torch versions):
1. Install WhisperX first, let it pull its preferred PyTorch version
2. Verify torch sees CUDA (`python -c "import torch; print(torch.cuda.is_available())"`)
3. If WhisperX doesn't pull CUDA torch, reinstall torch with cu121 index
4. Install recap in editable mode: `pip install -e ".[ml,todoist,dev]"`
5. Install PyInstaller: `pip install pyinstaller`

**User action required:** Accept the pyannote speaker-diarization-3.1 model license at `hf.co/pyannote/speaker-diarization-3.1` and generate an access token at `hf.co/settings/tokens`.

**Claude CLI:** Set `claude.command` in config.yaml to the full path at `%APPDATA%/Claude/claude-code/<version>/claude.exe` (the Rust briefing code auto-discovers this, but the Python side reads it from config).

## Phase 2: Test Data

Create `tests/fixtures/` with:
- A short test audio file (2-3 min recording with at least two speakers)
- A metadata JSON file:
  ```json
  {
    "title": "Test Meeting",
    "date": "2026-03-25",
    "participants": [
      {"name": "Tim"},
      {"name": "Other Person"}
    ],
    "platform": "manual"
  }
  ```
- A temp vault directory (e.g., `tests/temp-vault/`) for output — not the real Obsidian vault
- A test `config.yaml` pointing at the temp vault with the resolved Claude CLI path

## Phase 3: Pipeline Validation (Standalone)

Run the pipeline against test data, skipping the `merge` stage (that's the Rust-side ffmpeg merge of separate capture streams — not applicable for a pre-existing audio file):

```
python -m recap process --config tests/fixtures/config.yaml --from frames tests/fixtures/test-audio.wav tests/fixtures/test-metadata.json
```

Validate each stage:
- **frames:** Extracts video frames (skipped for audio-only — verify it handles gracefully)
- **transcribe:** WhisperX produces speaker-labelled transcript
- **analyze:** Claude CLI generates meeting analysis (key points, action items, etc.)
- **export:** Vault note written to temp vault directory

Check `status.json` for stage completion and verify the vault note content.

## Phase 4: Live Teams Meeting

Full automated flow:
1. Build and launch the Tauri app (`npm run tauri dev`)
2. Complete onboarding (storage paths, vault → temp vault, Claude CLI path)
3. Start a desktop Teams meeting
4. Verify: WASAPI monitor detects `Teams.exe` audio session → recorder arms → captures audio + screen
5. End the meeting → recorder produces merged recording
6. Pipeline runs automatically → vault note appears in temp vault

Note: Desktop Teams detection uses WASAPI audio session monitoring (`monitor.rs` watches for `Teams.exe`), not the browser extension. The browser extension is only needed for browser-based meetings (Google Meet, Zoho Meet, etc.).

## Cleanup

After testing is validated:
- Remove `tests/temp-vault/` contents
- Point the app at the real Obsidian vault
- Optionally rebuild the sidecar binary via `python scripts/build-sidecar.py`
