# Phase 4: Plugin Parity + Extension Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the Phase 3 transitional gaps (extension on Bearer, legacy routes deleted) and build the missing plugin surface (daemon-backed notification history, settings UI, speaker audio preview, vault-scan narrowing, silent-catch elimination).

**Architecture:** Observability vertical slice first (Group 1): daemon `/api/events` endpoint + plugin journal-backed `NotificationHistory` refactor + extension Bearer auth. Legacy route deletion lands immediately after (Group 2) to close the Phase 3 transitional gap. Config API (Group 3) introduces an explicit `ApiConfig` DTO module with ruamel round-trip PATCH and four pure translation functions. Feature parity (Group 4) adds audio clip endpoint + speaker modal + list narrowing. Closeout (Group 5) is integration test + manual acceptance + MANIFEST.

**Tech Stack:** Python 3.10+, aiohttp, ruamel.yaml (new dep), TypeScript (Svelte plugin), JavaScript (MV3 extension), ffmpeg (libmp3lame for clip extraction), existing pytest + `EventJournal`/`PairingWindow`/`Daemon` from Phase 3.

**Read before starting:**
- `docs/plans/2026-04-14-phase4-plugin-parity-design.md` — full design for this plan. Section 2 is load-bearing for every task.
- `docs/plans/2026-04-14-fix-everything-design.md` §Phase 4 (lines 294-347) — parent design.
- `docs/plans/2026-04-14-phase3-runtime-foundation.md` — Phase 3 is complete (commit `9f5cf3b`). Do NOT modify Phase 2 frozen code (EventIndex, OrgConfig.resolve_subfolder, resolve_note_path, to_vault_relative). Phase 3's frozen contracts: `EventJournal.{append, tail, subscribe, prune_old_backups}`, `Daemon.{start, stop, emit_event, run_in_loop, port, pairing}`, `PairingWindow.{open, consume, check_timeout, is_open, current_token}`.

**Baseline commit:** `7f860c2` (Phase 4 design doc committed on top of `9f5cf3b`). Test suite at 477.

---

## Conventions for every task

- Commit style: Conventional Commits (`feat:`, `refactor:`, `fix:`, `test:`, `chore:`, `docs:`).
- Never stage `uv.lock` or `docs/reviews/`.
- Run `uv run pytest -q` at the end of every Python-touching task; regressions are real.
- Prefer real filesystems via `tmp_path` over mocks. Network tests may mock at the framework boundary.
- Tests for new Python modules live in files mirroring the module name (`tests/test_api_config.py`, `tests/test_api_events.py`, `tests/test_clip_endpoint.py`).
- Plugin TypeScript changes: run `npm run build` inside `obsidian-recap/` to catch tsc errors before committing.
- Extension JavaScript changes: no test runner; verify via the manual acceptance checklist at Task 17.
- When a task migrates a call site or API, migrate ALL call sites in the same task — no half-migrated state.

---

## Task 1: `/api/events` endpoint + microsecond journal precision

**Context:** Plugin notification history (Task 3) needs a backfill endpoint. Plugin connects → `GET /api/events?limit=100` → renders most recent 100 entries. On WS reconnect → `GET /api/events?since=<last_seen_ts>` for gap fill. Also: bump `EventJournal.append()` timestamps to microsecond precision so `since` filtering is collision-safe.

**Files:**
- Modify: `recap/daemon/events.py` (microsecond timestamp)
- Modify: `recap/daemon/server.py` (new `_api_events` handler + route registration)
- Modify: `tests/test_event_journal.py` (update test for microsecond precision)
- Create: `tests/test_api_events.py`

**Step 1: Update `EventJournal.append()` timestamp precision**

In `recap/daemon/events.py` around line 80, change the `ts` line. Drop the `timespec="seconds"` kwarg so `datetime.isoformat()` defaults to microseconds.

**Step 2: Update `test_append_writes_one_line_per_entry`**

In `tests/test_event_journal.py`, after the existing assertions add `assert "." in e0["ts"]` to pin microsecond precision.

Run: `uv run pytest tests/test_event_journal.py -v` → all pass (existing tests tolerate the format change).

**Step 3: Write failing `/api/events` tests**

Create `tests/test_api_events.py` with `TestApiEvents` class containing:
- `test_returns_empty_list_when_no_journal_entries` — empty journal → `{"entries": []}`.
- `test_returns_entries_ascending` — 3 appends → response ascending by ts.
- `test_limit_caps_results` — 10 appends, limit=3 → returns most-recent 3 ascending (`m7`, `m8`, `m9`).
- `test_since_filters_strictly_after` — capture `middle_ts`, append 2 more, query with `since=middle_ts` → only the 2 later entries.
- `test_malformed_since_returns_400` — `since=not-a-timestamp` → 400.
- `test_malformed_limit_returns_400` — `limit=not-a-number` → 400.
- `test_limit_out_of_range_is_clamped` — `limit=9999` → 200; `limit=0` → 200.
- `test_requires_bearer` — no auth → 401.

Each test uses the `daemon_client` fixture and Bearer header `f"Bearer {daemon.config.auth_token}"`. Between the middle and later appends, call `time.sleep(0.01)` to ensure a distinct microsecond.

**Step 4: Run to verify failure**

Run: `uv run pytest tests/test_api_events.py -v`
Expected: FAIL — route does not exist.

**Step 5: Implement the handler**

In `recap/daemon/server.py`, add near the other `_api_*` handlers:

```python
from datetime import datetime

_MAX_EVENTS_LIMIT = 500
_DEFAULT_EVENTS_LIMIT = 100


async def _api_events(request: web.Request) -> web.Response:
    daemon: Daemon = request.app["daemon"]

    limit_str = request.query.get("limit", str(_DEFAULT_EVENTS_LIMIT))
    try:
        limit = int(limit_str)
    except ValueError:
        return web.json_response({"error": "limit must be an integer"}, status=400)
    limit = max(1, min(_MAX_EVENTS_LIMIT, limit))

    since_str = request.query.get("since")
    since_dt = None
    if since_str is not None:
        try:
            since_dt = datetime.fromisoformat(since_str)
        except ValueError:
            return web.json_response(
                {"error": "since must be RFC3339 timestamp"}, status=400,
            )

    raw_entries = daemon.event_journal.tail(limit=_MAX_EVENTS_LIMIT)
    filtered = []
    for entry in raw_entries:
        ts_str = entry.get("ts")
        if not isinstance(ts_str, str):
            continue
        try:
            entry_dt = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        if since_dt is not None and entry_dt <= since_dt:
            continue
        filtered.append(entry)

    result = filtered[-limit:] if len(filtered) > limit else filtered
    return web.json_response({"entries": result})
```

Register in the Authenticated API block: `app.router.add_get("/api/events", _api_events)`.

**Step 6: Run tests**

Run: `uv run pytest tests/test_api_events.py tests/test_event_journal.py -v` → PASS.
Run: `uv run pytest -q` → full suite passes.

**Step 7: Commit**

```bash
git add recap/daemon/events.py recap/daemon/server.py tests/test_api_events.py tests/test_event_journal.py
git commit -m "feat: /api/events backfill endpoint; microsecond journal precision"
```

---

## Task 2: Plugin `api.ts` — `tailEvents`, `onJournalEntry`, DaemonStatus sync

**Context:** `DaemonClient` needs `tailEvents(since?, limit?)` and `onJournalEntry(handler)` for notification history. Also updates the stale `DaemonStatus` interface to match Phase 3's actual response shape (adds `uptime_seconds`, `recent_errors`).

**Files:** Modify `obsidian-recap/src/api.ts`.

**Step 1: Read `api.ts`** to locate the existing `DaemonStatus` interface, event-handler registry, `get<T>` helper, and WS `onmessage` dispatch.

**Step 2: Update `DaemonStatus`**

Replace the existing interface with:

```typescript
export interface DaemonStatus {
    uptime_seconds: number;
    recent_errors: DaemonEvent[];
    // Legacy (kept for back-compat; mirror new fields):
    state: "idle" | "armed" | "detected" | "recording" | "processing";
    recording: { path: string; org: string } | null;
    daemon_uptime: number;
    last_calendar_sync: string | null;
    errors: string[];
}

export interface JournalEntry {
    ts: string;
    level: "info" | "warning" | "error";
    event: string;
    message: string;
    payload?: Record<string, unknown>;
}
```

**Step 3: Add two methods on `DaemonClient`**

