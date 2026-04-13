# Phase 9: Packaging + Polish

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Package the daemon as a PyInstaller folder distribution, add Windows Task Scheduler auto-start toggle, clean up the browser extension, set up Claude Desktop scheduled tasks, and run end-to-end testing.

**Architecture:** The daemon is packaged as a folder-mode PyInstaller distribution (exe + dependencies). The plugin can spawn the daemon or it auto-starts on login via Task Scheduler. Claude Desktop scheduled tasks handle briefings and note enrichment.

**Tech Stack:** PyInstaller, schtasks (Windows), Claude Desktop

---

### Task 1: PyInstaller spec file

**Files:**
- Create: `recap-daemon.spec` (or `scripts/build-daemon.py`)

**Step 1: Create PyInstaller build script**

```python
"""Build script for daemon PyInstaller package."""
import PyInstaller.__main__
import sys

PyInstaller.__main__.run([
    "recap/daemon/__main__.py",
    "--name=recap-daemon",
    "--noconfirm",
    "--clean",
    # Folder mode (not --onefile) for faster startup
    "--distpath=dist",
    "--workpath=build",
    # Include NeMo models, prompts, etc
    "--add-data=prompts:prompts",
    # Hidden imports for dynamic loads
    "--hidden-import=nemo.collections.asr",
    "--hidden-import=pyaudiowpatch",
    "--hidden-import=pyflac",
    "--hidden-import=pystray",
    "--hidden-import=keyring.backends.Windows",
    # Exclude unnecessary packages to reduce size
    "--exclude-module=matplotlib",
    "--exclude-module=tkinter",
])
```

Note: NeMo + PyTorch will make this a large distribution (~1-2GB). That's expected.

**Step 2: Build and test**

```bash
python scripts/build-daemon.py
dist/recap-daemon/recap-daemon.exe path/to/config.yaml
```

Verify: daemon starts from the packaged exe, tray icon appears, HTTP server responds.

**Step 3: Commit**

```bash
git add scripts/build-daemon.py
git commit -m "feat: add PyInstaller build script for daemon packaging"
```

---

### Task 2: Auto-start toggle

**Files:**
- Create: `recap/daemon/autostart.py`
- Modify: `recap/daemon/server.py` — add auto-start endpoints

**Step 1: Implement Task Scheduler registration**

```python
"""Windows Task Scheduler auto-start management."""
import subprocess
import pathlib


def install_autostart(daemon_exe_path: pathlib.Path, config_path: pathlib.Path) -> bool:
    """Register daemon to run on user login via Task Scheduler."""
    cmd = [
        "schtasks", "/create",
        "/tn", "RecapDaemon",
        "/tr", f'"{daemon_exe_path}" "{config_path}"',
        "/sc", "onlogon",
        "/rl", "limited",
        "/f",  # force overwrite if exists
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def remove_autostart() -> bool:
    """Remove daemon from Task Scheduler."""
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", "RecapDaemon", "/f"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def is_autostart_enabled() -> bool:
    """Check if daemon is registered in Task Scheduler."""
    result = subprocess.run(
        ["schtasks", "/query", "/tn", "RecapDaemon"],
        capture_output=True, text=True,
    )
    return result.returncode == 0
```

**Step 2: Add HTTP endpoints**

- `GET /api/autostart` — returns `{"enabled": true/false}`
- `POST /api/autostart/enable` — calls `install_autostart()`
- `POST /api/autostart/disable` — calls `remove_autostart()`

Plugin settings tab wires a toggle to these endpoints.

**Step 3: Test**

Enable auto-start, log out and back in, verify daemon starts automatically. Check Windows Settings → Apps → Startup shows "RecapDaemon". Disable, verify it's removed.

**Step 4: Commit**

```bash
git add recap/daemon/autostart.py recap/daemon/server.py
git commit -m "feat: add Windows Task Scheduler auto-start toggle"
```

---

### Task 3: Browser extension cleanup

**Files:**
- Modify: `extension/content.js`
- Modify: `extension/manifest.json`

**Step 1: Remove screen share code from content.js**

Read through `content.js` and remove:
- Screen share detection functions
- Screen share state signaling to daemon
- Any DOM observers watching for screen share UI elements

Keep:
- Meeting URL detection
- `findRecapPort()` and health check logic
- Meeting detected/ended signaling

**Step 2: Clean up manifest.json**

Remove any permissions that were only needed for screen share detection.

**Step 3: Test extension**

