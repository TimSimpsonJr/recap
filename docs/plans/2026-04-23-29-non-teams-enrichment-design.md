# Issue #29 — Non-Teams Participant Enrichment Design

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement from the plan document that follows this design.

**Goal:** Populate `RecordingMetadata.participants` for spontaneous Zoom, Google Meet, and Zoho meetings without regressing Teams or Signal, so frontmatter and the analysis prompt carry meaningful rosters for the entire recorded-meeting corpus.

**Architecture:** Introduce a `ParticipantRoster` accumulator owned by `MeetingDetector` that receives names from three sources (Teams UIA one-shot at detection, Zoom UIA periodic during recording, browser-extension DOM push via a new HTTP endpoint) and finalizes into `RecordingMetadata.participants` via a seam on `Recorder.stop()` that fires for every stop path. Browser DOM extraction ships as a content script on built-in Meet/Zoho/tranzpay hosts, polled by a `chrome.alarms` 30s cadence in the service worker.

**Tech Stack:** Python 3.12 async daemon (aiohttp), `uiautomation` for Windows UI Automation, Chrome MV3 extension (manifest v3, service worker + content script), pytest + manual acceptance for testing.

---

## 1. Architecture overview

Three data sources converge on one accumulator:

```
┌─── Teams UIA (one-shot at detection) ──────┐
├─── Zoom UIA (every 30s during recording) ──┤─► ParticipantRoster.merge(source, names, now)
└─── Browser DOM (extension → HTTP endpoint) ┘           │
                                                         ▼
                                                    roster.finalize()
                                                         │
                                                         ▼
                                     Recorder.stop() seam → metadata.participants → sidecar rewrite
```

**Ownership split:**
- `MeetingDetector` owns `ParticipantRoster`. It arms a fresh roster immediately before calling `recorder.start()`, and registers the stop finalizer in the same step.
- `Recorder` owns the finalization seam: a callback invoked inside every `stop()` path, pre-sidecar-rewrite.
- Neither knows the other's internals — the seam is a single registered `Callable[[], list[str]] | None` on Recorder.

**Platform matrix:**

| Platform | Ingress | Source tag | Cadence |
|---|---|---|---|
| Teams (native window) | existing `extract_teams_participants` | `teams_uia_detection` | once, at detection |
| Zoom (native window) | new `extract_zoom_participants` | `zoom_uia_periodic` | every 30s during recording |
| Google Meet (browser) | `/api/meeting-participants-updated` | `browser_dom_google_meet` | every 30s during recording |
| Zoho Meet (browser, incl. `meeting.tranzpay.io`) | `/api/meeting-participants-updated` | `browser_dom_zoho_meet` | every 30s during recording |
| Signal | — (out of scope, empty roster) | — | — |
| Teams-via-browser | — (known v1 gap, empty roster) | — | — |