```typescript
async tailEvents(since?: string, limit?: number): Promise<JournalEntry[]> {
    const params = new URLSearchParams();
    if (since !== undefined) params.set("since", since);
    if (limit !== undefined) params.set("limit", String(limit));
    const query = params.toString();
    const path = query ? `/api/events?${query}` : "/api/events";
    const resp = await this.get<{ entries: JournalEntry[] }>(path);
    return resp.entries;
}

onJournalEntry(handler: (entry: JournalEntry) => void): () => void {
    const dispatch = (event: DaemonEvent) => {
        const entry = (event as { entry?: JournalEntry }).entry;
        if (entry) handler(entry);
    };
    return this.on("journal_entry", dispatch);
}
```

If `this.on(eventName, handler)` does not already return an unsubscribe fn, update the registry's `on` helper: push to `eventHandlers`, return a function that removes via `indexOf`/`splice`.

**Step 4: Verify build**

Run: `cd obsidian-recap && npm run build` → zero tsc errors.

**Step 5: Commit**

```bash
git add obsidian-recap/src/api.ts
git commit -m "feat(plugin): tailEvents + onJournalEntry; update DaemonStatus type"
```

---

## Task 3: Plugin `notificationHistory.ts` — daemon-backed refactor

**Context:** Today `notificationHistory.ts:11` holds an in-memory `notifications: RecapNotification[]`. Task 3 replaces it with a thin renderer: `load()` calls `tailEvents(undefined, 100)`, `subscribe()` uses `onJournalEntry`. Removes `main.ts:295`-area synthesis of notifications from `state_change` events. `add()` method is deleted (§0.4: plugin never writes to daemon journal).

**Files:**
- Modify: `obsidian-recap/src/notificationHistory.ts`
- Modify: `obsidian-recap/src/main.ts` (remove synthesis; wire `setClient` / `detach`)

**Step 1: Read both files** in full. In `main.ts`, locate every `this.notificationHistory.add(...)` site and the state_change synthesis block near line 295.

**Step 2: Rewrite `notificationHistory.ts`**

Full replacement:

```typescript
import { Modal, App, Notice } from "obsidian";
import { DaemonClient, JournalEntry } from "./api";

export interface RecapNotification {
    timestamp: string;
    type: "info" | "warning" | "error";
    title: string;
    message: string;
}

function entryToNotification(entry: JournalEntry): RecapNotification {
    const payload = entry.payload as { title?: string } | undefined;
    const title = payload?.title ?? entry.event.replace(/_/g, " ");
    return { timestamp: entry.ts, type: entry.level, title, message: entry.message };
}

export class NotificationHistory {
    private client: DaemonClient | null = null;
    private cache: RecapNotification[] = [];
    private unsubscribe: (() => void) | null = null;
    private readonly maxSize = 100;
    private listeners: Array<() => void> = [];

    setClient(client: DaemonClient | null): void {
        if (this.unsubscribe) { this.unsubscribe(); this.unsubscribe = null; }
        this.client = client;
        this.cache = [];
        if (client) {
            void this.load();
            this.unsubscribe = client.onJournalEntry((entry) => {
                this.cache.push(entryToNotification(entry));
                if (this.cache.length > this.maxSize) {
                    this.cache.splice(0, this.cache.length - this.maxSize);
                }
                this.notifyListeners();
            });
        }
    }

    async load(): Promise<void> {
        if (!this.client) return;
        try {
            const entries = await this.client.tailEvents(undefined, this.maxSize);
            this.cache = entries.map(entryToNotification);
            this.notifyListeners();
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: notification history backfill failed — ${msg}`);
            console.error("Recap:", e);
        }
    }

    getAll(): RecapNotification[] { return [...this.cache]; }

    subscribe(callback: () => void): () => void {
        this.listeners.push(callback);
        return () => {
            const idx = this.listeners.indexOf(callback);
            if (idx >= 0) this.listeners.splice(idx, 1);
        };
    }

    detach(): void {
        if (this.unsubscribe) { this.unsubscribe(); this.unsubscribe = null; }
        this.client = null;
        this.cache = [];
        this.notifyListeners();
    }

    private notifyListeners(): void {
        for (const cb of this.listeners) {
            try { cb(); } catch (e) { console.error("Recap:", e); }
        }
    }
}

export class NotificationHistoryModal extends Modal {
    constructor(app: App, private history: NotificationHistory) { super(app); }

    onOpen(): void {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.createEl("h2", { text: "Recap notifications" });
        const list = contentEl.createEl("div", { cls: "recap-notification-list" });
        const entries = this.history.getAll().slice().reverse();
        if (entries.length === 0) {
            list.createEl("p", { text: "No notifications yet." });
            return;
        }
        for (const n of entries) {
            const row = list.createEl("div", { cls: `recap-notif recap-notif-${n.type}` });
            row.createEl("span", { cls: "recap-notif-time", text: n.timestamp });
            row.createEl("strong", { text: n.title });
            row.createEl("span", { text: n.message });
        }
    }

    onClose(): void { this.contentEl.empty(); }
}
```

**Step 3: Update `main.ts`**

1. Delete every `this.notificationHistory.add(...)` call (the method no longer exists).
2. Delete the notification-synthesis logic inside the state_change handler near line 295. Keep the status-bar update and live-transcript update — those are legitimately driven by state_change. The notification entries are now produced by the daemon journal and streamed to the plugin via WS.
3. After `this.client = new DaemonClient(...)`, add `this.notificationHistory.setClient(this.client);`.
4. Before `this.client = null` (on disconnect/unload), add `this.notificationHistory.detach();`.

**Step 4: Verify build**

Run: `cd obsidian-recap && npm run build` → zero errors.

**Step 5: Commit**

```bash
git add obsidian-recap/src/notificationHistory.ts obsidian-recap/src/main.ts
git commit -m "refactor(plugin): notification history is daemon-backed renderer"
```

---

## Task 4: Extension `options.html` + `options.js` pairing UI

**Context:** Options page grows a new "Daemon connection" section above the existing patterns UI. Daemon URL input validated loopback-only, normalized on save. Connect button calls `/bootstrap/token` with 1s timeout. Stores `recapAuth = {token, baseUrl, pairedAt}`. Listens to `chrome.storage.onChanged` for cross-context sync. When baseUrl changes, clears token.

**Files:**
- Modify: `extension/options.html`
- Modify: `extension/options.js`

**Step 1: Read current state** of both files. Existing pattern UI stays intact.

**Step 2: Add auth section to `options.html`** ABOVE the `#patterns` container:

```html
<section id="auth-section">
  <h2>Daemon connection</h2>
  <div class="form-row">
    <label for="base-url-input">Daemon URL:</label>
    <input type="text" id="base-url-input" placeholder="http://localhost:9847" />
  </div>
  <p id="base-url-error" class="error-msg" hidden></p>
  <div class="form-row">
    <button id="save-url-btn">Save URL</button>
    <button id="connect-btn">Connect</button>
    <button id="disconnect-btn" hidden>Disconnect</button>
  </div>
  <p id="auth-status" class="status-msg">Not paired.</p>
</section>
```

**Step 3: Rewrite `options.js`** to add the auth flow alongside the existing pattern-list logic.

Key additions (keep the existing pattern logic unchanged; wrap it with auth code):

