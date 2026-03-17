# Recap — Structural Map

## Stack

- **Desktop app:** Tauri v2 (Rust backend) + Svelte 5 (plain, no SvelteKit) + Tailwind CSS 4
- **ML pipeline:** Python (Whisper large-v3, Pyannote 3.1)
- **AI analysis:** Claude Code CLI (subprocess)
- **Integrations:** Zoom API, Todoist API, Zoho Calendar API

## Structure

```
recap/
├── .gitignore                          # Git ignore rules for Tauri, Node, Python, recordings
├── MANIFEST.md                         # This file — structural map
├── PLAN.md                             # Full implementation plan with architecture, phases, and decisions
├── index.html                          # Vite entry point — loads src/main.ts
├── package.json                        # Node dependencies (Tauri plugins, Svelte, Tailwind)
├── vite.config.ts                      # Vite config — Svelte + Tailwind plugins, Tauri dev server
├── tsconfig.json                       # TypeScript config for plain Svelte
├── src/
│   ├── main.ts                         # App entry point — mounts App.svelte to #app
│   ├── app.css                         # Global CSS — Tailwind import
│   └── App.svelte                      # Root component (placeholder)
├── static/                             # Static assets (favicon, SVG logos)
└── src-tauri/
    ├── Cargo.toml                      # Rust deps: Tauri plugins, reqwest, tokio, serde
    ├── tauri.conf.json                 # App config: identifier, deep-link scheme, window settings
    ├── build.rs                        # Tauri build script
    ├── capabilities/
    │   └── default.json                # Permissions: core, stronghold, store, deep-link, autostart, shell
    ├── icons/                          # App icons (all platforms)
    └── src/
        ├── main.rs                     # Entry point — calls recap_lib::run()
        └── lib.rs                      # Tauri builder setup with plugin registration
```

## Key Relationships

- `vite.config.ts` uses plain `svelte()` plugin; Vite builds to `dist/`
- `src-tauri/tauri.conf.json` points `frontendDist` to `../dist` (Vite output)
- `index.html` at repo root is Vite's HTML entry, loads `src/main.ts`
- `src-tauri/Cargo.toml` lib name is `recap_lib`, referenced by `main.rs`
- Deep-link scheme `recap://` configured in `tauri.conf.json` plugins section
- PLAN.md references tech stack decisions tracked in `~/.claude/projects/.../memory/meeting-tool-tech-stack.md`
- Vault output targets `Tim's Vault/Work/Meetings/`, `Work/People/`, `Work/Companies/`
