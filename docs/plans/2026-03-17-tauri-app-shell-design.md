# Phase 3: Tauri App Shell — Design Doc

## Goal

Background desktop app with system tray, global hotkeys registration, URL protocol handling, OAuth flows for all five platforms, encrypted credential storage, and a settings UI. The Python pipeline from Phase 2 is bundled as a sidecar binary.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Monorepo expansion (single crate) | Natural fit — Tauri scaffolds into existing repo. Platform modules are thin enough for Rust modules, not separate crates. |
| Frontend framework | Svelte | Lightweight, great Tauri community adoption, good fit for forms/lists/status UI. Svelte + vidstack handles future video playback. |
| Credential storage | Tauri Stronghold | OS-level encrypted vault. Right default for distributable app. |
| Non-secret storage | tauri-plugin-store | Plain JSON in AppData for settings like vault path, folder names. |
| Python integration | Sidecar (PyInstaller) | Self-contained binary bundled with the app. No Python install required for friends. |
| OAuth credentials | User-provided | No hardcoded client IDs/secrets. Each user registers their own developer apps and enters credentials in settings. |
| OAuth redirects | Hybrid | Deep links (`recap://`) for Zoom, Zoho, Todoist. Localhost HTTP server for Google and Microsoft (custom protocols not supported). |

## Project Structure

```
recap/
├── recap/                ← existing Python pipeline (unchanged)
├── tests/                ← existing Python tests (unchanged)
├── prompts/              ← existing prompt templates (unchanged)
├── pyproject.toml        ← existing
├── src-tauri/            ← Rust backend
│   ├── Cargo.toml
│   ├── tauri.conf.json   ← app config, window settings, sidecar declaration, deep link protocol
│   ├── capabilities/     ← per-window permission files
│   ├── icons/            ← app + tray icons
│   ├── binaries/         ← PyInstaller sidecar output (gitignored)
│   └── src/
│       ├── main.rs       ← Tauri app setup, plugin registration
│       ├── tray.rs       ← system tray icon + menu
│       ├── commands.rs   ← Tauri IPC commands (invoked from Svelte)
│       ├── oauth.rs      ← OAuth flow handling (token exchange, refresh, localhost server)
│       └── sidecar.rs    ← Python pipeline sidecar management
├── src/                  ← Svelte frontend
│   ├── App.svelte        ← root component, routing
│   ├── main.ts           ← Svelte mount point
│   ├── lib/
│   │   ├── components/   ← reusable UI components
│   │   ├── stores/       ← Svelte stores (credentials state, settings)
│   │   └── tauri.ts      ← typed wrappers around invoke() calls
│   └── routes/
│       ├── Settings.svelte
│       └── Dashboard.svelte  ← placeholder for Phase 5
├── scripts/
│   └── build-sidecar.py  ← PyInstaller build script → src-tauri/binaries/
├── package.json          ← Svelte, Vite, Tauri CLI, Tailwind
├── vite.config.ts
├── svelte.config.js
└── tailwind.config.js
```

## Build Chain

`npm run tauri dev` runs two things in parallel:
1. **Vite dev server** — compiles Svelte + Tailwind, serves on localhost with hot reload
2. **Cargo build** — compiles Rust backend, opens a webview window pointed at Vite

`npm run tauri build` produces a `.msi` installer with the app + sidecar binary bundled.

Sidecar build is a separate step: `python scripts/build-sidecar.py` runs PyInstaller and places the output in `src-tauri/binaries/`.

## System Tray

**Menu (right-click):**
- Start Recording — disabled in Phase 3
- Stop Recording — disabled in Phase 3
- ───────────
- Open Dashboard — brings main window to front / creates it
- Settings — opens settings page
- ───────────
- Quit — exits app, cleans up resources

**Behavior:**
- Left-click on tray icon → opens/focuses the dashboard window
- App starts minimized to tray (no window on launch)
- Closing the window hides to tray, does not quit
- Quit only via tray menu

**Tray icon states:** Idle (default). Recording (red dot overlay) and processing (spinner) states added when recording is wired up in later phases.

**Autostart:** `tauri-plugin-autostart` is included and configured but disabled. Enabled as one of the final steps when the full app is assembled.

## Deep Links

**Protocol:** `recap://` registered in `tauri.conf.json`.

**Routes:**
- `recap://oauth/{provider}/callback?code=...` — OAuth redirect (Zoom, Zoho, Todoist)
- `recap://meeting/start?url=...` — future: trigger recording from a meeting link (Phase 4+)

**Edge case:** If app isn't running when a deep link fires, Windows launches it with the URL as an argument. Tauri handles this automatically.

## OAuth & Credential Storage

### Five OAuth Flows

| Provider | Redirect method | Phase 3 scopes |
|----------|----------------|----------------|
| Zoom | Deep link (`recap://oauth/zoom/callback`) | `meeting:read`, `recording:read`, `user:read` |
| Google | Localhost HTTP server | `calendar.readonly`, `meetings.space.readonly` |
| Microsoft | Localhost HTTP server | `OnlineMeetings.Read`, `User.Read` |
| Zoho | Deep link (`recap://oauth/zoho/callback`) | `ZohoMeeting.manageOrg.READ`, `ZohoCalendar.calendar.READ` |
| Todoist | Deep link (`recap://oauth/todoist/callback`) | `data:read_write` |