```javascript
const DEFAULT_BASE_URL = "http://localhost:9847";
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

const baseUrlInput = document.getElementById("base-url-input");
const baseUrlError = document.getElementById("base-url-error");
const saveUrlBtn = document.getElementById("save-url-btn");
const connectBtn = document.getElementById("connect-btn");
const disconnectBtn = document.getElementById("disconnect-btn");
const authStatus = document.getElementById("auth-status");

function normalizeBaseUrl(raw) {
    return raw.trim().replace(/\/+$/, "");
}

function validateLoopbackUrl(raw) {
    try {
        const url = new URL(raw);
        if (!LOOPBACK_HOSTS.has(url.hostname)) {
            return `host must be loopback; got ${url.hostname}`;
        }
        return null;
    } catch (e) {
        return `invalid URL: ${e.message}`;
    }
}

function setAuthStatus(text, variant) {
    authStatus.textContent = text;
    authStatus.dataset.variant = variant || "neutral";
}

function renderAuthState(auth) {
    if (auth && auth.token) {
        const when = new Date(auth.pairedAt).toLocaleString();
        setAuthStatus(`Connected (paired ${when}).`, "ok");
        connectBtn.hidden = true;
        disconnectBtn.hidden = false;
    } else {
        setAuthStatus("Not paired.", "neutral");
        connectBtn.hidden = false;
        disconnectBtn.hidden = true;
    }
}

async function loadAuth() {
    const result = await chrome.storage.local.get("recapAuth");
    const auth = result.recapAuth || null;
    baseUrlInput.value = (auth && auth.baseUrl) || DEFAULT_BASE_URL;
    renderAuthState(auth);
}

async function saveBaseUrl() {
    const raw = baseUrlInput.value;
    const err = validateLoopbackUrl(raw);
    baseUrlError.textContent = err || "";
    baseUrlError.hidden = !err;
    if (err) return;
    const normalized = normalizeBaseUrl(raw);
    baseUrlInput.value = normalized;

    const existing = (await chrome.storage.local.get("recapAuth")).recapAuth || {};
    if (existing.baseUrl !== normalized) {
        await chrome.storage.local.set({ recapAuth: { baseUrl: normalized } });
    }
    renderAuthState({ baseUrl: normalized });
}

async function connect() {
    const existing = (await chrome.storage.local.get("recapAuth")).recapAuth || {};
    const baseUrl = existing.baseUrl || DEFAULT_BASE_URL;
    setAuthStatus("Pairing…", "neutral");

    let resp;
    try {
        resp = await fetch(`${baseUrl}/bootstrap/token`, {
            signal: AbortSignal.timeout(1000),
        });
    } catch (e) {
        setAuthStatus(`Daemon unreachable: ${e.message}`, "error");
        return;
    }

    if (resp.status === 404) {
        setAuthStatus(
            "Pairing window not open. Right-click the Recap tray icon → "
            + "“Pair browser extension…”, then click Connect.",
            "warning",
        );
        return;
    }
    if (resp.status === 403) {
        setAuthStatus("Pairing rejected (non-loopback).", "error");
        return;
    }
    if (!resp.ok) {
        setAuthStatus(`Pairing failed: HTTP ${resp.status}`, "error");
        return;
    }

    const body = await resp.json();
    if (!body.token) {
        setAuthStatus("Pairing response missing token.", "error");
        return;
    }
    const auth = { token: body.token, baseUrl, pairedAt: Date.now() };
    await chrome.storage.local.set({ recapAuth: auth });
    renderAuthState(auth);
}

async function disconnect() {
    await chrome.storage.local.remove("recapAuth");
    renderAuthState(null);
}

saveUrlBtn.addEventListener("click", saveBaseUrl);
connectBtn.addEventListener("click", connect);
disconnectBtn.addEventListener("click", disconnect);

chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !changes.recapAuth) return;
    const newAuth = changes.recapAuth.newValue || null;
    if (newAuth) baseUrlInput.value = newAuth.baseUrl || DEFAULT_BASE_URL;
    renderAuthState(newAuth);
});

loadAuth();
```

Preserve the existing `DEFAULT_PATTERNS`, `PLATFORMS`, pattern rendering, `add-btn`, `save-btn`, `reset-btn`, `remove-btn` logic exactly as-is. The `load()` call at the bottom should be renamed `loadPatterns()` if it previously only loaded patterns; call both `loadAuth()` and `loadPatterns()` on init.

**Step 4: Manual verification** (for the checklist at Task 17) — pair succeeds, non-loopback URL rejected, 404 message shown when tray pairing not opened, baseUrl change clears token.

**Step 5: Commit**

```bash
git add extension/options.html extension/options.js
git commit -m "feat(extension): pairing UI with loopback validation and token storage"
```

---

## Task 5: Extension `background.js` Bearer auth

**Context:** Service worker reads `recapAuth`, sends `Authorization: Bearer <token>` on `/api/meeting-detected` + `/api/meeting-ended`. `authReady` promise resolves the MV3 wake-up race: `notifyRecap()` awaits it before first call. `/health` stays unauth. 401 clears stored token.

**Files:** Modify `extension/background.js`.

**Step 1: Replace the whole file** with:

```javascript
const DEFAULT_BASE_URL = "http://localhost:9847";

const DEFAULT_MEETING_PATTERNS = [
  { pattern: "meet.google.com/", platform: "google_meet", excludeExact: "meet.google.com/" },
  { pattern: "teams.microsoft.com/", platform: "teams", requirePath: ["meetup-join", "pre-join"] },
  { pattern: "meeting.zoho.com/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.eu/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.in/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.zoho.com.au/meeting/", platform: "zoho_meet" },
  { pattern: "meeting.tranzpay.io/", platform: "zoho_meet" },
];

let cachedAuth = null;
let daemonReachable = false;
let activeMeetingTabs = new Map();

const authReady = (async () => {
  const result = await chrome.storage.local.get("recapAuth");
  cachedAuth = result.recapAuth || null;
})();

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || !changes.recapAuth) return;
  cachedAuth = changes.recapAuth.newValue || null;
  void findRecapDaemon();
});

function currentBaseUrl() {
  return (cachedAuth && cachedAuth.baseUrl) || DEFAULT_BASE_URL;
}

function setBadge(state) {
  if (state === "connected") {
    chrome.action.setBadgeBackgroundColor({ color: "#4baa55" });
    chrome.action.setBadgeText({ text: "ON" });
    chrome.action.setTitle({ title: "Recap - Connected" });
  } else if (state === "auth") {
    chrome.action.setBadgeBackgroundColor({ color: "#d9534f" });
    chrome.action.setBadgeText({ text: "AUTH" });
    chrome.action.setTitle({ title: "Recap - Not paired. Open options to connect." });
  } else {
    chrome.action.setBadgeBackgroundColor({ color: "#7a8493" });
    chrome.action.setBadgeText({ text: "" });
    chrome.action.setTitle({ title: "Recap - Not connected" });
  }
}

async function findRecapDaemon() {
  await authReady;
  const baseUrl = currentBaseUrl();
  try {
    const resp = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(1000) });
    if (resp.ok) {
      daemonReachable = true;
      setBadge(cachedAuth && cachedAuth.token ? "connected" : "auth");
      return true;
    }
  } catch (_) {}
  daemonReachable = false;
  setBadge("offline");
  return false;
}

async function getMeetingPatterns() {
  const result = await chrome.storage.local.get("meetingPatterns");
  return result.meetingPatterns || DEFAULT_MEETING_PATTERNS;
}

function matchesMeetingUrl(url, patterns) {
  try {
    const parsed = new URL(url);
    const fullUrl = parsed.hostname + parsed.pathname;
    for (const rule of patterns) {
      if (!fullUrl.includes(rule.pattern)) continue;
      if (rule.excludeExact && fullUrl === rule.excludeExact) continue;
      if (rule.requirePath && !rule.requirePath.some((p) => parsed.pathname.includes(p))) continue;
      return rule.platform;
    }
  } catch (_) {}
  return null;
}

async function notifyRecap(endpoint, data) {
  await authReady;
  if (!cachedAuth || !cachedAuth.token) {
    console.warn("Recap: not paired; skipping", endpoint);
    setBadge("auth");
    return;
  }
  if (!daemonReachable) await findRecapDaemon();
  if (!daemonReachable) return;

  const url = `${currentBaseUrl()}${endpoint}`;
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${cachedAuth.token}`,
      },
      body: JSON.stringify(data),
    });
    if (resp.status === 401) {
      console.warn("Recap: 401; clearing stored token");
      await chrome.storage.local.remove("recapAuth");
      setBadge("auth");
      return;
    }
    if (!resp.ok) {
      console.warn(`Recap: ${endpoint} returned ${resp.status}`);
    }
  } catch (e) {
    console.warn("Recap:", endpoint, "failed:", e.message);
    daemonReachable = false;
    setBadge("offline");
  }
}

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url) return;
  const patterns = await getMeetingPatterns();
  const platform = matchesMeetingUrl(tab.url, patterns);
  if (platform && !activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.set(tabId, { url: tab.url, title: tab.title, platform });
    await notifyRecap("/api/meeting-detected", {
      url: tab.url, title: tab.title || "Meeting", platform, tabId,
    });
  } else if (!platform && activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.delete(tabId);
    await notifyRecap("/api/meeting-ended", { tabId });
  }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  if (activeMeetingTabs.has(tabId)) {
    activeMeetingTabs.delete(tabId);
    await notifyRecap("/api/meeting-ended", { tabId });
  }
});

chrome.alarms.create("recap-health-check", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "recap-health-check") void findRecapDaemon();
});

void findRecapDaemon();
```

**Step 2: Manual verification** (for Task 17 checklist) — badge states: offline / AUTH / connected; meeting detection sends Bearer POST; 401 clears token.

**Step 3: Commit**

```bash
git add extension/background.js
git commit -m "feat(extension): Bearer auth on /api/meeting-*; authReady closes MV3 race"
```

---

## Task 6: Daemon — delete transitional `/meeting-detected` + `/meeting-ended` routes

**Context:** Extension is now on Bearer (Task 5). Delete the transitional unauth route registrations, the "Transitional: remove in Phase 4" comment, and `TestLegacyMeetingRoutesStillWork`. Lands IMMEDIATELY after Task 5.

**Files:**
- Modify: `recap/daemon/server.py`
- Modify: `tests/test_daemon_server.py`
- Modify: `MANIFEST.md`

**Step 1:** In `server.py`, find the `# Transitional: remove in Phase 4` block. Remove the comment AND the two `app.router.add_post("/meeting-detected", ...)` and `app.router.add_post("/meeting-ended", ...)` registrations. Keep the `_meeting_detected_api` / `_meeting_ended_api` handlers — they're still registered at the `/api/` paths.

