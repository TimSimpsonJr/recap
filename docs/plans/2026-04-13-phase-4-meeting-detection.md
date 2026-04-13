# Phase 4: Meeting Detection

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically detect meeting windows (Teams, Zoom, Signal), enrich metadata via UIA for Teams, handle calendar arming, and wire detection into the recording state machine.

**Architecture:** Detection runs as an async polling loop in the daemon. EnumWindows checks every 3 seconds. The browser extension listener runs on the same port range (17839-17845). Calendar arming sets detection to watch for specific windows around scheduled meeting times.

**Tech Stack:** pywin32, uiautomation, aiohttp (extension listener)

---

### Task 1: Add uiautomation dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add uiautomation to daemon dependencies**

```toml
"uiautomation>=2.0",
```

**Step 2: Install and verify**

```bash
uv sync --extra daemon
python -c "import uiautomation; print('OK')"
```

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add uiautomation dependency for Teams metadata enrichment"
```

---

### Task 2: Window detection module

**Files:**
- Create: `recap/daemon/recorder/detection.py`
- Test: `tests/test_detection.py`

**Step 1: Write the failing tests**

```python
"""Tests for meeting window detection."""
import pytest
from unittest.mock import patch
from recap.daemon.recorder.detection import (
    MeetingWindow,
    detect_meeting_windows,
    MEETING_PATTERNS,
)


class TestMeetingPatterns:
    def test_teams_pattern_matches(self):
        assert MEETING_PATTERNS["teams"].search("Meeting with Jane | Microsoft Teams")
        assert not MEETING_PATTERNS["teams"].search("Notepad")

    def test_zoom_pattern_matches(self):
        assert MEETING_PATTERNS["zoom"].search("Zoom Meeting")
        assert MEETING_PATTERNS["zoom"].search("Zoom Webinar")

    def test_signal_pattern_matches(self):
        assert MEETING_PATTERNS["signal"].search("Signal")


class TestDetectMeetingWindows:
    def test_returns_meeting_window_objects(self):
        mock_windows = [
            (12345, "Meeting with Bob | Microsoft Teams"),
        ]
        with patch("recap.daemon.recorder.detection._enumerate_windows", return_value=mock_windows):
            meetings = detect_meeting_windows()
        assert len(meetings) == 1
        assert meetings[0].platform == "teams"
        assert meetings[0].hwnd == 12345
        assert "Bob" in meetings[0].title or "Meeting" in meetings[0].title

    def test_ignores_non_meeting_windows(self):
        mock_windows = [
            (1, "Notepad"),
            (2, "Chrome - Google"),
        ]
        with patch("recap.daemon.recorder.detection._enumerate_windows", return_value=mock_windows):
            meetings = detect_meeting_windows()
        assert len(meetings) == 0

    def test_returns_platform_for_each_window(self):
        mock_windows = [
            (1, "Meeting | Microsoft Teams"),
            (2, "Zoom Meeting"),
        ]
        with patch("recap.daemon.recorder.detection._enumerate_windows", return_value=mock_windows):
            meetings = detect_meeting_windows()
        platforms = {m.platform for m in meetings}
        assert "teams" in platforms
        assert "zoom" in platforms
```

**Step 2: Run, fail, implement**

`recap/daemon/recorder/detection.py`:
- `MEETING_PATTERNS` — dict of `platform: re.Pattern` for Teams, Zoom, Signal window titles
- `MeetingWindow` dataclass: `hwnd: int, title: str, platform: str`
- `_enumerate_windows() -> list[tuple[int, str]]` — uses `win32gui.EnumWindows` + `GetWindowText` + `IsWindowVisible`
- `detect_meeting_windows() -> list[MeetingWindow]` — enumerate windows, match against patterns, return matches

**Step 3: Run tests, commit**

```bash
pytest tests/test_detection.py -v
git add recap/daemon/recorder/detection.py tests/test_detection.py
git commit -m "feat: add meeting window detection via EnumWindows"
```

---

### Task 3: Teams UIA enrichment

**Files:**
- Create: `recap/daemon/recorder/enrichment.py`
- Test: `tests/test_enrichment.py`

**Step 1: Write the failing tests**

```python
"""Tests for Teams metadata enrichment."""
import pytest
from recap.daemon.recorder.enrichment import (
    match_known_contacts,
    KnownContact,
)