Load in Chrome, join a Google Meet test call, verify meeting detection works and signals reach daemon.

**Step 4: Commit**

```bash
git add extension/
git commit -m "chore: strip screen share detection from extension (audio-only)"
```

---

### Task 4: Claude Desktop scheduled tasks

**Files:**
- Create: `docs/scheduled-tasks/morning-briefing.md` — task prompt for Claude Desktop
- Create: `docs/scheduled-tasks/note-enrichment.md` — task prompt for Claude Desktop

**Step 1: Write briefing task prompt**

```markdown
# Morning Briefing Task

Check today's calendar notes in the vault at `C:\Users\tim\OneDrive\Documents\Tim's Vault\_Recap\Calendar\`.

For each meeting note dated today:
1. Read the note's participants from frontmatter
2. Search `_Recap/*/Meetings/` for past meeting notes with overlapping participants
3. From those past meetings, gather: open action items, key decisions, relationship notes
4. Append a `## Briefing` section to today's meeting note with:
   - Key context from past meetings
   - Open action items relevant to this meeting's participants
   - Relationship notes if this is a recurring meeting

Also write/update a digest note at `_Recap/Calendar/Briefings/YYYY-MM-DD.md` listing all of today's meetings with links.

Do NOT modify anything above existing `## Briefing` sections. Only append/replace the briefing section.
```

**Step 2: Write note enrichment task prompt**

```markdown
# Note Enrichment Task

Check for meeting notes in `_Recap/*/Meetings/` that were created or modified since the last enrichment run.

For each new/updated meeting note:
1. Read the participants and companies from frontmatter
2. For each participant, find their People note in `_Recap/*/People/`
3. Read the existing People note content
4. Read the meeting note's key points, decisions, and action items
5. Integrate new insights into the People note — update topics, add meeting reference, note any role/context changes
6. Do the same for Company notes in `_Recap/*/Companies/`

If a People or Company note doesn't exist, create a stub with frontmatter and initial sections.

Preserve all existing user-written content in People/Company notes. Add new information under appropriate sections, don't reorganize or rewrite existing content.
```

**Step 3: Register scheduled tasks in Claude Desktop**

Use the Claude Desktop scheduled tasks feature to register:
- Morning briefing: daily at ~8am
- Note enrichment: 3x daily at ~8:30am, 1pm, 6pm

**Step 4: Commit**

```bash
git add docs/scheduled-tasks/
git commit -m "docs: add Claude Desktop scheduled task prompts for briefing and enrichment"
```

---

### Task 5: End-to-end testing

**Step 1: Full lifecycle test**

1. **Install:** Build daemon with PyInstaller, install plugin in Obsidian
2. **Configure:** Set up `_Recap/.recap/config.yaml` with vault path, org config
3. **OAuth:** Connect Zoho calendar via settings tab
4. **Calendar sync:** Wait for sync, verify calendar notes appear
5. **Auto-detect:** Start a Teams call, verify daemon detects and records
6. **Pipeline:** After call ends, verify pipeline runs (check logs + frontmatter status)
7. **Vault note:** Verify meeting note appears in correct org subfolder with correct format
8. **Live transcript:** During a second test call, open live transcript view, verify segments appear
9. **Speaker correction:** If speakers unidentified, test the correction modal
10. **Briefing:** Run morning briefing task, verify briefing appended to tomorrow's meeting notes
11. **Enrichment:** Run note enrichment, verify people/company notes updated
12. **Auto-start:** Enable auto-start, reboot, verify daemon starts on login
13. **Error handling:** Kill daemon mid-recording, restart, verify orphaned FLAC detected

**Step 2: Fix any issues found**

Each fix gets its own commit.

---

### Task 6: Update README and MANIFEST.md

**Files:**
- Modify: `README.md` — update with installation instructions, usage guide
- Modify: `MANIFEST.md` — regenerate for final repo structure

**Step 1: README update**

Add:
- Installation instructions (build daemon, install plugin, configure)
- Quick start guide
- Configuration reference
- Troubleshooting section
- Architecture diagram

**Step 2: MANIFEST.md**

Regenerate to reflect the final repo structure.

**Step 3: Commit**

```bash
git add README.md MANIFEST.md
git commit -m "docs: update README and MANIFEST for final architecture"
```

---

### Task 7: Final push

```bash
pytest tests/ -v --ignore=tests/fixtures
git push
```

At this point, the `obsidian-pivot` branch has the complete implementation. Create a PR for review before merging to master.