**Step 2:** Delete `TestLegacyMeetingRoutesStillWork` from `tests/test_daemon_server.py`.

**Step 3:** Add a regression guard class `TestLegacyRoutesDeleted` with two tests: POST `/meeting-detected` returns 404; POST `/meeting-ended` returns 404.

**Step 4:** Update `MANIFEST.md` to remove any "transitional route" caveat.

**Step 5:** Run: `uv run pytest -q` → all pass.

**Step 6: Commit**

```bash
git add recap/daemon/server.py tests/test_daemon_server.py MANIFEST.md
git commit -m "refactor: delete transitional /meeting-detected and /meeting-ended routes"
```

---

## Task 7: Plugin silent-catch elimination

**Context:** Replace every `catch {}`, `catch (e) {}`, and log-only catch in plugin code with `Notice` + `console.error`. Plugin-local errors do NOT write to the daemon journal (§0.4).

**Files:**
- Modify: `obsidian-recap/src/main.ts`
- Modify: `obsidian-recap/src/renameProcessor.ts`
- Modify: `obsidian-recap/src/api.ts` (any fetch/WS error paths missing user surface)

**Step 1: Grep targets**

```bash
cd obsidian-recap/src
grep -rn "catch *{}\|catch *(e) *{}\|catch *(e) *{ *console\." . --include="*.ts"
```

Also skim for `try {} catch (e) { console.error(e); }` without a `Notice`.

**Step 2: Replacement pattern.** For each hit:

```typescript
} catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    new Notice(`Recap: <action description> failed — ${msg}`);
    console.error("Recap:", e);
}
```

Action description examples:
- `main.ts:readAuthToken` → "could not read auth token"
- `main.ts:reconnect` → "reconnection to daemon failed"
- `main.ts:file-open` → "could not open meeting note"
- `main.ts:activateView` → "could not activate view"
- `main.ts:289` (status refresh) → "daemon status refresh failed"
- `renameProcessor.ts:*` → "rename processing failed"

Ensure `import { Notice } from "obsidian";` is present in every touched file.

**Step 3: Verify zero silent catches.** Re-run the Step 1 grep → 0 hits.

**Step 4: Build.** `cd obsidian-recap && npm run build` → zero tsc errors.

**Step 5: Commit**

```bash
git add obsidian-recap/src/main.ts obsidian-recap/src/renameProcessor.ts obsidian-recap/src/api.ts
git commit -m "refactor(plugin): eliminate silent catches; route errors to Notice + console"
```

---

## Task 8: Daemon `api_config.py` module + `/api/config` GET

**Context:** New `recap/daemon/api_config.py` with `ApiConfig` DTO + four translation functions. Add `parse_daemon_config_dict()` to `config.py`. Add `config_path` + `config_lock` to `Daemon`. Wire `/api/config` GET.

**Files:**
- Create: `recap/daemon/api_config.py`
- Modify: `recap/daemon/config.py` (add `parse_daemon_config_dict`)
- Modify: `recap/daemon/service.py` (add `config_path`, `config_lock`)
- Modify: `recap/daemon/__main__.py` (pass `config_path` to `Daemon`)
- Modify: `recap/daemon/server.py` (add handler + route)
- Modify: `pyproject.toml` (add `ruamel.yaml>=0.18`)
- Modify: `tests/conftest.py` (make `daemon_client` fixture create a real config file)
- Create: `tests/test_api_config.py`

**Step 1: Add the ruamel dependency**

In `pyproject.toml`, under `[project].dependencies`, add `"ruamel.yaml>=0.18"`. Run `uv sync`. Verify: `uv run python -c "import ruamel.yaml; print(ruamel.yaml.__version__)"`.

**Step 2: Extract `parse_daemon_config_dict` in `config.py`**

In `recap/daemon/config.py`, find `load_daemon_config()` (around line 164). Move the parsing logic (everything after `yaml.safe_load`) into a new pure function:

```python
def parse_daemon_config_dict(raw: dict[str, Any]) -> DaemonConfig:
    """Parse a raw config dict into a DaemonConfig. Raises ValueError on failure."""
    # existing validation + object construction
    ...

def load_daemon_config(path: pathlib.Path) -> DaemonConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping; got {type(raw).__name__}")
    return parse_daemon_config_dict(raw)
```

**Step 3: Write failing tests**

Create `tests/test_api_config.py` with the following test classes:

- `TestYamlDocLoad`
  - `test_load_preserves_comments` — writes YAML with top-of-file comment, loads, confirms `isinstance(doc, CommentedMap)`.
- `TestYamlDocToApiConfig`
  - `test_returns_allowlisted_fields` — writes YAML with `auth_token` at top level + orgs/detection/calendar/known_contacts/recording/logging; loads; calls `yaml_doc_to_api_config`; asserts `api.vault_path`, `api.orgs[0].name`, `api.default_org` (derived from `orgs[].default`); asserts `"auth_token" not in dir(api)`.
- `TestApiConfigGet`
  - `test_returns_sanitized_config` — GET `/api/config` with Bearer → 200 → body contains `vault_path`, `plugin_port` but NOT `auth_token`.
  - `test_requires_bearer` — no auth → 401.

**Step 4: Run to verify failure**

