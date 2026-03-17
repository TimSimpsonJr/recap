# Recap — Structural Map

## Stack

- **Desktop app:** Tauri v2 (Rust backend) + Svelte 5 (plain, no SvelteKit) + Tailwind CSS 4
- **ML pipeline:** Python (Whisper large-v3, Pyannote 3.1)
- **AI analysis:** Claude Code CLI (subprocess)
- **Integrations:** Zoom, Google, Microsoft, Zoho, Todoist (OAuth flows)

## Structure

```
recap/
├── index.html                          # Vite entry point — loads src/main.ts
├── package.json                        # Node deps (Tauri plugins, Svelte, Tailwind)
├── vite.config.ts                      # Vite config — Svelte + Tailwind plugins
├── tsconfig.json                       # TypeScript config for plain Svelte
├── run_pipeline.py                     # PyInstaller entry point for sidecar
├── scripts/
│   └── build-sidecar.py                # Builds PyInstaller sidecar → src-tauri/binaries/
├── src/
│   ├── main.ts                         # Mounts App.svelte to #app
│   ├── app.css                         # Global CSS — Tailwind import
│   ├── App.svelte                      # Root: hash routing, store init, OAuth callback listener
│   ├── routes/
│   │   ├── Dashboard.svelte            # Placeholder (Phase 5)
│   │   └── Settings.svelte             # Full settings page — connections, vault, whisperx, etc.
│   └── lib/
│       ├── tauri.ts                    # Typed invoke() wrappers (OAuth, sidecar)
│       ├── stores/
│       │   ├── credentials.ts          # Stronghold-backed credential store (5 providers)
│       │   └── settings.ts             # tauri-plugin-store backed app settings
│       └── components/
│           ├── ProviderCard.svelte     # OAuth connection card (client ID/secret, connect/disconnect)
│           ├── SettingsSection.svelte  # Reusable section wrapper
│           ├── VaultSettings.svelte    # Vault path + folder config
│           ├── RecordingSettings.svelte # Recordings folder
│           ├── WhisperXSettings.svelte # Model, device, compute type, language
│           ├── TodoistSettings.svelte  # Project + labels
│           ├── GeneralSettings.svelte  # Autostart (disabled), notifications
│           └── AboutSection.svelte     # Version + sidecar status
├── src-tauri/
│   ├── Cargo.toml                      # Rust deps: tauri plugins, reqwest, tokio, serde, uuid, open
│   ├── tauri.conf.json                 # App config: deep-link, sidecar, window (hidden on start)
│   ├── build.rs                        # Tauri build script
│   ├── capabilities/
│   │   └── default.json                # Permissions: core, stronghold, store, deep-link, autostart, shell, dialog
│   ├── icons/                          # App icons
│   └── src/
│       ├── main.rs                     # Entry point → recap_lib::run()
│       ├── lib.rs                      # Tauri builder: plugins, tray, deep links, IPC commands
│       ├── tray.rs                     # System tray menu + left-click handler
│       ├── deep_link.rs                # recap:// URL handler, emits oauth-callback events
│       ├── credentials.rs              # Provider types + placeholder IPC commands
│       ├── oauth.rs                    # 5-provider OAuth: auth URLs, token exchange, localhost server
│       └── sidecar.rs                  # Pipeline sidecar invocation + status check
├── recap/                              # Python pipeline (unchanged)
│   ├── cli.py                          # CLI entry point
│   ├── pipeline.py                     # Orchestrates transcription → analysis → output
│   ├── config.py                       # YAML config loader
│   ├── transcription.py                # WhisperX + Pyannote
│   ├── analysis.py                     # Claude Code CLI invocation
│   ├── output.py                       # Markdown + Todoist output
│   └── todoist_client.py               # Todoist API client
├── tests/                              # Python tests
├── prompts/                            # Claude prompt templates
└── docs/plans/                         # Design docs and implementation plans
```

## Key Relationships

- `App.svelte` initializes credential/settings stores on mount, listens for `oauth-callback` events from Rust
- `lib.rs` registers all plugins in `.setup()`, creates tray, sets up deep links, hides window on start
- `deep_link.rs` emits `oauth-callback` event → `App.svelte` catches it → calls `exchange_oauth_code` IPC → saves tokens via Stronghold
- `oauth.rs` `start_oauth` command opens browser; for Google/Microsoft, spawns localhost server to catch redirect
- `credentials.ts` store wraps Stronghold JS API; `settings.ts` wraps tauri-plugin-store
- `ProviderCard.svelte` reads from credential store, calls `startOAuth` IPC to begin flow
- `scripts/build-sidecar.py` → PyInstaller → `src-tauri/binaries/recap-pipeline-{triple}.exe`
- `sidecar.rs` invokes the binary via `tauri-plugin-shell` sidecar API
- Window close → hide (not quit); quit only via tray menu