class TestKnownContactMatching:
    def test_matches_exact_display_name(self):
        contacts = [
            KnownContact(name="Jane Smith", display_name="Jane Smith"),
            KnownContact(name="Bob Lee", display_name="Bob L."),
        ]
        result = match_known_contacts(["Jane Smith", "Bob L."], contacts)
        assert result == ["Jane Smith", "Bob Lee"]

    def test_returns_original_name_for_no_match(self):
        contacts = [
            KnownContact(name="Jane Smith", display_name="Jane Smith"),
        ]
        result = match_known_contacts(["Unknown Person"], contacts)
        assert result == ["Unknown Person"]

    def test_empty_contacts_returns_originals(self):
        result = match_known_contacts(["Alice", "Bob"], [])
        assert result == ["Alice", "Bob"]
```

**Step 2: Run, fail, implement**

`recap/daemon/recorder/enrichment.py`:
- `KnownContact` dataclass: `name: str, display_name: str`
- `match_known_contacts(display_names: list[str], contacts: list[KnownContact]) -> list[str]` — match display names to known contacts, return resolved names
- `extract_teams_participants(hwnd: int) -> list[str] | None` — use uiautomation to walk the Teams accessibility tree, extract participant names from the roster panel. Returns None on failure (best-effort). Retry once on partial results (WebView2 UIA inconsistency).
- `enrich_meeting_metadata(meeting: MeetingWindow, known_contacts: list[KnownContact]) -> dict` — combine UIA extraction + known contact matching + window title parsing. Returns `{"title": ..., "participants": [...], "platform": ...}`.

UIA extraction is inherently fragile. Wrap everything in try/except, log failures at DEBUG level, never block recording.

**Step 3: Run tests, commit**

```bash
pytest tests/test_enrichment.py -v
git add recap/daemon/recorder/enrichment.py tests/test_enrichment.py
git commit -m "feat: add Teams UIA enrichment and known contacts matching"
```

---

### Task 4: Detection polling loop

**Files:**
- Create: `recap/daemon/recorder/detector.py`
- Test: `tests/test_detector.py`

**Step 1: Write the failing tests**

```python
"""Tests for detection polling loop."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from recap.daemon.recorder.detector import MeetingDetector


class TestMeetingDetector:
    def test_detection_config_respects_enabled(self):
        config = MagicMock()
        config.detection.teams.enabled = False
        config.detection.zoom.enabled = True
        config.detection.signal.enabled = True
        detector = MeetingDetector(config=config)
        assert "teams" not in detector.enabled_platforms
        assert "zoom" in detector.enabled_platforms

    def test_auto_record_behavior(self):
        config = MagicMock()
        config.detection.teams.behavior = "auto-record"
        config.detection.teams.default_org = "disbursecloud"
        detector = MeetingDetector(config=config)
        assert detector.get_behavior("teams") == "auto-record"
        assert detector.get_default_org("teams") == "disbursecloud"

    def test_prompt_behavior_for_signal(self):
        config = MagicMock()
        config.detection.signal.behavior = "prompt"
        detector = MeetingDetector(config=config)
        assert detector.get_behavior("signal") == "prompt"
```

**Step 2: Run, fail, implement**

`MeetingDetector`:
- `__init__(config, state_machine, recorder, on_signal_detected)` — takes detection config, recorder state machine, and a callback for Signal prompt
- `enabled_platforms` property — list of platforms with `enabled: True`
- `get_behavior(platform) -> str` — "auto-record" or "prompt"
- `get_default_org(platform) -> str`
- `start()` — start async polling loop (every 3 seconds)
- `stop()` — stop polling
- Polling logic:
  1. Call `detect_meeting_windows()`
  2. For each detected meeting not already being recorded:
     - If behavior is "auto-record": transition state machine to RECORDING, start recorder
     - If behavior is "prompt": fire `on_signal_detected` callback (for Signal popup)
  3. Track currently detected meetings to avoid re-triggering
  4. If a previously detected meeting window disappears: this is handled by the window monitoring in the recorder (Phase 2), not here

**Step 3: Run tests, commit**

```bash
pytest tests/test_detector.py -v
git add recap/daemon/recorder/detector.py tests/test_detector.py
git commit -m "feat: add detection polling loop with per-platform behavior"
```

---

### Task 5: Browser extension listener

**Files:**
- Modify: `recap/daemon/server.py` — add extension-compatible endpoints

**Step 1: Add extension endpoints**

The browser extension hits these endpoints on ports 17839-17845:
- `GET /health` — already exists
- `POST /meeting-detected` — extension signals a meeting URL was found. Body: `{"url": "...", "platform": "meet"}`
- `POST /meeting-ended` — extension signals meeting page closed

Read `extension/background.js` and `extension/content.js` to confirm the exact endpoint paths and request format.

**Step 2: Wire extension signals to detector**

When the extension signals a meeting, the detector should:
- Extract meeting URL and platform
- Merge with EnumWindows detection (avoid duplicate detection)
- Same auto-record / prompt behavior as window detection

**Step 3: Test with actual extension**

Load the extension in Chrome, join a Google Meet test call, verify the daemon receives the signal.

**Step 4: Commit**

```bash
git add recap/daemon/server.py
git commit -m "feat: add browser extension listener endpoints for meeting detection"
```

---

### Task 6: Signal detection popup

**Files:**
- Create: `recap/daemon/recorder/signal_popup.py`

**Step 1: Implement popup dialog**

When a Signal call is detected, show a native Windows dialog (using `tkinter` since pystray's thread can't show dialogs):

- Title: "Signal call detected"
- "Record this call?"
- Org dropdown (populated from config orgs)
- Pipeline dropdown ("Claude" / "Local only")
- "Skip" and "Record" buttons

`show_signal_popup(orgs: list[str], defaults: dict) -> dict | None`:
- Returns `{"org": "personal", "backend": "ollama"}` if Record clicked
- Returns None if Skip clicked or window closed

Run in a separate thread (tkinter needs its own mainloop).

**Step 2: Wire to detector**

The detector's `on_signal_detected` callback calls `show_signal_popup()`. On "Record": start recording with returned org + backend. On "Skip": ignore.

**Step 3: Manual test**

Open Signal on the desktop, verify popup appears. Click Record, verify recording starts. Click Skip, verify nothing happens.

**Step 4: Commit**

```bash
git add recap/daemon/recorder/signal_popup.py
git commit -m "feat: add Signal call detection popup with org/pipeline picker"
```

---

### Task 7: Calendar arming

**Files:**
- Modify: `recap/daemon/recorder/detector.py` — add calendar arming logic

**Step 1: Implement arming**

Add to `MeetingDetector`:
- `arm_for_event(event_id, start_time, platform_hint)` — arm detection to start N minutes before a calendar event (default 2 minutes)
- When armed: state machine → ARMED. Detection polling becomes more aggressive (every 1 second instead of 3).
- When meeting window detected during armed period: auto-start recording
- When armed period expires without detection (event start + 10 minutes): disarm, state → IDLE
- Calendar sync (Phase 5) calls `arm_for_event()` for upcoming events

For now, arming is called manually via HTTP endpoint:
`POST /api/arm` — body: `{"event_id": "...", "start_time": "...", "org": "..."}`

Calendar sync will call this automatically in Phase 5.

**Step 2: Test arming via HTTP**

```bash
curl -X POST http://localhost:9847/api/arm \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"event_id": "test", "start_time": "2026-04-14T14:00:00", "org": "disbursecloud"}'
```

**Step 3: Commit**

```bash
git add recap/daemon/recorder/detector.py recap/daemon/server.py
git commit -m "feat: add calendar arming for pre-meeting detection"
```

---

### Task 8: Window monitoring for recording end

**Files:**
- Modify: `recap/daemon/recorder/detector.py` — monitor active meeting window

**Step 1: Add window monitoring during recording**

When recording starts for a detected meeting:
- Track the `hwnd` of the meeting window
- Poll every 3 seconds: is the window still visible?
- If window closes: trigger recording stop (same as silence detection, but immediate)
- This works alongside silence detection (Phase 2) — whichever fires first wins

**Step 2: Test**

Start a test call, start recording, close the meeting window. Verify recording stops immediately.

**Step 3: Commit**

```bash
git add recap/daemon/recorder/detector.py
git commit -m "feat: add window monitoring to detect meeting end"
```

---

### Task 9: Wire detection to daemon

**Files:**
- Modify: `recap/daemon/__main__.py` — start detector on daemon startup

**Step 1: Integrate detector**

In the daemon entry point:
- Create `MeetingDetector` with config, state machine, recorder
- Start detection polling on daemon startup
- Wire Signal popup callback
- Wire tray state updates to detector state

**Step 2: Full manual test**

1. Start daemon
2. Open Microsoft Teams, start a call
3. Verify daemon auto-detects and starts recording
4. End the call
5. Verify recording stops and pipeline runs
6. Check vault note appears

**Step 3: Commit**

```bash
git add recap/daemon/__main__.py
git commit -m "feat: wire meeting detection to daemon startup"
```

---

### Task 10: Push and verify

```bash
pytest tests/ -v --ignore=tests/fixtures
git push
```