Run: `uv run pytest tests/test_api_config.py -v` → FAIL (module doesn't exist).

**Step 5: Create `recap/daemon/api_config.py`**

```python
"""API DTO + translation layer for /api/config (design §2.3)."""
from __future__ import annotations

import dataclasses
import pathlib
from dataclasses import dataclass, field
from typing import Any, Optional

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


@dataclass
class ApiOrgConfig:
    name: str
    subfolder: str
    default: bool = False


@dataclass
class ApiDetectionRule:
    enabled: bool
    behavior: str
    default_org: Optional[str] = None
    default_backend: Optional[str] = None


@dataclass
class ApiCalendarProvider:
    enabled: bool
    calendar_id: Optional[str] = None
    org: Optional[str] = None


@dataclass
class ApiKnownContact:
    name: str
    aliases: list[str] = field(default_factory=list)
    email: Optional[str] = None


@dataclass
class ApiConfig:
    vault_path: str
    recordings_path: str
    plugin_port: int
    orgs: list[ApiOrgConfig]
    detection: dict[str, ApiDetectionRule]
    calendar: dict[str, ApiCalendarProvider]
    known_contacts: list[ApiKnownContact]
    recording_silence_timeout_minutes: int
    recording_max_duration_hours: float
    logging_retention_days: int
    user_name: Optional[str] = None
    default_org: Optional[str] = None


def _rt_yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    return y


def load_yaml_doc(path: pathlib.Path) -> CommentedMap:
    y = _rt_yaml()
    with path.open("r", encoding="utf-8") as f:
        doc = y.load(f)
    if doc is None:
        return CommentedMap()
    if not isinstance(doc, CommentedMap):
        raise ValueError(f"config root must be a mapping; got {type(doc).__name__}")
    return doc


def dump_yaml_doc(doc: CommentedMap, fh) -> None:
    _rt_yaml().dump(doc, fh)


def _to_str(v: Any, field_name: str) -> str:
    if not isinstance(v, str):
        raise ValueError(f"{field_name} must be a string")
    return v


def _get(d: Any, key: str, default: Any = None) -> Any:
    if isinstance(d, (CommentedMap, dict)):
        return d.get(key, default)
    return default


def yaml_doc_to_api_config(doc: CommentedMap) -> ApiConfig:
    orgs: list[ApiOrgConfig] = []
    for item in _get(doc, "orgs", []) or []:
        orgs.append(ApiOrgConfig(
            name=_to_str(_get(item, "name", ""), "orgs[].name"),
            subfolder=_to_str(_get(item, "subfolder", ""), "orgs[].subfolder"),
            default=bool(_get(item, "default", False)),
        ))

    detection: dict[str, ApiDetectionRule] = {}
    for platform, cfg in (_get(doc, "detection", {}) or {}).items():
        if cfg is None:
            continue
        detection[platform] = ApiDetectionRule(
            enabled=bool(_get(cfg, "enabled", False)),
            behavior=_to_str(_get(cfg, "behavior", "prompt"),
                             f"detection.{platform}.behavior"),
            default_org=_get(cfg, "default_org"),
            default_backend=_get(cfg, "default_backend"),
        )

    calendar: dict[str, ApiCalendarProvider] = {}
    for provider, cfg in (_get(doc, "calendar", {}) or {}).items():
        if cfg is None:
            continue
        calendar[provider] = ApiCalendarProvider(
            enabled=bool(_get(cfg, "enabled", False)),
            calendar_id=_get(cfg, "calendar_id"),
            org=_get(cfg, "org"),
        )

    contacts: list[ApiKnownContact] = []
    for item in _get(doc, "known_contacts", []) or []:
        contacts.append(ApiKnownContact(
            name=_to_str(_get(item, "name", ""), "known_contacts[].name"),
            aliases=list(_get(item, "aliases", []) or []),
            email=_get(item, "email"),
        ))

    recording = _get(doc, "recording", {}) or {}
    logging_cfg = _get(doc, "logging", {}) or {}
    daemon_ports = _get(doc, "daemon_ports", {}) or {}
    derived_default_org = next((o.name for o in orgs if o.default), None)

    return ApiConfig(
        vault_path=_to_str(_get(doc, "vault_path", ""), "vault_path"),
        recordings_path=_to_str(_get(doc, "recordings_path", ""), "recordings_path"),
        plugin_port=int(_get(daemon_ports, "plugin_port", 9847)),
        orgs=orgs,
        detection=detection,
        calendar=calendar,
        known_contacts=contacts,
        recording_silence_timeout_minutes=int(_get(recording, "silence_timeout_minutes", 5)),
        recording_max_duration_hours=float(_get(recording, "max_duration_hours", 3)),
        logging_retention_days=int(_get(logging_cfg, "retention_days", 7)),
        user_name=_get(doc, "user_name"),
        default_org=derived_default_org,
    )


def api_config_to_json_dict(cfg: ApiConfig) -> dict[str, Any]:
    return dataclasses.asdict(cfg)
```

**Step 6: `Daemon.config_path` + `config_lock`**

In `recap/daemon/service.py`:

```python
import threading
import pathlib
from typing import Optional

class Daemon:
    def __init__(self, config: "DaemonConfig", *, config_path: Optional[pathlib.Path] = None):
        # existing body
        self.config_path = config_path
        self.config_lock = threading.Lock()
```

In `recap/daemon/__main__.py` `main()`, pass `config_path=config_path` when constructing `Daemon(cfg)`.

**Step 7: GET handler + route in `server.py`**

```python
from recap.daemon.api_config import (
    api_config_to_json_dict, load_yaml_doc, yaml_doc_to_api_config,
)


async def _api_config_get(request: web.Request) -> web.Response:
    daemon: Daemon = request.app["daemon"]
    if daemon.config_path is None:
        return web.json_response({"error": "config path not available"}, status=503)
    try:
        doc = load_yaml_doc(daemon.config_path)
        api = yaml_doc_to_api_config(doc)
    except (OSError, ValueError) as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response(api_config_to_json_dict(api))
```

Register: `app.router.add_get("/api/config", _api_config_get)`.

**Step 8: Update `tests/conftest.py`**

Extend `daemon_client` fixture so it writes a minimal real `config.yaml` to `tmp_path` and sets `daemon.config_path = tmp_path / "config.yaml"` before returning.

**Step 9: Run tests**

Run: `uv run pytest tests/test_api_config.py -v` → PASS.
Run: `uv run pytest -q` → full suite passes.

**Step 10: Commit**

```bash
git add recap/daemon/api_config.py recap/daemon/config.py recap/daemon/service.py recap/daemon/__main__.py recap/daemon/server.py pyproject.toml tests/test_api_config.py tests/conftest.py
git commit -m "feat: /api/config GET + api_config DTO module + ruamel dependency"
```

Do NOT stage `uv.lock`.

---

## Task 9: `/api/config` PATCH with ruamel round-trip

**Context:** Add `apply_api_patch_to_yaml_doc`, `find_unknown_keys`, `validate_yaml_doc` to `api_config.py`. Add `_api_config_patch` handler. Strict nested unknown-key validation. Whole-list replacement for `orgs` / `known_contacts`. Atomic write. Emits `config_updated` journal event.

**Files:**
- Modify: `recap/daemon/api_config.py`
- Modify: `recap/daemon/server.py`
- Modify: `tests/test_api_config.py`

**Step 1: Write failing PATCH tests** in `tests/test_api_config.py`:

- `TestApplyPatchToYamlDoc`
  - `test_scalar_patch_preserves_sibling_comments` — YAML with `# Important comment` and `# Another comment`, patch `{"vault_path": "/new"}`, dump, verify both comments still present.
  - `test_list_patch_is_whole_replacement` — YAML with 2 orgs, patch `{"orgs": [{"name": "gamma", "subfolder": "G", "default": true}]}`, verify `len(doc["orgs"]) == 1` and name is `gamma`.
- `TestFindUnknownKeys`
  - `test_top_level_unknown_key` — body `{"nope": 1}` → `find_unknown_keys` returns `["nope"]`.
  - `test_nested_detection_unknown_subfield_caught` — body `{"detection": {"google_meet": {"enabled": true, "bogus": 1}}}` → list contains `"detection.google_meet.bogus"`.
  - `test_orgs_entry_unknown_field` — body `{"orgs": [{"name": "x", "subfolder": "y", "default": true, "zzz": "nope"}]}` → list contains `"orgs[].zzz"`.
- `TestApiConfigPatch`
  - `test_patch_updates_config_yaml_and_preserves_comments` — inject a marker comment, PATCH `{"user_name": "NewName"}`, assert 200 + `restart_required: true` + file has both `NewName` and the comment.
  - `test_patch_unknown_top_level_key_returns_400` — `{"nonsense_field": true}` → 400.
  - `test_patch_unknown_nested_key_returns_400` — `{"detection": {"google_meet": {"enabled": true, "bogus_field": 1}}}` → 400.
  - `test_patch_default_org_rejected` — `{"default_org": "alpha"}` → 400.
  - `test_patch_non_dict_body_returns_400` — JSON array body → 400.
  - `test_patch_emits_config_updated_event` — after successful PATCH, journal contains `config_updated`.

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_api_config.py -v` → FAIL.

**Step 3: Extend `api_config.py`**

Append:

```python
_READ_ONLY_KEYS = frozenset({"default_org"})


def _field_names(cls) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def find_unknown_keys(body: dict[str, Any]) -> list[str]:
    unknown: list[str] = []
    top_allowed = _field_names(ApiConfig)

    for key, value in body.items():
        if key in _READ_ONLY_KEYS:
            unknown.append(f"{key} (read-only)")
            continue
        if key not in top_allowed:
            unknown.append(key)
            continue

        if key == "orgs" and isinstance(value, list):
            allowed = _field_names(ApiOrgConfig)
            for entry in value:
                if not isinstance(entry, dict):
                    continue
                for k in entry:
                    if k not in allowed:
                        unknown.append(f"orgs[].{k}")
        elif key == "detection" and isinstance(value, dict):
            allowed = _field_names(ApiDetectionRule)
            for platform, rule in value.items():
                if not isinstance(rule, dict):
                    continue
                for k in rule:
                    if k not in allowed:
                        unknown.append(f"detection.{platform}.{k}")
        elif key == "calendar" and isinstance(value, dict):
            allowed = _field_names(ApiCalendarProvider)
            for provider, cfg in value.items():
                if not isinstance(cfg, dict):
                    continue
                for k in cfg:
                    if k not in allowed:
                        unknown.append(f"calendar.{provider}.{k}")
        elif key == "known_contacts" and isinstance(value, list):
            allowed = _field_names(ApiKnownContact)
            for entry in value:
                if not isinstance(entry, dict):
                    continue
                for k in entry:
                    if k not in allowed:
                        unknown.append(f"known_contacts[].{k}")

    return unknown


def apply_api_patch_to_yaml_doc(doc: CommentedMap, patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if key in _READ_ONLY_KEYS:
            continue

        if key == "recording_silence_timeout_minutes":
            doc.setdefault("recording", CommentedMap())["silence_timeout_minutes"] = value
            continue
        if key == "recording_max_duration_hours":
            doc.setdefault("recording", CommentedMap())["max_duration_hours"] = value
            continue
        if key == "logging_retention_days":
            doc.setdefault("logging", CommentedMap())["retention_days"] = value
            continue
        if key == "plugin_port":
            doc.setdefault("daemon_ports", CommentedMap())["plugin_port"] = value
            continue

        if key == "orgs" and isinstance(value, list):
            new_list = CommentedSeq()
            for o in value:
                m = CommentedMap()
                m["name"] = o.get("name", "")
                m["subfolder"] = o.get("subfolder", "")
                m["default"] = bool(o.get("default", False))
                new_list.append(m)
            doc["orgs"] = new_list
            continue

        if key == "known_contacts" and isinstance(value, list):
            new_list = CommentedSeq()
            for kc in value:
                m = CommentedMap()
                m["name"] = kc.get("name", "")
                if "aliases" in kc:
                    m["aliases"] = list(kc["aliases"] or [])
                if "email" in kc:
                    m["email"] = kc["email"]
                new_list.append(m)
            doc["known_contacts"] = new_list
            continue

        if key == "detection" and isinstance(value, dict):
            det = doc.setdefault("detection", CommentedMap())
            for platform, rule in value.items():
                target = det.setdefault(platform, CommentedMap())
                for k in ("enabled", "behavior", "default_org", "default_backend"):
                    if k in rule:
                        target[k] = rule[k]
            continue

        if key == "calendar" and isinstance(value, dict):
            cal = doc.setdefault("calendar", CommentedMap())
            for provider, cfg in value.items():
                target = cal.setdefault(provider, CommentedMap())
                for k in ("enabled", "calendar_id", "org"):
                    if k in cfg:
                        target[k] = cfg[k]
            continue

        doc[key] = value


def validate_yaml_doc(doc: CommentedMap) -> None:
    from recap.daemon.config import parse_daemon_config_dict
    parse_daemon_config_dict(_to_plain_dict(doc))


def _to_plain_dict(obj: Any) -> Any:
    if isinstance(obj, (CommentedMap, dict)):
        return {k: _to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, (CommentedSeq, list)):
        return [_to_plain_dict(v) for v in obj]
    return obj
```

**Step 4: Add the PATCH handler in `server.py`**

```python
import json
import os
from recap.daemon.api_config import (
    apply_api_patch_to_yaml_doc, dump_yaml_doc, find_unknown_keys,
    load_yaml_doc, validate_yaml_doc,
)


async def _api_config_patch(request: web.Request) -> web.Response:
    daemon: Daemon = request.app["daemon"]
    if daemon.config_path is None:
        return web.json_response({"error": "config path not available"}, status=503)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "request body must be a JSON object"}, status=400)

    unknown = find_unknown_keys(body)
    if unknown:
        return web.json_response(
            {"error": f"unknown or read-only fields: {unknown}"}, status=400,
        )

    with daemon.config_lock:
        try:
            doc = load_yaml_doc(daemon.config_path)
            apply_api_patch_to_yaml_doc(doc, body)
            validate_yaml_doc(doc)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except OSError as e:
            return web.json_response({"error": str(e)}, status=500)

        tmp_path = daemon.config_path.with_suffix(
            daemon.config_path.suffix + ".tmp",
        )
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                dump_yaml_doc(doc, f)
            os.replace(tmp_path, daemon.config_path)
        except OSError as e:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return web.json_response({"error": str(e)}, status=500)

    daemon.emit_event(
        "info", "config_updated",
        f"Config updated (keys: {sorted(body.keys())})",
        payload={"changed_keys": sorted(body.keys())},
    )
    return web.json_response({"status": "ok", "restart_required": True})