### Flow (all providers)

1. User enters client ID + client secret in settings (required before Connect is enabled)
2. User clicks "Connect [Provider]"
3. Rust opens system browser to provider's authorization URL
4. Provider redirects to deep link or localhost server
5. Rust extracts auth code, exchanges for access + refresh tokens
6. Tokens stored in Stronghold
7. Settings page updates to show "Connected as [name/email]"

### Localhost server (Google, Microsoft)

Rust spins up a temporary HTTP server on a random port for the OAuth redirect. Server listens for a single request, extracts the auth code, shuts down, and passes the code to the token exchange logic.

### Token refresh

Background task checks token expiry periodically. Provider-specific lifetimes:
- Zoom: 1hr access, long-lived refresh
- Google: 1hr access, long-lived refresh
- Microsoft: 1hr access, 90-day refresh (inactive refresh tokens expire)
- Zoho: 1hr access, long-lived refresh
- Todoist: no expiry on access token

If refresh fails (token revoked or expired), settings page shows "Reconnect required."

### Stronghold structure

```
stronghold vault
├── {provider}.client_id
├── {provider}.client_secret
├── {provider}.access_token
├── {provider}.refresh_token
└── ... (for each of: zoom, google, microsoft, zoho, todoist)
```

### Notes

- **Google unverified app warning:** Until app verification (requires privacy policy, homepage), users see a "This app isn't verified" interstitial. Click through via Advanced → Go to Recap.
- **Zoho regional endpoints:** OAuth endpoints differ by data center (.com, .eu, .in, .com.au). Settings include a region selector for Zoho.
- **Microsoft account tier:** After connecting, detect personal vs business via Graph `/me` endpoint. Show note on personal accounts: "Personal account — recording will require manual start."

## Sidecar (Python Pipeline)

**Packaging:** PyInstaller bundles `python -m recap` into `recap-pipeline.exe`, including Python interpreter and all dependencies.

**Build script:** `scripts/build-sidecar.py` runs PyInstaller and copies output to `src-tauri/binaries/recap-pipeline.exe`.

**Tauri declaration** in `tauri.conf.json`:
```json
{
  "bundle": {
    "externalBin": ["binaries/recap-pipeline"]
  }
}
```

**Rust invocation:**
```rust
Command::new_sidecar("recap-pipeline")
    .args(["process", "--config", &config_path, &recording_path])
    .spawn()
```

**Phase 3 scope:** Infrastructure only — build script, sidecar declaration, Rust wrapper. Actual triggering (meeting ends → run pipeline) is Phase 4.

**Size note:** WhisperX + PyTorch + CUDA makes the sidecar ~2-3GB. Fine for local use. Friends need an NVIDIA GPU.

## Settings Page

### Platform Connections

One card per provider:
- Client ID field
- Client Secret field
- Connect / Disconnect button (Connect disabled until credentials entered)
- Status: Disconnected / Connected as [name] / Reconnect required
- Zoho: additional region dropdown
- Microsoft: account tier note after connecting

### Vault Settings

- Vault path (with native Browse dialog)
- Meetings folder (relative to vault, default: `Work/Meetings`)
- People folder (default: `Work/People`)
- Companies folder (default: `Work/Companies`)

### Recording Settings

- Recordings folder (with Browse dialog)
- Placeholder section — more options in later phases

### WhisperX Settings

- Model: dropdown (large-v3, medium, small, base, tiny)
- Device: dropdown (cuda, cpu)
- Compute type: dropdown (float16, int8, float32)
- Language: text input (default: en)

### Todoist Settings

- Project: text input or dropdown (fetched from Todoist API after connecting)
- Default labels: text input

### General

- Start on login: checkbox (disabled, enabled in final phase)
- Show notification when processing complete: checkbox

### About / Diagnostics

- Version number
- Sidecar status (found / not found)
- GPU detection (CUDA available / not available, device name)
- Log viewer (expandable, shows recent pipeline output)

### Storage

- Non-secret settings (vault path, folders, WhisperX config, Todoist project): `tauri-plugin-store` → plain JSON in AppData
- All credentials (client IDs, secrets, tokens): Stronghold
- Existing `config.yaml` is read-only fallback — Tauri settings take precedence, `config.yaml` values used as defaults on first run

## Open Questions (Future Phases)

### Recording capture strategy for non-Zoom platforms

PLAN.md assumes Zoom uses its cloud recording API, and other platforms (Teams personal, Google Meet, Zoho Meet) use "URL intercept + manual start." But the plan never specifies what "manual start" captures audio *from*. The two options are:

1. **Local audio capture (WASAPI / virtual audio cable)** — capture system audio directly from Windows
2. **Screen/window recording** — capture the meeting window (video + audio) via Windows screen capture APIs

PLAN.md defers local audio capture to Phase 9 (Signal/Discord), but non-Zoom platforms would need it earlier to be functional. This is a dependency gap to resolve when planning Phase 4+.