**Explicitly not in v1:**
- WebSocket `participants_updated` broadcast (deferred to live-transcription work; `merge()` return value shaped to make this an additive follow-up).
- DOM MutationObserver fast-path for browser (would split cadence models across platforms).
- Voice fingerprinting, directory imports, known_contacts schema changes (all tracked separately in #28).
- Dynamic content-script registration via `chrome.scripting` — browser roster enrichment is scoped to built-in hosts; user-added URL patterns retain pre-#29 empty-participants behavior.

## 2. `ParticipantRoster` class

**File:** `recap/daemon/recorder/roster.py` (new)

```python
class ParticipantRoster:
    """Per-recording ordered-dedupe participant accumulator.

    Owned by MeetingDetector. Fed by Teams UIA (one-shot), Zoom UIA
    (periodic), and browser DOM extraction (periodic HTTP push).
    Finalized list becomes RecordingMetadata.participants at stop time.

    Shaped for future additive behavior: merge() returns whether the
    roster changed in a user-visible way, so a later WebSocket
    participants_updated broadcast can hook in without redesign.

    Thread-safety: NONE. All callers run on the daemon's single asyncio
    event loop (aiohttp handler + detector poll + recorder stop).
    Introducing threads requires adding locks.
    """

    def __init__(self) -> None:
        # key=casefold, value=display. Dict preserves insertion order
        # since Py3.7, so updates to existing keys don't reorder.
        self._names: dict[str, str] = {}
        self._last_merge_per_source: dict[str, datetime] = {}

    def merge(
        self,
        source: str,
        names: Sequence[str],
        observed_at: datetime,
    ) -> bool:
        """Merge names from a source. Returns True if the roster changed
        in a user-visible way (new name added OR display form upgraded).

        observed_at MUST be timezone-aware. Naive datetimes raise
        ValueError so timestamps stay usable downstream.
        """
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        changed = False
        for raw in names:
            name = raw.strip()
            if not name:
                continue
            key = name.casefold()
            existing = self._names.get(key)
            if existing is None or existing != name:
                self._names[key] = name
                changed = True
        self._last_merge_per_source[source] = observed_at
        return changed

    def current(self) -> list[str]:
        """Current ordered deduped roster. Safe to call during recording."""
        return list(self._names.values())

    def finalize(self) -> list[str]:
        """Final roster at stop time. Same as current() in v1; separate
        seam so future finalization logic (e.g. diarization reconciliation)
        can hook here without callers changing."""
        return self.current()
```

**Design decisions:**

| Decision | Choice | Rationale |
|---|---|---|
| Internal store | `dict[str, str]` (casefold → display) | Case-insensitive dedupe + stable first-seen ordering + upgradeable display form |
| Known-contacts matching | At ingress (caller-side), not in roster | Roster is a plain accumulator; `match_known_contacts` canonicalizes before merging |
| Source attribution | Stored as per-source last-merge timestamp only | YAGNI for v1; future diarization can extend |
| `observed_at` | Timezone-aware; `ValueError` on naive | Timestamps stay usable; `datetime.now().astimezone()` at every merge site |
| Thread safety | None | Single-threaded asyncio is invariant; enforced in docstring |
| Lifecycle | New instance per recording | Detector arms fresh instance post-`recorder.start()` success |

**Known limitation documented in docstring:** Cross-source name variants are NOT reconciled beyond casefold. `"Alice S."` from Teams UIA and `"Alice Smith"` from a later Zoom UIA merge would appear as two entries unless both resolve to the same canonical name via `match_known_contacts` at ingress. Curating `known_contacts` is the user's dedupe mechanism.

## 3. Daemon wiring

### 3.1 `Recorder.stop()` finalization seam

Add to `Recorder.__init__`:

```python
self.on_before_finalize: Callable[[], list[str]] | None = None
self.on_after_stop: Callable[[], None] | None = None
```

Inject into the existing sidecar-rewrite block at [recorder.py:288-301](recap/daemon/recorder/recorder.py:288), **unconditionally** for every stop path (API, detector, silence-timeout, duration-timeout, fatal audio event):

```python
finalized_participants: list[str] | None = None
if self.on_before_finalize is not None:
    try:
        finalized_participants = self.on_before_finalize()
    except Exception:
        logger.warning("Participant finalizer failed", exc_info=True)

should_rewrite_for_participants = (
    finalized_participants is not None
    and self._current_metadata is not None
    and finalized_participants != self._current_metadata.participants
)

if (
    path is not None
    and self._current_metadata is not None
    and (audio_warnings or devices_seen or should_rewrite_for_participants)
):
    self._current_metadata.audio_warnings = audio_warnings
    self._current_metadata.system_audio_devices_seen = devices_seen
    if should_rewrite_for_participants:
        self._current_metadata.participants = finalized_participants
    try:
        write_recording_metadata(path, self._current_metadata)
    except OSError:
        logger.warning("Failed to persist sidecar for %s", path, exc_info=True)

if self.on_after_stop is not None:
    try:
        self.on_after_stop()
    except Exception:
        logger.warning("on_after_stop hook failed", exc_info=True)
```

- **Empty roster at finalize** (Zoom UIA found nothing, browser never pushed) → `finalized_participants == []` → `should_rewrite_for_participants == False` → no rewrite.
- **Teams-seeded identical-list at finalize** → differs-from-initial False → no rewrite.
- **Zoom/browser merges produced new names** → differs-from-initial True, non-empty → rewrite.
- **Hooks raising** never abort stop. Hooks persist between sessions until next `start()` overwrites; `_end_roster_session()` makes them inert by clearing detector-owned state.

### 3.2 `MeetingDetector` session lifecycle

```python
def _begin_roster_session(
    self,
    initial_names: Sequence[str] = (),
    initial_source: str | None = None,
    tab_id: int | None = None,
) -> None:
    """Arm a fresh roster, seed with any one-shot extraction, and register
    stop hooks. Called AFTER recorder.start() succeeds so a failed start
    cannot leak detector session state.

    Seeding with Teams' one-shot enrichment makes finalize() idempotent
    when no later merges happen, so the start-time sidecar (which is
    what crash-recovery rehydration reads at pipeline/__init__.py:602)
    always carries the best snapshot available at that moment.
    """
    roster = ParticipantRoster()
    if initial_names and initial_source:
        roster.merge(
            initial_source,
            list(initial_names),
            datetime.now().astimezone(),
        )
    self._active_roster = roster
    self._extension_recording_tab_id = tab_id
    self._polls_since_roster_refresh = 0
    self._recorder.on_before_finalize = roster.finalize
    self._recorder.on_after_stop = self._end_roster_session

def _end_roster_session(self) -> None:
    """Clear detector-owned session state. Registered as Recorder.on_after_stop
    so it fires on every stop path — API, silence, duration, fatal, extension."""
    self._active_roster = None
    self._extension_recording_tab_id = None
    self._polls_since_roster_refresh = 0
```

Called from every `recorder.start()` success site in detector:
- Armed-event detection path ([detector.py:389](recap/daemon/recorder/detector.py:389))
- Auto-record detection path ([detector.py:399](recap/daemon/recorder/detector.py:399))
- Signal popup acceptance
- `handle_extension_meeting_detected` browser path

Redundant clear in `handle_extension_meeting_ended` at [detector.py:327](recap/daemon/recorder/detector.py:327) is **removed**; `on_after_stop` is the single source of truth for session cleanup.

**Teams one-shot funneling:**
1. `enriched = enrich_meeting_metadata(...)` — existing behavior, Teams UIA + `match_known_contacts`.
2. Build `metadata` with `participants=enriched["participants"]` — initial sidecar at [recorder.py:212](recap/daemon/recorder/recorder.py:212) carries the Teams roster, preserving crash-recovery rehydration.
3. `await recorder.start(metadata)`.
4. `_begin_roster_session(initial_names=enriched["participants"], initial_source="teams_uia_detection", ...)` primes the roster.
5. Typical outcome: no later merges → `finalize()` returns same list → no rewrite.

### 3.3 Zoom UIA periodic extraction

New in `call_state.py`:

```python
def extract_zoom_participants(hwnd: int) -> list[str] | None:
    """Walk the Zoom client's UIA tree for participant panel entries.
    Mirrors extract_teams_participants. Returns None on any failure —
    the function must never crash the detection poll."""
    # Lazy import uiautomation (Windows-only, untyped).
    # Depth-bounded walk (max_depth=15, matching Teams walker).
    # Target: ListItemControl entries in the participants pane.
    # Empty result or any exception → None.
```

Detector poll wiring:

```python
_ROSTER_REFRESH_POLLS = 10  # 10 polls * 3s base interval = 30s cadence

async def _poll_once(self) -> None:
    # ... existing stop-monitoring, arm-timeout, detection paths ...

    if (
        self._recorder.is_recording
        and self._recording_hwnd is not None
        and self._active_roster is not None
    ):
        self._polls_since_roster_refresh += 1
        if self._polls_since_roster_refresh >= _ROSTER_REFRESH_POLLS:
            self._polls_since_roster_refresh = 0
            await self._refresh_roster_uia()

async def _refresh_roster_uia(self) -> None:
    """Platform-dispatched UIA roster refresh. Zoom only in v1 —
    Teams stays one-shot per issue's non-goal 'don't change Teams
    enrichment.'"""
    # ... look up current recording's platform; if Zoom, call
    #     extract_zoom_participants, match_known_contacts, merge.
```

**Teams deliberately skipped** in periodic refresh to preserve the issue's "don't change Teams enrichment" non-goal. Zoom is the only platform refreshed via UIA during recording.

### 3.4 `/api/meeting-participants-updated` endpoint

```python
async def _meeting_participants_updated_api(request):
    detector = request.app.get(_DETECTOR_KEY)
    if detector is None:
        return web.json_response({"error": "detector not available"}, status=503)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return web.json_response({"error": "body must be an object"}, status=400)

    tab_id = body.get("tabId")
    raw_list = body.get("participants")
    if tab_id is None:
        return web.json_response({"error": "missing required field: tabId"}, status=400)
    if not isinstance(raw_list, list):
        return web.json_response({"error": "participants must be a list"}, status=400)

    # Filter non-string entries rather than stringifying — don't let
    # malformed payloads leak garbage into frontmatter.
    participants = [p for p in raw_list if isinstance(p, str)]
    if len(participants) != len(raw_list):
        dropped = len(raw_list) - len(participants)
        logger.debug(
            "participants endpoint dropped %d non-string entries (tabId=%s)",
            dropped, tab_id,
        )

    # Defense against pathological DOM.
    if len(participants) > 100:
        logger.warning(
            "participants endpoint truncated %d-item payload to 100 (tabId=%s)",
            len(participants), tab_id,
        )
        participants = participants[:100]

    accepted = await detector.handle_extension_participants_updated(
        tab_id=tab_id, participants=participants,
    )
    return web.json_response({
        "status": "accepted" if accepted else "ignored",
    })
```

Detector handler:

```python
async def handle_extension_participants_updated(
    self, *, tab_id: int | None, participants: list[str],
) -> bool:
    if (
        tab_id is None
        or tab_id != self._extension_recording_tab_id
        or self._active_roster is None
        or not self._recorder.is_recording
    ):
        return False
    platform = self._current_browser_platform  # stashed at start
    source = f"browser_dom_{platform}"  # e.g. browser_dom_google_meet
    matched = match_known_contacts(participants, self._config.known_contacts)
    self._active_roster.merge(source, matched, datetime.now().astimezone())
    return True
```

Silent drop (200 `{"status": "ignored"}`) covers: no active recording, wrong tab_id, roster cleared during stop. Never 4xx on racy state from a content script that hasn't noticed the recording ended.

## 4. Extension changes

### 4.1 Self-contained content script

Chrome's manifest does not support `type: "module"` on content scripts. `content.js` stays self-contained. Platform detection by hostname literal:

```javascript
function platformForHost(h) {
  if (h === "meet.google.com") return "google_meet";
  if (h.startsWith("meeting.zoho.") || h === "meeting.tranzpay.io") return "zoho_meet";
  return null;
}
```

### 4.2 Built-in-hosts-only scope

Detection (via `chrome.storage.local.meetingPatterns` + background `matchesMeetingUrl`) remains user-customizable. Enrichment (via manifest `content_scripts.matches`) is **static and limited to built-in hosts**. User-added hosts still trigger recording but do NOT receive roster refresh.

This is an intentional product boundary, documented in release notes, a `LIMITATION:` comment near the alarm registration in `background.js`, and the handoff doc.

### 4.3 `manifest.json`

```json
{
  "manifest_version": 3,
  "name": "Recap Meeting Detector",
  "version": "1.1.0",
  "permissions": ["tabs", "storage", "alarms"],
  "host_permissions": [
    "http://localhost/*",
    "https://meet.google.com/*",
    "https://meeting.zoho.com/*",
    "https://meeting.zoho.eu/*",
    "https://meeting.zoho.in/*",
    "https://meeting.zoho.com.au/*",
    "https://meeting.tranzpay.io/*"
  ],
  "content_scripts": [{
    "matches": [
      "https://meet.google.com/*",
      "https://meeting.zoho.com/*",
      "https://meeting.zoho.eu/*",
      "https://meeting.zoho.in/*",
      "https://meeting.zoho.com.au/*",
      "https://meeting.tranzpay.io/*"
    ],
    "js": ["content.js"],
    "run_at": "document_idle"
  }],
  "background": { "service_worker": "background.js" }
}
```

**User impact on reload:** Chrome prompts for new host permissions. Release notes call this out.

**Teams-via-browser** (`teams.microsoft.com`) intentionally excluded from content scripts — the v1 known gap.

### 4.4 `content.js`

```javascript
// content.js — scrapes participant rosters on request from background.
// Runs only on domains declared in manifest content_scripts.matches.

function platformForHost(h) { /* ... */ }

function scrapeMeet() {
  // Fallback selector ladder — first non-empty hit wins. Selectors drift;
  // v1 ships with best-known selectors, logs a miss via background telemetry.
  const selectors = [
    '[role="list"][aria-label*="participant" i] [role="listitem"] [data-self-name], [role="list"][aria-label*="participant" i] [role="listitem"] span',
    '[data-participant-id]',
    'div[jsname][data-participant-id] span',
  ];
  for (const sel of selectors) {
    const nodes = document.querySelectorAll(sel);
    if (nodes.length === 0) continue;
    const names = Array.from(nodes, n =>
      (n.getAttribute("data-self-name") || n.textContent || "").trim()
    ).filter(Boolean);
    if (names.length) return names;
  }
  return [];
}

function scrapeZoho() {
  // Selectors TBD from fixture HTML captured during a real call.
  const selectors = [
    '[data-testid="participant-name"]',
    '.participant-list .participant-name',
  ];
  for (const sel of selectors) {
    const nodes = document.querySelectorAll(sel);
    if (nodes.length === 0) continue;
    const names = Array.from(nodes, n => (n.textContent || "").trim()).filter(Boolean);
    if (names.length) return names;
  }
  return [];
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "recap:get-roster") {
    const platform = platformForHost(window.location.hostname);
    let participants = [];
    try {
      if (platform === "google_meet") participants = scrapeMeet();
      else if (platform === "zoho_meet") participants = scrapeZoho();
    } catch (e) {
      console.warn("Recap content-script scrape failed:", e.message);
    }
    sendResponse({ platform, participants });
    return true;
  }
});
```

### 4.5 `background.js` additions

```javascript
chrome.alarms.create("recap-roster-refresh", { periodInMinutes: 0.5 });

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === "recap-health-check") { void findRecapDaemon(); return; }
  if (alarm.name === "recap-roster-refresh") { void refreshAllRosters(); return; }
});

async function refreshAllRosters() {
  // LIMITATION: only built-in hosts get content-script injection, so
  // user-added meeting patterns won't receive roster refresh here.
  for (const [tabId, tab] of activeMeetingTabs) {
    try {
      const response = await chrome.tabs.sendMessage(tabId, { type: "recap:get-roster" });
      if (!response) continue;
      const participants = (response.participants || []).slice(0, 50);
      if (participants.length === 0) continue;  // skip empty pushes
      await notifyRecap("/api/meeting-participants-updated", { tabId, participants });
    } catch (e) {
      // Expected for Teams-via-browser tabs (no content script), closed tabs,
      // page reloads. Don't log — noise.
    }
  }
}
```

## 5. Error handling and edge cases

### Extension layer
- Selectors all miss → `[]` → background skips empty payloads.
- Content script throws → caught inside `onMessage`, responds with empty list.
- `chrome.tabs.sendMessage` rejects (tab closed, no content script) → silently skipped.
- Daemon unreachable / 401 → existing badge handling, no retry this tick.
- Pathological DOM → `participants.slice(0, 50)` cap in background.

### Daemon endpoint layer
| Condition | Response |
|---|---|
| Auth missing/invalid | 401 via existing middleware |
| Body not JSON | 400 |
| Body not object | 400 |
| Missing `tabId` | 400 |
| `participants` not a list | 400 |
| Non-string list entries | Filter + debug log |
| > 100 entries | Truncate to 100 + warning log |
| No active recording / wrong tabId / no roster / not recording | 200 `{"status": "ignored"}` + debug log |

### Detector and roster layer
- `extract_zoom_participants` raises → `None` → skip merge.
- Roster merge with naive datetime → `ValueError` (caller responsibility; all sites use `datetime.now().astimezone()`).
- Merge after `_end_roster_session` → `_active_roster is None` guard, no-op.
- Empty match list → merge returns False, harmless.

### Recorder stop path
- `on_before_finalize` raises → logged, treated as `None`, stop completes.
- `on_after_stop` raises → logged, stop completes.
- `write_recording_metadata` raises `OSError` → existing warning, initial sidecar remains.

### Crash / recovery
| Scenario | Outcome |
|---|---|
| Crash after start, Teams path, before any merge | Initial sidecar has Teams one-shot → rehydration works |
| Crash after start, Zoom/browser path | Initial sidecar `participants=[]` → same as today's non-Teams behavior |
| Crash mid-recording after Zoom refreshes | In-memory roster lost → initial sidecar survives → degraded but no corruption |
| Double-stop race | Finalize idempotent, differs=False on second call → no double-rewrite |

### v1 residual risks (documented, not mitigated)

- **Zoom UIA hang** would stall the detector poll loop, which *also* owns stop-monitoring. A hanging walk during an active Zoom recording could prevent meeting-end detection until silence-timeout or manual stop. This is a genuinely broader risk surface than current Teams-only exposure (Teams UIA runs once, pre-recording). Mitigation deferred: move roster refresh to a separate async task + `asyncio.wait_for` + executor offload. Task-lifecycle complexity outweighed the marginal risk reduction for v1.
- **Meet/Zoho DOM selector rot** — silent empty return when Google/Zoho redesign the roster panel. No alerting. Mitigation: fixture HTML stored under `docs/handoffs/29-fixtures/`.
- **User closes participants panel mid-meeting** — roster stops receiving updates that tick but retains what it saw earlier (additive-only accumulation).

### Concurrency model
All roster mutations run on the daemon's single asyncio event loop — no locks, no threads. Documented in `ParticipantRoster` docstring.

## 6. Testing strategy

### Test file matrix

| File | Scope | New / extended |
|---|---|---|
| `tests/test_roster.py` | `ParticipantRoster` unit tests | **new** |
| `tests/test_enrichment.py` | `extract_zoom_participants` unit tests | extended |
| `tests/test_recorder_finalize.py` | Recorder stop-seam callback contract | **new** |
| `tests/test_detector.py` | Detector session lifecycle + three-source wiring | extended |
| `tests/test_daemon_server.py` | `/api/meeting-participants-updated` HTTP contract | extended |
| `tests/test_extension_lockstep.py` | Manifest / background / options / BUILT_IN_HOSTS agreement | **new** |
| `tests/test_unscheduled_enrichment_integration.py` | End-to-end spontaneous → populated frontmatter | **new** |

### Representative coverage

**`test_roster.py`** (10): empty merge returns False; first merge True + ordered; same/same-case returns False; same/different-case returns True + display upgrade; new names appended; whitespace skipped; naive datetime raises ValueError; `_last_merge_per_source` updates; `current()` == `finalize()`; multi-source ordering preserved.

**`test_enrichment.py` (Zoom additions)** (5): success case; no-matches → None; UIA exception → None; module-import failure → None; empty pane → None.

**`test_recorder_finalize.py`** (8): finalize called; after_stop called after finalize; finalize raises → logged + continues; after_stop raises → logged + continues; empty → no rewrite; same-as-initial → no rewrite; new list → rewrite once; audio_warnings + new participants → single combined rewrite.

**`test_detector.py` (additions)** (12): begin_session only after successful start; failed start doesn't leak; both hooks registered; end_session clears all three; stop via API + finalize/cleanup; stop via silence-timeout; stop via extension-ended uses on_after_stop; Teams path seeds + idempotent; Zoom path 10-poll refresh; off-cycle polls skip; browser endpoint merges; browser stale tab_id silent no-op.

**`test_daemon_server.py` (additions)** (9): 401 no auth; 400 missing tabId; 400 missing participants; 400 not-a-list; filter non-string entries; truncate >100; ignored no active recording; ignored wrong tabId; accepted valid payload.

**`test_extension_lockstep.py`** (4): `BUILT_IN_HOSTS` ⊆ background defaults; options agree with background; `BUILT_IN_HOSTS` ⊆ manifest content_scripts; content_scripts ⊆ host_permissions. Plus one negative: `teams.microsoft.com` is NOT in BUILT_IN_HOSTS (documents the deliberate gap).

**`test_unscheduled_enrichment_integration.py`** (4 scenarios): Zoom spontaneous mocked UIA → frontmatter populated; Meet spontaneous mocked HTTP → populated; Zoho tranzpay variant → populated; Teams regression (existing unscheduled flow + Teams UIA) → no regression.

### Manual acceptance checklist

New `docs/handoffs/YYYY-MM-DD-29-acceptance.md` covers scenarios unit/integration can't: real UIA trees, real browser DOM, extension permission reload. 11 scenarios including Zoom/Meet/Zoho live calls, Teams regression, Teams-via-browser documented gap, panel-closed case, crash mid-recording, late-joiner under 30s latency.

### JS-side testing explicitly out of v1

No JS test framework in `extension/`. Selector correctness verified manually + fixture HTML under `docs/handoffs/29-fixtures/`.

## 7. Acceptance criteria coverage

| Issue AC | Covered by |
|---|---|
| AC1: Zoom spontaneous populates participants via UIA | `test_enrichment.py` + `test_detector.py` Zoom path + integration E2E |
| AC2: Meet/Zoho spontaneous populates via extension DOM | `test_daemon_server.py` + integration E2E + manual AC #3, #4 |
| AC3: Teams no regression | `test_detector.py` Teams path + manual AC #5 |
| AC4: Signal no regression | `test_detector.py` Signal assertion + existing Signal tests |
| AC5: Analysis prompt populated when extractor returned names | Existing `test_analyze.py` + integration E2E |
| AC6: Frontmatter non-empty when extractor returns names | Integration E2E + `test_recorder_finalize.py` |
| AC7: Per-platform integration tests | `test_unscheduled_enrichment_integration.py` (4 scenarios) |

## 8. Non-goals for v1

- WebSocket `participants_updated` broadcast — `merge() -> bool` is the seam; broadcast is an additive follow-up.
- DOM MutationObserver fast-path — would split browser/Zoom cadence models.
- Dynamic `chrome.scripting` content-script registration for user-added hosts.
- Voice fingerprinting, directory imports, `known_contacts` schema changes — tracked in #28.
- Teams UIA periodic refresh — issue's non-goal "don't change Teams enrichment."
- Zoom UIA hang mitigation via executor + `wait_for` — deferred per residual-risk analysis.
- JS unit test framework in `extension/`.

## 9. Future-compat seams preserved

- `ParticipantRoster.merge() -> bool` → future `participants_updated` WS broadcast is a 3-line addition in the detector, no roster redesign.
- `observed_at` retained per source → future "roster at time T" reconstruction or diarization weighting.
- Separate `finalize()` method → future finalization logic (diarization reconciliation) hooks here without callers changing.
- `source` string naming convention `"<platform>_<mechanism>"` → future per-source trust/confidence scoring for diarization.
- `BUILT_IN_HOSTS` constant + lockstep test → future host additions land in one place, test fails until three configs are updated in sync.