```

Register: `app.router.add_patch("/api/config", _api_config_patch)`.

**Step 5: Run tests**

Run: `uv run pytest tests/test_api_config.py -v` → PASS.
Run: `uv run pytest -q` → full suite passes.

**Step 6: Commit**

```bash
git add recap/daemon/api_config.py recap/daemon/server.py tests/test_api_config.py
git commit -m "feat: /api/config PATCH with ruamel round-trip and strict validation"
```

---

## Task 10: Plugin `settings.ts` pt.1 — orgs section

**Context:** Extend the Obsidian settings tab. GETs `/api/config` on display; PATCHes on save. Single default-org semantics: toggling one org's default=true clears others.

**Files:**
- Modify: `obsidian-recap/src/settings.ts`
- Modify: `obsidian-recap/src/api.ts`

**Step 1: Add API types + methods to `api.ts`**

```typescript
export interface ApiOrg { name: string; subfolder: string; default: boolean; }
export interface ApiDetectionRule {
    enabled: boolean;
    behavior: "auto-record" | "prompt";
    default_org: string | null;
    default_backend: string | null;
}
export interface ApiCalendarProvider {
    enabled: boolean;
    calendar_id: string | null;
    org: string | null;
}
export interface ApiKnownContact {
    name: string;
    aliases: string[];
    email: string | null;
}
export interface ApiConfigDto {
    vault_path: string;
    recordings_path: string;
    user_name: string | null;
    plugin_port: number;
    orgs: ApiOrg[];
    default_org: string | null;
    detection: Record<string, ApiDetectionRule>;
    calendar: Record<string, ApiCalendarProvider>;
    known_contacts: ApiKnownContact[];
    recording_silence_timeout_minutes: number;
    recording_max_duration_hours: number;
    logging_retention_days: number;
}

// Inside DaemonClient:
async getConfig(): Promise<ApiConfigDto> {
    return this.get<ApiConfigDto>("/api/config");
}

async patchConfig(patch: Partial<ApiConfigDto>): Promise<{ status: string; restart_required: boolean }> {
    const resp = await fetch(`${this.baseUrl}/api/config`, {
        method: "PATCH",
        headers: {
            "Authorization": `Bearer ${this.token}`,
            "Content-Type": "application/json",
        },
        body: JSON.stringify(patch),
    });
    if (!resp.ok) throw new DaemonError(resp.status, await resp.text());
    return resp.json();
}
```

**Step 2: Extend `settings.ts`**

Read the existing `display()` method; make it `async` if needed. Inside, after the existing settings, add an orgs section. Fetch config via `this.plugin.client.getConfig()`. Render each org as a `new Setting(row)` with text inputs for name + subfolder, a toggle for default (cascade: setting one clears others), and a Remove button. Two bottom buttons: "Add org" and "Save orgs". Save calls `patchConfig({ orgs })` and renders `resp.restart_required` message.

Error paths (connection failure, GET failure, PATCH failure) use the `Notice + console.error` pattern.

**Step 3: Build**

Run: `cd obsidian-recap && npm run build` → zero errors.

**Step 4: Commit**

```bash
git add obsidian-recap/src/settings.ts obsidian-recap/src/api.ts
git commit -m "feat(plugin): settings orgs section with list/add/remove/default"
```

---

## Task 11: Plugin `settings.ts` pt.2 — detection + calendar + contacts + daemon

**Context:** Detection/calendar/contacts sections match the orgs pattern: read from `cfg`, collect edits in a local object, Save button calls `patchConfig`. Daemon lifecycle section shows state/uptime; Restart button surfaces a `Notice` telling the user to tray-quit + relaunch.

**Files:** Modify `obsidian-recap/src/settings.ts`.

**Step 1: Detection section**

For each `platform` in `cfg.detection`: enabled toggle, behavior dropdown (`auto-record`/`prompt`). Collect in `detectionEdits: Record<string, Partial<ApiDetectionRule>>`. Save button calls `patchConfig({ detection: detectionEdits })`.

**Step 2: Calendar section**

For each `provider` in `cfg.calendar`: enabled toggle, calendar_id text, org text. Save calls `patchConfig({ calendar: calendarEdits })`.

**Step 3: Contacts section**

List of contacts with name/aliases/email fields; Add Contact + Remove buttons. Save calls `patchConfig({ known_contacts: contacts })`.

**Step 4: Daemon lifecycle section**

Call `getStatus()` → display `"State: ${state}, uptime: ${Math.floor(uptime_seconds)}s"`. Restart button opens a `Notice` telling the user to use the tray.

**Step 5: Build**

Run: `cd obsidian-recap && npm run build` → zero errors.

**Step 6: Commit**

```bash
git add obsidian-recap/src/settings.ts
git commit -m "feat(plugin): settings detection/calendar/contacts/daemon sections"
```

---

## Task 12: Daemon `/api/recordings/<stem>/clip` endpoint

**Context:** Serves an MP3 clip of the first utterance by a given speaker. Stem validated regex. Resolves `audio_path = recordings_path / f"{stem}.flac"` and `transcript_file = artifacts.transcript_path(audio_path)`. Iterates `TranscriptResult.utterances` (NOT `segments`). Uses `subprocess.run` wrapped in `asyncio.to_thread` to invoke ffmpeg (safe: list args, no shell). Cache at `<recordings_path>/<stem>.clips/<label>_<duration>s.mp3`.

**Files:**
- Modify: `recap/daemon/server.py`
- Create: `tests/test_clip_endpoint.py`

**Step 1: Write failing tests**

Create `tests/test_clip_endpoint.py` with:

- `clip_fixture` — creates `<stem>.flac` (fake 1KB bytes) + `<stem>.transcript.json` containing `utterances` with two speakers (SPEAKER_00 start=1.5/end=3.2, SPEAKER_01 start=3.5/end=6.0).
- `TestClipValidation`:
  - `test_stem_with_traversal_rejected` — `..%2Fetc%2Fpasswd` → 400.
  - `test_missing_recording_returns_404`.
  - `test_missing_transcript_returns_404` — delete transcript → 404.
  - `test_speaker_not_in_transcript_returns_404` — SPEAKER_99 → 404.
  - `test_duration_out_of_range_returns_400` — duration=99 → 400.
  - `test_requires_bearer`.
- `TestClipCache`:
  - `test_cache_hit_serves_without_ffmpeg` — pre-create cache file, patch `asyncio.to_thread` to assert NOT called; 200 + `audio/mpeg`.
  - `test_cache_miss_invokes_ffmpeg` — patch `asyncio.to_thread` to simulate ffmpeg success (write fake bytes to cache path, return a stub result with `returncode=0`); 200 + `audio/mpeg`.
- `TestClipFfmpegFailure`:
  - `test_ffmpeg_nonzero_returns_500_and_journals` — patched ffmpeg returns `returncode=1`; 500; `clip_extraction_failed` event in journal.
- `TestClipIntegration` (decorated with `@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")`):
  - `test_real_ffmpeg_produces_mp3` — generates a real 10s silent FLAC via `subprocess.run(["ffmpeg", "-f", "lavfi", "-i", "anullsrc=...", ...])`, calls endpoint, verifies `audio/mpeg` + non-empty body.

