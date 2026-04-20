# Handoff — Scenario 1 step 2: meeting detection → auto-record

**Date:** 2026-04-20
**Branch:** `obsidian-pivot`
**Previous handoff:** `docs/handoffs/2026-04-15-final-integration-pass.md` (Final Integration Pass scenarios)

## Goal

Verify the golden path from "user joins a meeting" through to "daemon is recording the right audio, to the right file, under the right org." This is step 2 of Scenario 1. Step 1 (calendar sync → stub note) is confirmed working as of this session.

## What is already working (verified today)

- **Launcher-wrapped daemon** with one-click restart from the plugin settings. Start the daemon via `uv run python -m recap.launcher config.yaml`. The plugin's "Restart daemon" button (Settings → Recap → Daemon lifecycle) shuts the child down and the launcher respawns it; full restart takes ~1s after the WebSocket-close + `shutdown_timeout=5.0` fix.
- **Zoho + Google calendar sync.** As of 14:14 local, the scheduler pulled 7 events from Zoho and wrote stub notes under `C:/Users/tim/recap-test-vault/Disbursecloud/Meetings/`. OAuth now requests `access_type=offline` + `prompt=consent` and the Zoho scope is `ZohoCalendar.calendar.ALL,ZohoCalendar.event.ALL`.
- **Plugin is deployed** at `C:/Users/tim/recap-test-vault/.obsidian/plugins/recap/` with today's `main.js` + `styles.css`. Settings show the Restart button enabled.

## The test

1. User joins a live meeting — Teams, Zoom, or Google Meet in their browser (Chrome/Edge with the Recap MV3 extension installed and paired).
2. Browser extension detects the meeting URL and fires a signal to the daemon.
3. Daemon's `MeetingDetector` routes the signal based on `config.yaml → detection.<platform>.behavior` (`auto-record` for Teams/Zoom in the current config).
4. Daemon transitions `Recorder` to `recording` state, opens audio capture on the default loopback + mic, and begins writing `.flac` to `C:/Users/tim/recap-test-data/recordings/`.
5. Plugin sidebar reflects "Recording (<org>)" state via WebSocket `state_change` frame.

## What to watch for in the logs

Tail `C:/Users/tim/recap-test-vault/_Recap/.recap/logs/recap.log` while the user joins the meeting. Expected sequence (approximate messages):

- `Meeting detected: <platform> <url>` or similar detector log.
- `Recorder starting capture for org: <org>`
- `AudioCapture opened: rate=48000 channels=<n>`
- `Recording file: C:\Users\tim\recap-test-data\recordings\<timestamp>-<org>.flac`

## Most likely failure modes

- **Extension not paired / not firing.** Check the extension's own console. If no `/api/meeting-detected` POST hits the daemon, nothing downstream will happen. Pairing lives under Settings → Recap → Pair browser extension… which invokes `daemon.pairing.open()` and hands the extension a token via `/bootstrap/token`.
- **Detection routed to `prompt` behavior.** If `config.yaml` has `auto-record` but the code path still prompts, check `recap/daemon/recorder/detection.py` for routing logic. The signal popup path is what handles prompt-mode.
- **Audio hardware mismatch.** Prior session proved the `maxInputChannels` auto-detect works for the user's Realtek loopback + Fifine mic (both 2-channel). If new hardware was plugged in, the pump's stereo→mono downmix needs to kick in; watch for `-9996 Invalid device` errors on stream open. Fix landed in commit `fcbb9bf`.
- **Zoho event-id mismatch / no arm-ahead.** The scheduler writes a `rename-queue` entry when it sees a matching calendar event, so the stub note gets renamed to the actual recording stem when the pipeline completes. If the meeting URL doesn't match any synced event, the recording still happens under an auto-generated stem — the rename step just doesn't fire. This is Scenario 3 territory, not a step-2 failure.

## Key files / code paths

- `recap/daemon/recorder/detector.py` — `MeetingDetector.handle_signal()` is the entry point from the extension.
- `recap/daemon/recorder/detection.py` — routes auto-record vs prompt based on config.
- `recap/daemon/recorder/recorder.py` — `Recorder.start(org)` opens the audio pipeline.
- `recap/daemon/recorder/audio.py` — `_SourceStream` + pump + resample chain. Loopback uses PyAudioWPatch's `get_default_wasapi_loopback`, mic uses `get_default_wasapi_device(d_in=True)`.
- Plugin `obsidian-recap/src/views/MeetingListView.ts` — listens for `state_change` WebSocket frames and updates the status row.
- Browser extension — lives outside this repo; paired via the Obsidian plugin's pair button.

## Today's remaining work (post step 2)

- **Scenario 1 step 3** — confirm the pipeline runs to completion after stop: transcription, diarization, speaker stubs, canonical note write, stub rename.
- **Scenario 3** — rename queue behavior when an in-flight recording matches a pre-existing calendar stub.
- **Three-tab Meetings sidebar redesign** — design + implementation plan committed this session (`docs/plans/2026-04-20-meetings-tabs-design.md` + `-implementation.md`). Plan is 9 tasks, TDD-first. Codex is reviewing the plan before execution starts.

## Session state at handoff

- All local tests passing: `uv run pytest` shows 680 / 680.
- `git status` shows only `.claude/settings.local.json` modified plus `docs/mockups/` (preview stub) and `launcher.log` (gitignored).
- Today's commits on `obsidian-pivot`: launcher + restart button, daemon shutdown profiler, WebSocket close on shutdown, Zoho offline+scope fix, OAuth scope logging, Meetings redesign design doc, Meetings redesign implementation plan.

## Quick restart recipe (if picking this up cold)

1. `cd C:/Users/tim/OneDrive/Documents/Projects/recap`
2. `uv run python -m recap.launcher config.yaml`
3. Open Obsidian. Settings → Recap → confirm "Zoho Calendar: Connected" and "Google Calendar: Connected". Restart button should be enabled.
4. Tail the log: `tail -f /c/Users/tim/recap-test-vault/_Recap/.recap/logs/recap.log`
5. Join the meeting and watch for the detector → recorder sequence above.
