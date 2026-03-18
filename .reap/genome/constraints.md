# Project Constraints

- **Python ≥ 3.10** — required by WhisperX and type hint syntax
- **Tauri v2** — locked to v2 APIs (plugin system, IPC, Stronghold, deep-link)
- **Svelte 5 (runes syntax)** — uses `$state`, `$derived`, `$effect` — not Svelte 4 reactive declarations
- **Tailwind CSS 4** — new config approach (CSS-based, not tailwind.config.js); don't use v3 patterns
- **TypeScript ~5.6**
- **Windows-first** — WASAPI audio capture + Graphics Capture API are Windows-only; cross-platform is not a current goal
- **NVIDIA GPU assumed for recording** — ffmpeg H.265 NVENC encoding; no software fallback
- **SSD required for multi-stream capture** — simultaneous audio + screen recording needs SSD throughput
- **No cloud storage of user data** — recordings, transcripts, and analysis artifacts stay local
- **PyTorch CUDA 12.1** — extra-index-url pinned to cu121 wheels
- **Obsidian vault compatibility** — generated notes must be valid Obsidian markdown (wikilinks, callouts, YAML frontmatter). Not generic markdown.
- **Claude CLI for LLM calls** — all LLM interactions use the `claude` CLI (`claude --print`), not the Anthropic API SDK. This keeps auth/config centralized in the CLI and avoids managing API keys in the app.
