# Phase 0: Repo Cleanup

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a clean starting point by removing Tauri/Svelte code, closing stale issues, and establishing the feature branch.

**Architecture:** This is pure cleanup. No new functionality. The repo should end this phase with only the Python pipeline code, tests, prompts, docs, and browser extension remaining.

**Tech Stack:** Git, GitHub CLI

---

### Task 1: Create feature branch

**Files:**
- None (git operations only)

**Step 1: Create and push the obsidian-pivot branch**

```bash
git checkout -b obsidian-pivot
git push -u origin obsidian-pivot
```

**Step 2: Verify branch**

```bash
git branch --show-current
```

Expected: `obsidian-pivot`

---

### Task 2: Close stale Tauri-era issues

**Step 1: List all open issues**

```bash
gh issue list --state open
```

**Step 2: Close each Tauri-era issue (1-24) with a note**

For each open issue in the 1-24 range:

```bash
gh issue close <NUMBER> --comment "Closing: Tauri app replaced by Obsidian plugin architecture. See docs/plans/2026-04-13-obsidian-plugin-architecture.md"
```

Do NOT close issue #25 (iPhone recording ingest) — that carries forward.

**Step 3: Verify only #25 and newer remain open**

```bash
gh issue list --state open
```

---

### Task 3: Remove Tauri/Rust code

**Files:**
- Delete: `src-tauri/` (entire directory)
- Delete: `src/` (entire Svelte frontend directory)
- Delete: `scripts/build-sidecar.py`

**Step 1: Remove directories and files**

```bash
rm -rf src-tauri/ src/ scripts/build-sidecar.py
```

**Step 2: Verify removal**

```bash
ls src-tauri/ 2>/dev/null && echo "STILL EXISTS" || echo "REMOVED"
ls src/ 2>/dev/null && echo "STILL EXISTS" || echo "REMOVED"
ls scripts/build-sidecar.py 2>/dev/null && echo "STILL EXISTS" || echo "REMOVED"
```

Expected: all three print "REMOVED"

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove Tauri/Rust backend and Svelte frontend

Replaced by Python daemon + Obsidian plugin architecture.
See docs/plans/2026-04-13-obsidian-plugin-architecture.md"
```

---

### Task 4: Remove dropped Python modules

**Files:**
- Delete: `recap/frames.py`
- Delete: `recap/todoist.py`
- Delete: `prompts/participant_extraction.md`
- Delete: `tests/test_frames.py`
- Delete: `tests/test_todoist.py`

**Step 1: Remove files**

```bash
rm -f recap/frames.py recap/todoist.py prompts/participant_extraction.md
rm -f tests/test_frames.py tests/test_todoist.py
```

**Step 2: Remove WhisperX/Pyannote/Todoist from pyproject.toml**

Edit `pyproject.toml` — remove the `ml` and `todoist` optional dependency groups and the WhisperX/todoist-api-python entries. Keep the `dev` group.

The dependencies section should end up as:

```toml
[project]
name = "recap"
version = "0.2.0"
description = "Meeting recording → transcription → analysis → Obsidian vault notes"
requires-python = ">=3.10"
dependencies = [
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

Bump version to 0.2.0 to mark the architecture change.

**Step 3: Remove whisperx import from transcribe.py**

Delete `recap/transcribe.py` entirely — it will be rewritten in Phase 3.

```bash
rm -f recap/transcribe.py tests/test_transcribe.py
```

**Step 4: Verify remaining Python structure**

```bash
ls recap/
```

Expected: `__init__.py`, `__main__.py`, `analyze.py`, `cli.py`, `config.py`, `errors.py`, `models.py`, `pipeline.py`, `vault.py`

**Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove dropped modules (frames, todoist, whisperx, transcribe)

Audio-only pipeline: no video frames, no Todoist sync.
Transcription will be rewritten for Parakeet in Phase 3."
```

---

### Task 5: Remove frontend dependencies

**Files:**
- Delete: `package.json`
- Delete: `package-lock.json` (if exists)
- Delete: `tsconfig.json`
- Delete: `tsconfig.node.json` (if exists)
- Delete: `vite.config.ts` (if exists)
- Delete: `tailwind.config.*` (if exists)
- Delete: `postcss.config.*` (if exists)
- Delete: `index.html` (if exists)
- Delete: `node_modules/` (if exists)
- Delete: `.npmrc` (if exists)
- Delete: `vite-env.d.ts` (if exists)

**Step 1: Find and remove frontend config files**

```bash
rm -rf node_modules/ package.json package-lock.json tsconfig.json tsconfig.node.json vite.config.ts postcss.config.* tailwind.config.* index.html .npmrc
```

**Step 2: Check for any remaining frontend artifacts**

```bash
find . -name "*.svelte" -o -name "*.vue" -o -name "*.tsx" -o -name "*.jsx" 2>/dev/null | head -20
```

Expected: no output (or only files inside `extension/`)

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove frontend build config and dependencies

Svelte/Vite/Tailwind replaced by Obsidian plugin (Phase 6)."
```

---

### Task 6: Strip browser extension screen share code

**Files:**
- Modify: `extension/content.js` — remove screen share detection
- Modify: `extension/manifest.json` — remove unnecessary permissions if any were screen-share-specific

**Step 1: Read current extension files**

Read `extension/content.js`, `extension/background.js`, and `extension/manifest.json` to understand what's screen-share-specific vs meeting-URL-detection.

**Step 2: Remove screen share signaling from content.js**

Remove any functions/code that detect screen sharing state and signal it to the daemon. Keep the meeting URL detection and the `findRecapPort()` / health check logic.

**Step 3: Verify extension still works structurally**

Review that `manifest.json` permissions, `background.js` meeting detection, and `content.js` meeting URL extraction are intact.

**Step 4: Commit**

```bash
git add extension/
git commit -m "chore: strip screen share detection from browser extension

Audio-only recording: no screen capture, no share switching.
Extension retains meeting URL detection and daemon signaling."
```

---

### Task 7: Update README

**Files:**
- Modify: `README.md`

**Step 1: Rewrite README**

Replace the current README with a new one reflecting the Obsidian plugin architecture. Include:

- Project description (meeting recording → transcription → Obsidian vault notes)
- Architecture overview (daemon + plugin diagram)
- Current status (in development, Phase 0 complete)
- Prerequisites (Python 3.10+, NVIDIA GPU with CUDA, Obsidian with Dataview + Full Calendar plugins)
- Link to design doc (`docs/plans/2026-04-13-obsidian-plugin-architecture.md`)
- Development setup (brief, will be expanded later)

Keep it short. This will be updated as phases complete.

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for Obsidian plugin architecture"
```

---

### Task 8: Regenerate MANIFEST.md

**Files:**
- Modify: `MANIFEST.md`

**Step 1: Regenerate MANIFEST.md**

Update to reflect the new repo structure after cleanup. Three sections (Stack, Structure, Key Relationships), 50-80 lines.

**Step 2: Commit**

```bash
git add MANIFEST.md
git commit -m "docs: regenerate MANIFEST.md after repo cleanup"
```

---

### Task 9: Push and verify

**Step 1: Push all commits**

```bash
git push
```

**Step 2: Verify on GitHub**

```bash
gh repo view --web
```

Check that `obsidian-pivot` branch shows the cleaned-up repo.

**Step 3: Verify tests still pass for remaining modules**

```bash
pytest tests/ -v --ignore=tests/fixtures 2>&1 | tail -20
```

Some tests may fail due to removed imports (pipeline.py may reference transcribe/frames/todoist). Note failures — they'll be fixed in Phase 1 and 3 when those modules are rewritten.
