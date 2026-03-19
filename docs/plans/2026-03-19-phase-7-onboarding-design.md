# Phase 7: Onboarding Flow — Design

## Overview

First-run experience that walks new users through required configuration, then provides an inline checklist for optional integrations. Hybrid approach: full-screen wizard for blocking steps, then dashboard with dismissible checklist for the rest.

## Onboarding State & Detection

### New settings fields

| Field | Type | Default | Purpose |
|---|---|---|---|
| `onboardingComplete` | `boolean` | `false` | Gates full-screen wizard |
| `userName` | `string` | `""` | Pipeline config — user identity |
| `claudeModel` | `string` | `"sonnet"` | Model passed to `claude --model` |
| `claudeCommand` | `string` | `"claude"` | Path to Claude CLI executable |
| `todoistProjectMap` | `Record<string, string>` | `{}` | Meeting type → Todoist project routing |

### Derived / hardcoded

- `framesPath` — auto-derived as `{recordingsFolder}/frames`
- `claude.command` default — `"claude"` (configurable via `claudeCommand`)

### Session-only state

- `onboardingDismissed` — `$state(false)` in Dashboard, resets each app launch

### Secrets (Stronghold + env vars)

- HuggingFace token → stored in Stronghold, passed to sidecar as `HUGGINGFACE_TOKEN`
- Todoist API token → stored in Stronghold, passed to sidecar as `TODOIST_API_TOKEN`

### Detection flow

1. `App.svelte` checks `onboardingComplete` after loading settings/credentials
2. `false` → render `Onboarding.svelte` full-screen (no nav bar)
3. `true` → normal app; Dashboard shows inline checklist if optional steps remain and not dismissed this session

## Full-Screen Wizard

Four screens, linear with back/next navigation:

### Step 1: Welcome

- "Welcome to Recap" heading with brief tagline
- Single "Get Started" button

### Step 2: Storage

- Recordings directory picker with SSD warning (reuse HDD detection from RecordingSettings)
- User name text input
- "Next" blocked until both fields are filled

### Step 3: Vault

- Obsidian vault path picker
- Preview of default subfolder structure: Meetings/, People/, Companies/
- "Next" blocked until path is filled

### Step 4: Pipeline

- HuggingFace token — password-masked input, link to HF token page, explanation ("Required for speaker diarization — Pyannote models are gated on HuggingFace")
- Claude CLI path — text input, pre-filled with `"claude"`
- Claude model — dropdown selector (haiku / sonnet / opus)
- "Finish" blocked until HF token is filled

### On finish

- Save all values to settings store
- Save HF token to Stronghold
- Set `onboardingComplete = true`
- Transition to dashboard (which shows inline checklist)

## Inline Checklist

### Component

`SetupChecklist.svelte` — rendered at the top of Dashboard between search bar and meeting list.

### Items

| Item | Completion check | Action |
|---|---|---|
| Connect Zoom | `$credentials.zoom` has tokens | Open provider modal |
| Connect Google | `$credentials.google` has tokens | Open provider modal |
| Connect Microsoft Teams | `$credentials.microsoft` has tokens | Open provider modal |
| Connect Zoho | `$credentials.zoho` has tokens | Open provider modal |
| Connect Todoist | `$credentials.todoist` has tokens | Open provider modal |
| Install browser extension | `extensionInstalled` setting | Manual "Done" dismiss (persisted) |

### Behavior

- Each item shows a checkmark when complete, a "Connect" / "Install" button when not
- Clicking "Connect" opens the same `Modal` + `ProviderCard` used by Settings
- Dismiss X button hides the checklist for the current session
- Reappears on next launch if any items are still incomplete (nags once per launch)
- Auto-hides permanently when all items are connected/dismissed
- "Install browser extension" links to extension folder / Chrome extensions page, with manual "Done" button that persists `extensionInstalled = true` in settings

## Config.yaml Generation

Rust generates `config.yaml` in the recordings root directory before spawning the sidecar. Assembled from settings store values:

```yaml
vault_path: {vaultPath}
recordings_path: {recordingsFolder}
frames_path: {recordingsFolder}/frames
user_name: {userName}

whisperx:
  model: {whisperxModel}
  device: {whisperxDevice}
  compute_type: {whisperxComputeType}
  language: {whisperxLanguage}

claude:
  command: {claudeCommand}
  model: {claudeModel}

todoist:
  default_project: {todoistProject}
  labels: {todoistLabels}
  project_map: {todoistProjectMap}
```

Secrets are NOT written to the file. Passed as environment variables when Rust spawns the sidecar:
- `HUGGINGFACE_TOKEN`
- `TODOIST_API_TOKEN`

Pipeline's `config.py` updated to read these env vars with fallback to yaml fields (supports manual CLI runs with a hand-written config).

## Settings Integration

### New sections / fields in Settings page

- **Claude section** (new) — model dropdown (haiku/sonnet/opus) + CLI path input
- **WhisperX section** — add HuggingFace token (password-masked, reads/writes Stronghold)
- **Todoist section** — add project map key-value editor
- **General section** — add "Re-run setup wizard" button

### Re-run behavior

- Sets `onboardingComplete = false`
- App immediately shows the full-screen wizard
- All fields pre-filled with current values so user can adjust, not re-enter

## Validation

### Full-screen wizard (per step)

- **Storage**: recordings dir must be valid path (SSD warning on HDD), user name non-empty. Block "Next" until filled.
- **Vault**: vault path must be valid path. Block "Next" until filled.
- **Pipeline**: HF token non-empty, Claude CLI path non-empty (pre-filled), model always has value. Block "Finish" until HF token filled.

### No deep validation

Paths are not checked for existence (user may create them later). Tokens are not validated against APIs. If something is wrong, the pipeline surfaces actionable errors at the relevant stage, which is retryable.

## Actionable Pipeline Errors

Wrap each pipeline stage's entry point with try/except for known failure modes. Map to clear, actionable messages written to `status.json`. Fall through to raw error text for unexpected exceptions. The frontend already displays these via `PipelineDots`.

### Transcription stage

| Failure | Message |
|---|---|
| HF token invalid/missing | "HuggingFace authentication failed — check your token in Settings > WhisperX" |
| CUDA unavailable | "CUDA not available — check GPU drivers or switch device to 'cpu' in Settings > WhisperX" |
| Out of GPU memory | "GPU out of memory — try a smaller model (e.g., 'medium') in Settings > WhisperX" |
| Model download fails | "Failed to download WhisperX model — check your internet connection and HuggingFace token" |
| Audio file missing/corrupt | "Audio file not found or unreadable — recording may be incomplete" |

### Analysis stage

| Failure | Message |
|---|---|
| Claude CLI not found | "Claude CLI not found at '{command}' — update the path in Settings > Claude" |
| Claude CLI auth error | "Claude analysis failed — check Claude CLI is authenticated (run 'claude' in a terminal)" |
| Rate limited | "Claude rate limited — wait a few minutes and retry" |
| Output parse failure | "Claude returned unexpected output — retry (transient) or check prompt template" |
| Prompt template missing | "Prompt template not found at {path} — check Recap installation" |

### Export stage

| Failure | Message |
|---|---|
| Vault path missing | "Vault path does not exist — update it in Settings > Vault" |
| Write permission error | "Cannot write to vault — check folder permissions for {path}" |

### Todoist stage

| Failure | Message |
|---|---|
| Invalid token | "Todoist authentication failed — reconnect in Settings > Todoist" |

### Frames stage

| Failure | Message |
|---|---|
| ffmpeg not found | "ffmpeg not found — ensure ffmpeg is installed and on system PATH" |
| Video file missing | "Recording file not found — it may have been moved or deleted" |

### Any stage

| Failure | Message |
|---|---|
| Disk full | "Disk full — free space on {drive} and retry" |
| Recordings path missing | "Recordings directory not found — update it in Settings > Recording" |
