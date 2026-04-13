# Test Readiness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Get the Recap pipeline running end-to-end — standalone first, then through the Tauri app with a live Teams meeting.

**Architecture:** Pipeline-first approach. Set up the Python ML environment, create test fixtures, validate the pipeline standalone via `python -m recap process`, then build the sidecar and test the full Tauri app flow with a real Teams call.

**Tech Stack:** Python 3.12, PyTorch cu121, WhisperX, pyannote.audio, PyInstaller, Claude CLI, Tauri v2

---

### Task 1: Create Python Virtual Environment

**Files:**
- Create: `.venv/` (via python -m venv)

**Step 1: Create the virtual environment**

Run (in PowerShell or cmd, NOT bash — venv activate scripts are Windows-specific):
```
python -m venv .venv
```

**Step 2: Activate it**

Run:
```
.venv\Scripts\activate
```

**Step 3: Verify activation**

Run:
```
python -c "import sys; print(sys.prefix)"
```

Expected: Path ends with `.venv` (not the global Python path).

---

### Task 2: Install PyTorch with CUDA 12.1

**Step 1: Uninstall existing CPU-only torch**

The global Python has torch 2.10 (CPU). The venv starts clean, so no uninstall needed — just install directly.

Run:
```
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

Note: This is a large download (~2.5GB). The cu121 index may not have the absolute latest torch version — that's fine, WhisperX will work with whatever cu121 provides.

**Step 2: Verify CUDA support**

Run:
```
python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('CUDA version:', torch.version.cuda); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
```

Expected:
```
CUDA available: True
CUDA version: 12.1
Device: NVIDIA GeForce RTX 4070
```

If CUDA is False, something went wrong with the install. Check `pip show torch` to verify the version includes `+cu121`.

---

### Task 3: Install WhisperX and Pipeline Dependencies

**Step 1: Install WhisperX**

Run:
```
pip install whisperx
```

This pulls in pyannote.audio, transformers, and other ML dependencies. If it tries to downgrade torch to a CPU version, cancel and instead run:
```
pip install whisperx --no-deps
pip install pyannote.audio
```

**Step 2: Verify WhisperX imports cleanly**

Run:
```
python -c "import whisperx; print('WhisperX OK')"
```

Expected: `WhisperX OK` (no import errors).

**Step 3: Verify torch still has CUDA**

Run:
```
python -c "import torch; print('CUDA:', torch.cuda.is_available())"
```

Expected: `CUDA: True`. If False, WhisperX overwrote torch. Fix with:
```
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

**Step 4: Install recap in editable mode with all extras**

Run:
```
pip install -e ".[ml,todoist,dev]"
```

**Step 5: Install PyInstaller (needed later for sidecar rebuild)**

Run:
```
pip install pyinstaller
```

**Step 6: Verify the recap package loads**

Run:
```
python -m recap --help
```

Expected: Shows the CLI help with `process` and `retry-todoist` subcommands.

---

### Task 4: Locate Claude CLI and Verify It Works

The Claude CLI is installed via the Claude Desktop installer at `%APPDATA%/Claude/claude-code/<version>/claude.exe`. The Rust briefing code (`src-tauri/src/briefing.rs:278-311`) has auto-discovery logic we can reference.

**Step 1: Find the Claude CLI binary**

Run (PowerShell):
```
Get-ChildItem "$env:APPDATA\Claude\claude-code" -Directory | Sort-Object Name -Descending | Select-Object -First 1 | ForEach-Object { Join-Path $_.FullName "claude.exe" }
```

Expected: A path like `C:\Users\tim\AppData\Roaming\Claude\claude-code\0.2.79\claude.exe` (version number will vary).

**Step 2: Verify it runs**

Run (using the actual path from Step 1):
```
"C:\Users\tim\AppData\Roaming\Claude\claude-code\<version>\claude.exe" --version
```

Expected: Prints the Claude CLI version.

**Step 3: Record the path**

Save the full path — it goes into the test config.yaml as `claude.command` in Task 6.

---

### Task 5: HuggingFace Token Setup (User Action)

Pyannote's speaker diarization models are gated — they require accepting a license and providing an access token.

**Step 1: Accept the pyannote model license**

Open in browser: `https://huggingface.co/pyannote/speaker-diarization-3.1`

Click "Agree and access repository". You need a HuggingFace account (free).

Also accept: `https://huggingface.co/pyannote/segmentation-3.0`

**Step 2: Generate an access token**

Go to: `https://huggingface.co/settings/tokens`

Create a new token with at least `read` scope. Copy it.

**Step 3: Verify the token works**

Run:
```
set HUGGINGFACE_TOKEN=hf_your_token_here
python -c "from huggingface_hub import HfApi; api = HfApi(); api.whoami(token='hf_your_token_here'); print('Token OK')"
```