**Step 2: Run to verify failure** — route doesn't exist.

**Step 3: Implement the handler in `server.py`**

Use `subprocess.run` + `asyncio.to_thread` (avoids the shell; list-args is safe):

```python
import asyncio
import json
import re
import subprocess
from recap.artifacts import transcript_path as artifact_transcript_path


_STEM_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_MIN_DURATION = 1
_MAX_DURATION = 30
_DEFAULT_DURATION = 5


def _run_ffmpeg_clip(cmd: list[str]) -> tuple[int, bytes]:
    """Run ffmpeg with list args (no shell). Returns (returncode, stderr)."""
    result = subprocess.run(cmd, capture_output=True, check=False)
    return result.returncode, result.stderr


async def _api_recording_clip(request: web.Request) -> web.Response:
    daemon: Daemon = request.app["daemon"]
    stem = request.match_info["stem"]
    if not _STEM_RE.fullmatch(stem):
        return web.json_response({"error": "invalid stem"}, status=400)

    speaker = request.query.get("speaker")
    if not speaker:
        return web.json_response({"error": "speaker required"}, status=400)

    duration_str = request.query.get("duration", str(_DEFAULT_DURATION))
    try:
        duration = int(duration_str)
    except ValueError:
        return web.json_response({"error": "duration must be an integer"}, status=400)
    if duration < _MIN_DURATION or duration > _MAX_DURATION:
        return web.json_response(
            {"error": f"duration must be in [{_MIN_DURATION}, {_MAX_DURATION}]"},
            status=400,
        )

    audio_path = daemon.config.recordings_path / f"{stem}.flac"
    if not audio_path.exists():
        return web.json_response({"error": "recording not found"}, status=404)

    transcript_file = artifact_transcript_path(audio_path)
    if not transcript_file.exists():
        return web.json_response({"error": "transcript not found"}, status=404)

    try:
        transcript_data = json.loads(transcript_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return web.json_response({"error": f"transcript read: {e}"}, status=500)

    utterances = transcript_data.get("utterances") or []
    match = next((u for u in utterances if u.get("speaker") == speaker), None)
    if match is None:
        return web.json_response({"error": "speaker not found in transcript"}, status=404)

    start = float(match["start"])
    end = float(match["end"])
    clip_duration = min(float(duration), max(0.5, end - start))

    cache_dir = daemon.config.recordings_path / f"{stem}.clips"
    cache_file = cache_dir / f"{speaker}_{duration}s.mp3"
    if cache_file.exists():
        return web.FileResponse(cache_file, headers={"Content-Type": "audio/mpeg"})

    cache_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-t", f"{clip_duration:.3f}",
        "-i", str(audio_path),
        "-acodec", "libmp3lame",
        "-b:a", "96k",
        "-ar", "22050",
        str(cache_file),
    ]
    returncode, stderr = await asyncio.to_thread(_run_ffmpeg_clip, cmd)
    if returncode != 0:
        daemon.emit_event(
            "error", "clip_extraction_failed",
            f"ffmpeg exit {returncode}",
            payload={
                "stem": stem, "speaker": speaker, "returncode": returncode,
                "stderr": stderr.decode("utf-8", errors="replace")[:500],
            },
        )
        if cache_file.exists():
            try: cache_file.unlink()
            except OSError: pass
        return web.json_response({"error": "clip extraction failed"}, status=500)

    return web.FileResponse(cache_file, headers={"Content-Type": "audio/mpeg"})
```

Register: `app.router.add_get("/api/recordings/{stem}/clip", _api_recording_clip)`.

The unit tests mock `asyncio.to_thread` to simulate success/failure; the integration test uses real ffmpeg under the skipif guard.

**Step 4: Run tests**

Run: `uv run pytest tests/test_clip_endpoint.py -v` → PASS (integration test skips if ffmpeg unavailable).
Run: `uv run pytest -q` → full suite passes.

**Step 5: Commit**

```bash
git add recap/daemon/server.py tests/test_clip_endpoint.py
git commit -m "feat: /api/recordings/<stem>/clip endpoint with cache + journaling"
```

---

## Task 13: Plugin `SpeakerCorrectionModal.ts` — audio preview + contacts

**Context:** Add `<audio controls>` per speaker; source is a blob from the clip endpoint. Contacts datalist sourced from `/api/config.known_contacts`.

**Files:**
- Modify: `obsidian-recap/src/views/SpeakerCorrectionModal.ts`
- Modify: `obsidian-recap/src/api.ts`

**Step 1: Add `fetchSpeakerClip` to `api.ts`**

```typescript
getSpeakerClipUrl(stem: string, speaker: string, duration = 5): string {
    return `${this.baseUrl}/api/recordings/${encodeURIComponent(stem)}/clip`
        + `?speaker=${encodeURIComponent(speaker)}&duration=${duration}`;
}

async fetchSpeakerClip(stem: string, speaker: string, duration = 5): Promise<Blob> {
    const resp = await fetch(this.getSpeakerClipUrl(stem, speaker, duration), {
        headers: { "Authorization": `Bearer ${this.token}` },
    });
    if (!resp.ok) throw new DaemonError(resp.status, await resp.text());
    return resp.blob();
}
```

**Step 2: Update the modal**

Derive `stem` from `recordingPath` (strip `.flac`, basename). For each speaker row, create an `<audio controls>` element. Fetch the clip via `fetchSpeakerClip(stem, label, 5)`, on success `audioEl.src = URL.createObjectURL(blob)`. On error: replace with a warning span `"(clip unavailable: <msg>)"` and `console.error`.

Populate a `<datalist id="recap-known-contacts">` with names from `this.client.getConfig().known_contacts`. Set `list="recap-known-contacts"` on each speaker name input. If `getConfig()` fails, fall back to the `knownContacts` prop + `console.error` (non-fatal).

**Step 3: Build** → `cd obsidian-recap && npm run build` → zero errors.

**Step 4: Commit**

```bash
git add obsidian-recap/src/views/SpeakerCorrectionModal.ts obsidian-recap/src/api.ts
git commit -m "feat(plugin): speaker correction modal plays daemon audio clips + contacts datalist"
```

---

## Task 14: Plugin `MeetingListView.ts` — narrow scan to configured org subfolders

**Context:** Before loading, fetch `/api/config`. Use `cfg.orgs[].subfolder` to filter `this.app.vault.getMarkdownFiles()`. Fallback: whole-vault scan on API failure, with `Notice`.

**Files:** Modify `obsidian-recap/src/views/MeetingListView.ts`.

**Step 1: Read the current `loadMeetings`** (or equivalent) to understand the existing iteration.

**Step 2: Refactor**

At the top of the method:

```typescript
let subfolders: string[] = [];
if (this.plugin.client) {
    try {
        const cfg = await this.plugin.client.getConfig();
        subfolders = cfg.orgs
            .map((o) => o.subfolder)
            .filter((s): s is string => !!s && s.length > 0);
    } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        new Notice(`Recap: could not load org config — scanning whole vault. ${msg}`);
        console.error("Recap:", e);
    }
}

const allFiles = this.app.vault.getMarkdownFiles();
const files = subfolders.length === 0
    ? allFiles
    : allFiles.filter((f) =>
        subfolders.some((sub) => f.path.startsWith(sub + "/") || f.path === sub)
    );
```

Replace subsequent references to `allFiles` with `files`.

**Step 3: Build** → zero errors.

**Step 4: Commit**

```bash
git add obsidian-recap/src/views/MeetingListView.ts
git commit -m "feat(plugin): MeetingListView scans only configured org subfolders"
```

---

## Task 15: Plugin `api.ts` DaemonStatus alignment — final check

