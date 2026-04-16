# Project Constraints

- **Python ≥ 3.10** — required by NeMo and type-hint syntax used across the codebase.
- **Windows-first** — WASAPI loopback audio capture (PyAudioWPatch) and DPAPI credential storage are Windows-only; cross-platform is not a current goal.
- **NVIDIA GPU with CUDA 12.6** — required for Parakeet ASR + NeMo Sortformer diarization. RTX 4070 (12 GB VRAM) is the reference machine.
- **PyTorch CUDA 12.6** — `extra-index-url` pinned to `https://download.pytorch.org/whl/cu126` in `pyproject.toml`.
- **SSD required for recordings** — simultaneous audio capture + pipeline I/O needs SSD throughput.
- **ffmpeg on PATH** — required for AAC conversion and speaker clip extraction.
- **No cloud storage of user data** — recordings, transcripts, and analysis artifacts stay local. Vault notes go straight to the user's Obsidian vault.
- **Obsidian vault compatibility** — generated notes must be valid Obsidian markdown (wikilinks, callouts, YAML frontmatter). Not generic markdown.
- **Obsidian plugin TypeScript** — compiles via esbuild; `npm run build` must emit zero `tsc -noEmit` errors.
- **Chrome/Edge MV3 extension** — pure JavaScript, no build step. MV3 service worker constraints apply: no `setInterval` (use `chrome.alarms`); handle wake-up races with an `authReady` promise.
- **Claude CLI for LLM calls (personal use)** — all LLM interactions go through `claude --print` or `ollama run`. Claude CLI usage is permitted under Consumer ToS for personal use on your own machine. If Recap is ever distributed to other users, switch to Anthropic API keys under Commercial Terms. Ollama is the local-inference alternative and is already wired in as a per-org backend.
- **Loopback-only pairing** — `/bootstrap/token` only accepts connections from `127.0.0.1`; extension pairing validates the loopback URL before exchanging the token.
- **Bearer on every `/api/*` except bootstrap** — no unauthenticated mutations. A 401 must clear the caller's stored token.