Note: If `huggingface_hub` isn't installed, run `pip install huggingface_hub` first (it should already be pulled in by pyannote.audio).

---

### Task 6: Create Test Fixtures

**Files:**
- Create: `tests/fixtures/test-metadata.json`
- Create: `tests/fixtures/config.yaml`
- Create: `tests/temp-vault/Work/Meetings/` (directory)
- Create: `tests/temp-vault/Work/People/` (directory)
- Create: `tests/temp-vault/Work/Companies/` (directory)

**Step 1: Create the temp vault directory structure**

Run:
```
mkdir -p tests/temp-vault/Work/Meetings tests/temp-vault/Work/People tests/temp-vault/Work/Companies
```

**Step 2: Create the test metadata file**

Create `tests/fixtures/test-metadata.json`:
```json
{
  "title": "Test Meeting",
  "date": "2026-03-25",
  "participants": [
    {"name": "Tim"},
    {"name": "Test Speaker"}
  ],
  "platform": "manual"
}
```

**Step 3: Create the test config.yaml**

Create `tests/fixtures/config.yaml` (replace `<CLAUDE_CLI_PATH>` with the path from Task 4):
```yaml
vault_path: "tests/temp-vault"
recordings_path: "tests/temp-recordings"
frames_path: "tests/temp-recordings/frames"
user_name: "Tim"

whisperx:
  model: "large-v3"
  device: "cuda"
  compute_type: "float16"
  language: "en"

claude:
  command: "<CLAUDE_CLI_PATH>"
  model: "sonnet"
```

Note: Use forward slashes in paths. The `recordings_path` is where the pipeline moves the audio file during processing — it will create this directory. No Todoist config needed for initial testing.

**Step 4: Create a test audio recording**

Record a short 2-3 minute audio file with two people talking (or yourself in two voices). Use any recording tool — Windows Voice Recorder, Audacity, or even a phone recording transferred over.

Save as `tests/fixtures/test-meeting.wav` (or `.mp3`, `.m4a` — WhisperX/ffmpeg handles all common formats).

The pipeline will move this file to `tests/temp-recordings/` during processing, so keep a backup copy if you want to re-run.

---

### Task 7: Run Pipeline — Transcribe Stage

This validates WhisperX + pyannote diarization with your GPU.

**Step 1: Activate the venv (if not already)**

Run:
```
.venv\Scripts\activate
```

**Step 2: Set the HuggingFace token**

Run:
```
set HUGGINGFACE_TOKEN=hf_your_token_here
```

**Step 3: Run the pipeline from the transcribe stage**

Run (from the repo root):
```
python -m recap process --config tests/fixtures/config.yaml --only transcribe tests/fixtures/test-meeting.wav tests/fixtures/test-metadata.json
```

Note: Using `--only transcribe` to test just this stage first. The pipeline will:
1. Move the audio file to `tests/temp-recordings/2026-03-25-test-meeting.wav`
2. Load the WhisperX model (first run downloads ~3GB of model weights)
3. Transcribe the audio
4. Run speaker diarization
5. Save `*.transcript.json` alongside the recording

Expected: Log output showing transcription progress, ending with "Transcription complete: N utterances".

**Step 4: Verify the transcript**

Check that `tests/temp-recordings/2026-03-25-test-meeting.transcript.json` exists and contains utterances with speaker labels and timestamps.

**Troubleshooting:**
- "CUDA out of memory": Try `compute_type: "int8"` in config.yaml
- "Could not download model": HuggingFace token issue — check Task 5
- Import errors: Check that WhisperX and pyannote.audio are installed in the venv

---

### Task 8: Run Pipeline — Analyze Stage

This validates Claude CLI integration.

**Step 1: Copy the audio back (the pipeline moved it)**

The previous run moved the test audio into `tests/temp-recordings/`. For `--only analyze`, the pipeline needs the transcript file that was already saved. But it still expects the audio path argument and will try to move it again.

The simplest approach: run the full pipeline from analyze stage forward:
```
python -m recap process --config tests/fixtures/config.yaml --from analyze tests/temp-recordings/2026-03-25-test-meeting.wav tests/fixtures/test-metadata.json
```

Wait — the audio was already moved in Task 7. The `--from analyze` flag means transcribe is skipped but the pipeline still runs `shutil.move()` on the audio path at line 190 of `pipeline.py`. This will fail if the file was already moved.

**Better approach:** Re-run from the beginning with a fresh copy of the test audio:
```
copy tests\fixtures\test-meeting-backup.wav tests\fixtures\test-meeting.wav
python -m recap process --config tests/fixtures/config.yaml tests/fixtures/test-meeting.wav tests/fixtures/test-metadata.json
```