**Context:** Task 2 already added the extended type. This task grep-verifies no consumer still uses the legacy shape in a way that would drop information.

**Files:** Verify `obsidian-recap/src/api.ts`, `obsidian-recap/src/main.ts`, and any other file consuming `DaemonStatus`.

**Step 1:**

```bash
cd obsidian-recap/src
grep -rn "\.daemon_uptime\|\.errors\|\.recent_errors\|\.uptime_seconds\|\.last_calendar_sync" . --include="*.ts"
```

For each hit: verify it uses the correct field.
- Uptime display in new UI → `status.uptime_seconds`.
- Error rendering → `status.recent_errors ?? []` (array of `DaemonEvent`); iterate and render `ev.message` (or `ev.event`).
- `last_calendar_sync` untouched.
- Legacy `daemon_uptime`/`errors` may remain as read-only fallbacks; no action unless they're used where new fields would be better.

**Step 2: Build** → zero errors.

**Step 3: Commit**

```bash
git add obsidian-recap/src/
git commit -m "chore(plugin): align status field usage to uptime_seconds/recent_errors"
```

If no actual changes were needed, skip the commit or use `--allow-empty` with a no-op note.

---

## Task 16: `tests/test_phase4_integration.py` — contract integration

**Context:** Python-only end-to-end: pairing → Bearer → journal → `/api/events` backfill → WS live → `/api/config` round-trip. No plugin JS test runner (manual acceptance at Task 17).

**Files:** Create `tests/test_phase4_integration.py`.

**Step 1: Write the test**

The test function is async (`@pytest.mark.asyncio`) and follows this outline:

1. **Setup:** `make_daemon_config(tmp_path)`; write a minimal config.yaml with a top-of-file marker comment; construct `Daemon(cfg, config_path=config_path)`; `await daemon.start(args=..., callbacks=...)` using `minimal_daemon_args()` and `build_daemon_callbacks(daemon)`.

2. **Use `aiohttp.ClientSession` against `http://127.0.0.1:{daemon.port}`:**
   - **Pairing:** `daemon.pairing.open()` → `GET /bootstrap/token` → 200 + `token == cfg.auth_token`. Second call → 404.
   - **Bearer:** `POST /api/meeting-detected` with Bearer → 200. Without → 401.
   - **Journal tail:** `daemon.event_journal.tail(limit=100)` contains `pairing_opened`, `pairing_token_issued`, `daemon_started`.
   - **`/api/events` backfill:** `GET /api/events?limit=100` → returns entries including `pairing_opened`. Capture `middle_ts` = last entry's ts; `daemon.emit_event("info", "post_test_marker", "after")`; `GET /api/events?since={middle_ts}` → contains `post_test_marker`, not `pairing_opened`.
   - **WebSocket live:** `session.ws_connect(f"ws://127.0.0.1:{daemon.port}/api/ws?token={token}")`; after small sleep, `daemon.emit_event("info", "ws_live_test", "streamed")`; receive frames via `ws.receive()` with timeout; assert one has `event == "journal_entry"` and `entry.event == "ws_live_test"`.
   - **`/api/config` GET:** 200, body contains `vault_path`, does NOT contain `auth_token`, has `default_org == "alpha"`.
   - **`/api/config` PATCH:** `{"user_name": "IntegrationTest"}` → 200 + `restart_required: true`. Read `config_path.read_text()`; assert both `IntegrationTest` and the marker comment present.
   - **`config_updated` in journal** after PATCH.

3. **Teardown:** `await daemon.stop()` in `finally`.

**Step 2: Run**

Run: `uv run pytest tests/test_phase4_integration.py -v` → PASS.
Run: `uv run pytest -q` → full suite passes.

**Step 3: Commit**

```bash
git add tests/test_phase4_integration.py
git commit -m "test: Phase 4 contract integration (pairing, Bearer, events, config, WS)"
```

---

## Task 17: MANIFEST + manual acceptance checklist

**Files:**
- Create: `docs/handoffs/2026-04-14-phase4-plugin-manual-acceptance.md`
- Modify: `MANIFEST.md`

**Step 1: Manual acceptance checklist**

Create `docs/handoffs/2026-04-14-phase4-plugin-manual-acceptance.md` with sections:

- **Extension**: load in Chrome; open options; loopback validation; pair-without-tray 404 message; tray → Connect → status; trigger meeting → 200 POST; Disconnect; baseUrl change → token cleared.
- **Plugin — notification history**: connect; open modal → backfill loads; live entries appear; reconnect → works.
- **Plugin — settings UI**: orgs add/edit/remove/default → config.yaml round-trips with comments preserved; detection toggle save; calendar save; contacts save; daemon restart shows tray Notice.
- **Plugin — speaker correction audio preview**: each SPEAKER_XX has working `<audio controls>`; contacts datalist populated.
- **Plugin — MeetingListView narrowing**: 10k-note vault loads <100ms; only notes under org subfolders visible.
- **Plugin — silent-catch sanity**: force-disconnect daemon → Notice shown; grep `catch {}` → 0.
- **Extension ↔ daemon**: delete auth-token → next POST 401 → badge AUTH → re-pair; change plugin_port → baseUrl update → re-pair.
- **Regression checks**: `uv run pytest -q` all pass; `npm run build` zero errors; grep verifications.

**Step 2: Update MANIFEST**

- Add to Structure: `recap/daemon/api_config.py`, `tests/test_api_events.py`, `tests/test_api_config.py`, `tests/test_clip_endpoint.py`, `tests/test_phase4_integration.py`, `docs/handoffs/2026-04-14-phase4-plugin-manual-acceptance.md`.
- Update annotations: `server.py` (new endpoints), `service.py` (config_path + lock), `events.py` (microsecond ts), `extension/*`, plugin files.
- Update Key Relationships:
  - Add: "Extension pairs via tray → `/bootstrap/token`; stores {token, baseUrl, pairedAt}; reactive 401-based invalidation."
  - Add: "Plugin notification history is a thin renderer over daemon journal; backfill via `/api/events`, live via WS `journal_entry`."
  - Add: "Plugin settings UI round-trips daemon config via `/api/config`; ruamel preserves comments; restart required to apply."
  - Remove: any transitional-route mention.
- Keep 50-80 lines.

**Step 3: Final pytest**

Run: `uv run pytest -q` → all pass.

**Step 4: Commit**

```bash
git add MANIFEST.md docs/handoffs/2026-04-14-phase4-plugin-manual-acceptance.md
git commit -m "docs: Phase 4 MANIFEST + manual acceptance checklist"
```

---

## Post-Phase Verification

| Command | Expected |
|---|---|
| `uv run pytest -q` | all pass (~520) |
| `grep -rn "catch *{}\|catch *(e) *{}" obsidian-recap/src/` | 0 hits |
| `grep -n "'/meeting-detected'\|'/meeting-ended'" recap/daemon/server.py` | only `/api/meeting-*` variants |
| `grep -n "class ApiConfig" recap/daemon/api_config.py` | 1 hit |
| `grep -n "ruamel.yaml" pyproject.toml` | 1 hit |
| `cd obsidian-recap && npm run build` | zero tsc errors |
| Manual acceptance checklist | all items ✓ |

**Acceptance criteria** (from design §Acceptance Criteria):

- [ ] Extension pairs from tray → options → Connect; 401 clears token.
- [ ] All `/api/meeting-*` traffic Bearer-authenticated. Legacy routes deleted.
- [ ] Plugin notification history shows backfill + live.
- [ ] Settings UI round-trips orgs/detection/calendar/known_contacts; YAML comments preserved.
- [ ] Speaker correction modal plays MP3 clips; contacts datalist populated.
- [ ] MeetingListView scans configured subfolders; sub-100ms on 10k notes.
- [ ] No silent catches in plugin.
- [ ] `test_phase4_integration.py` passes.
- [ ] Manual acceptance verified.

---

## Handoff to Phase 5

Phase 5 (Honesty Pass) picks up:
- Remaining `except Exception:` swallow patterns missed in Phase 4.
- Deprecated scaffolding identified during Phase 4 review.
- Type-safety tightening across Phases 1-4.
- Optional: JS test runner for plugin if manual acceptance proves inadequate.
- Optional: `/api/events` backwards pagination for deeper scrollback.
- Optional: `/api/restart` endpoint if plugin-initiated restart becomes worth building.

Phase 4 does NOT touch Phase 2 frozen code (`EventIndex`, `OrgConfig.resolve_subfolder`, `resolve_note_path`, `to_vault_relative`). Phase 3 transitional shapes to review: `callbacks` dict in `Daemon.start`; legacy `daemon_uptime`/`errors` mirror fields in `/api/status` (drop when plugin fully migrates). Phase 5 decides closure.