This runs the full pipeline: transcribe → analyze → export. Since WhisperX models are cached from Task 7, transcription will be faster on the second run.

Expected:
- Transcription completes (cached models)
- "Running Claude analysis" log line
- Claude CLI produces JSON analysis
- Vault note written to `tests/temp-vault/Work/Meetings/2026-03-25 - Test Meeting.md`
- `status.json` shows all stages completed

**Step 2: Check the vault note**

Open `tests/temp-vault/Work/Meetings/2026-03-25 - Test Meeting.md` and verify it has:
- YAML frontmatter (date, participants, platform, etc.)
- Summary section
- Key points
- Action items (if any in the conversation)
- Transcript with speaker labels and timestamps

---

### Task 9: Rebuild Sidecar Binary

After validating the pipeline works standalone, rebuild the PyInstaller sidecar so the Tauri app can invoke it.

**Step 1: Ensure venv is active**

Run:
```
.venv\Scripts\activate
```

**Step 2: Build the sidecar**

Run:
```
python scripts/build-sidecar.py
```

This runs PyInstaller to bundle the entire Python environment (including WhisperX, torch, etc.) into a single `.exe` at `src-tauri/binaries/recap-pipeline-x86_64-pc-windows-msvc.exe`.

Warning: This is slow (several minutes) and the resulting binary is large (~2-4GB due to PyTorch + CUDA).

**Step 3: Verify the sidecar runs**

Run:
```
src-tauri\binaries\recap-pipeline-x86_64-pc-windows-msvc.exe --help
```

Expected: Same CLI help output as `python -m recap --help`.

---

### Task 10: Build and Launch Tauri App

**Step 1: Ensure npm dependencies are installed**

Run:
```
npm install
```

**Step 2: Launch in dev mode**

Run:
```
npm run tauri dev
```

Expected: The app builds (Rust compilation may take a few minutes on first run) and the Recap window appears with the onboarding wizard.

**Step 3: Complete onboarding**

- Set recordings folder to an SSD path (e.g., `C:\Users\tim\recap-data\recordings`)
- Set vault path to `tests/temp-vault` (the temp vault from Task 6 — use the absolute path)
- Configure Claude CLI path (from Task 4)
- Set your name

**Step 4: Verify the dashboard loads**

After onboarding, the dashboard should appear. If VITE_DUMMY_DATA is not set, it will show an empty state (no meetings yet).

---

### Task 11: Live Teams Meeting Test

Full automated flow: desktop Teams meeting → WASAPI detection → recording → pipeline → vault note.

**Step 1: Ensure the Tauri app is running**

From Task 10, the app should be running with `npm run tauri dev`.

**Step 2: Start a Teams meeting**

Open the desktop Teams app and start or join a meeting. The Recap recorder monitors WASAPI audio sessions for `Teams.exe` (see `src-tauri/src/recorder/monitor.rs:26`).

**Step 3: Verify recording starts**

The app's `RecordingStatusBar` should show that a meeting was detected and recording has started. The state machine flow is:
- `Idle` → `Detected` (WASAPI finds Teams.exe audio)
- `Detected` → `Recording` (capture begins: WASAPI audio + Graphics Capture screen)

**Step 4: Have a short conversation (2-3 minutes)**

Talk with at least one other person to generate meaningful transcript content.

**Step 5: End the meeting**

Leave the Teams call. The recorder should detect the audio session ending and transition:
- `Recording` → `Processing` (ffmpeg merge of audio + video streams)
- `Processing` → `Idle` (sidecar launch with the merged recording)

**Step 6: Wait for pipeline completion**

The pipeline runs as a sidecar. Watch the dashboard for pipeline status dots updating. Check the Tauri dev console for sidecar stdout/stderr.

**Step 7: Verify the vault note**

Check `tests/temp-vault/Work/Meetings/` for a new meeting note. Verify it contains the meeting title (from Teams window title or calendar match), transcript, and analysis.

---

### Task 12: Cleanup

**Step 1: Remove temp test data**

Run:
```
rm -rf tests/temp-vault tests/temp-recordings
```

**Step 2: Point app at real vault**

In the Recap app Settings, change the vault path from the temp vault to your real Obsidian vault: `C:\Users\tim\OneDrive\Documents\Tim's Vault`

**Step 3: Optionally commit test fixtures**

The test metadata and config templates in `tests/fixtures/` are useful to keep. The test audio file should stay gitignored (large binary). Add to `.gitignore` if needed:
```
tests/temp-vault/
tests/temp-recordings/
tests/fixtures/*.wav
tests/fixtures/*.mp3
tests/fixtures/*.m4a
```
