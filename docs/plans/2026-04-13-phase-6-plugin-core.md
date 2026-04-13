# Phase 6: Obsidian Plugin (Core)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Scaffold the Obsidian plugin with meeting list view, status bar, recording controls, daemon API client, and settings tab.

**Architecture:** Standard Obsidian plugin with ItemViews for custom panes, PluginSettingTab for configuration, and status bar items for recording state. Communicates with daemon via HTTP REST + WebSocket. Uses Dataview API for querying meeting notes.

**Tech Stack:** TypeScript, Obsidian API, esbuild

---

### Task 1: Scaffold plugin

**Files:**
- Create: `obsidian-recap/manifest.json`
- Create: `obsidian-recap/package.json`
- Create: `obsidian-recap/tsconfig.json`
- Create: `obsidian-recap/esbuild.config.mjs`
- Create: `obsidian-recap/src/main.ts`
- Create: `obsidian-recap/styles.css`

**Step 1: Create plugin directory and manifest**

`manifest.json`:
```json
{
    "id": "recap",
    "name": "Recap",
    "version": "0.1.0",
    "minAppVersion": "1.5.0",
    "description": "Meeting recording dashboard — browse, review, and manage meeting notes from the Recap daemon.",
    "author": "Tim Simpson",
    "isDesktopOnly": true
}
```

**Step 2: Create package.json**

```json
{
    "name": "obsidian-recap",
    "version": "0.1.0",
    "description": "Obsidian plugin for Recap meeting recording system",
    "main": "main.js",
    "scripts": {
        "dev": "node esbuild.config.mjs",
        "build": "tsc -noEmit -skipLibCheck && node esbuild.config.mjs production"
    },
    "devDependencies": {
        "@types/node": "^20.0.0",
        "esbuild": "^0.20.0",
        "obsidian": "latest",
        "typescript": "~5.6.0"
    }
}
```

**Step 3: Create tsconfig.json**

Standard Obsidian plugin tsconfig with strict mode, ES2022 target, module bundler resolution.

**Step 4: Create esbuild config**

Standard Obsidian plugin esbuild config: bundle `src/main.ts` → `main.js`, external `obsidian`, watch mode for dev.

**Step 5: Create minimal main.ts**

```typescript
import { Plugin } from "obsidian";

export default class RecapPlugin extends Plugin {
    async onload() {
        console.log("Recap plugin loaded");
    }

    onunload() {
        console.log("Recap plugin unloaded");
    }
}
```

**Step 6: Install, build, verify**

```bash
cd obsidian-recap
npm install
npm run build
```

Verify `main.js` is generated. Copy to Obsidian vault's `.obsidian/plugins/recap/` and enable in Obsidian to verify it loads.

**Step 7: Commit**

```bash
git add obsidian-recap/
git commit -m "feat: scaffold Obsidian plugin with manifest and build config"
```

---

### Task 2: Daemon API client

**Files:**
- Create: `obsidian-recap/src/api.ts`

**Step 1: Implement HTTP + WebSocket client**

```typescript
export class DaemonClient {
    private baseUrl: string;
    private token: string;
    private ws: WebSocket | null = null;
    private wsReconnectTimer: number | null = null;

    constructor(baseUrl: string, token: string) {
        this.baseUrl = baseUrl;
        this.token = token;
    }

    // HTTP methods
    async get<T>(path: string): Promise<T> {
        const resp = await fetch(`${this.baseUrl}${path}`, {
            headers: { "Authorization": `Bearer ${this.token}` },
        });
        if (!resp.ok) throw new DaemonError(resp.status, await resp.text());
        return resp.json();
    }

    async post<T>(path: string, body?: unknown): Promise<T> {
        const resp = await fetch(`${this.baseUrl}${path}`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${this.token}`,
                "Content-Type": "application/json",
            },
            body: body ? JSON.stringify(body) : undefined,
        });
        if (!resp.ok) throw new DaemonError(resp.status, await resp.text());
        return resp.json();
    }

    // WebSocket
    connectWebSocket(onMessage: (event: DaemonEvent) => void, onDisconnect: () => void): void {
        // Connect to ws://localhost:9847/api/ws
        // Auto-reconnect every 10 seconds on disconnect
        // Parse incoming JSON messages as DaemonEvent
    }

    disconnectWebSocket(): void {
        // Clean up WebSocket and reconnect timer
    }

    // Convenience methods
    async getStatus(): Promise<DaemonStatus> { return this.get("/api/status"); }
    async startRecording(org: string): Promise<void> { await this.post("/api/record/start", { org }); }
    async stopRecording(): Promise<void> { await this.post("/api/record/stop"); }
    async reprocess(recordingPath: string, fromStage?: string): Promise<void> { ... }
    async submitSpeakerCorrections(recordingPath: string, mapping: Record<string, string>): Promise<void> { ... }
}

export class DaemonError extends Error {
    constructor(public status: number, message: string) { super(message); }
}

export interface DaemonStatus {
    state: "idle" | "armed" | "recording" | "processing";
    recording: { path: string; org: string; duration: number } | null;
    daemon_uptime: number;
    last_calendar_sync: string | null;
    errors: string[];
}

export interface DaemonEvent {
    event: string;
    [key: string]: unknown;
}
```

**Step 2: Commit**

```bash
git add obsidian-recap/src/api.ts
git commit -m "feat: add daemon HTTP/WebSocket client for plugin"
```

---

### Task 3: Status bar item

**Files:**
- Create: `obsidian-recap/src/components/StatusBarItem.ts`
- Modify: `obsidian-recap/src/main.ts`

**Step 1: Implement status bar**

The status bar shows:
- Daemon connection state: "Daemon offline" (red) / connected (no text, just functional)
- Recording state: "⏺ Recording (Disbursecloud)" / "⚙ Processing..." / nothing when idle

```typescript
export class RecapStatusBar {
    private el: HTMLElement;
    private client: DaemonClient;

    constructor(statusBarEl: HTMLElement, client: DaemonClient) {
        this.el = statusBarEl;
        this.client = client;
    }

    updateState(state: DaemonStatus["state"], org?: string): void {
        switch (state) {
            case "recording":
                this.el.setText(`⏺ Recording (${org})`);
                this.el.addClass("recap-recording");
                break;
            case "processing":
                this.el.setText("⚙ Processing...");
                break;
            default:
                this.el.setText("");
                this.el.removeClass("recap-recording");
        }
    }

    setOffline(): void {
        this.el.setText("⚠ Daemon offline");
        this.el.addClass("recap-offline");
    }

    setConnected(): void {
        this.el.setText("");
        this.el.removeClass("recap-offline");
    }
}
```

**Step 2: Wire to plugin**

In `main.ts`:
- Create status bar item via `this.addStatusBarItem()`
- Create `DaemonClient` with URL + token from settings
- Connect WebSocket, update status bar on state change events
- On WebSocket disconnect: show "Daemon offline"

**Step 3: Build and test in Obsidian**

```bash
npm run build
```

Copy to vault, enable plugin, verify status bar shows connection state.

**Step 4: Commit**

```bash
git add obsidian-recap/src/
git commit -m "feat: add status bar with daemon connection and recording state"
```

---

### Task 4: Recording controls (commands)

**Files:**
- Modify: `obsidian-recap/src/main.ts`

**Step 1: Add commands**

```typescript
this.addCommand({
    id: "start-recording",
    name: "Start recording",
    callback: async () => {
        // Show org picker modal, then call client.startRecording(org)
    },
});

this.addCommand({
    id: "stop-recording",
    name: "Stop recording",
    callback: async () => {
        await this.client.stopRecording();
    },
});
```

The start recording command should show a quick picker (Obsidian's SuggestModal) listing the configured orgs.

**Step 2: Create org picker modal**

```typescript
export class OrgPickerModal extends SuggestModal<string> {
    orgs: string[];
    onSelect: (org: string) => void;
    // ... standard SuggestModal implementation
}
```

**Step 3: Build and test**

Verify: Ctrl+P → "Recap: Start recording" → org picker → recording starts. Ctrl+P → "Recap: Stop recording" → recording stops.

**Step 4: Commit**

```bash
git add obsidian-recap/src/
git commit -m "feat: add start/stop recording commands with org picker"
```

---

### Task 5: Meeting list view

**Files:**
- Create: `obsidian-recap/src/views/MeetingListView.ts`
- Create: `obsidian-recap/src/components/MeetingRow.ts`
- Create: `obsidian-recap/src/components/FilterBar.ts`
- Create: `obsidian-recap/src/components/PipelineStatus.ts`
- Modify: `obsidian-recap/src/main.ts`

**Step 1: Register the view**

```typescript
export const VIEW_MEETING_LIST = "recap-meeting-list";

// In main.ts onload():
this.registerView(VIEW_MEETING_LIST, (leaf) => new MeetingListView(leaf, this));
this.addRibbonIcon("mic", "Recap", () => this.activateView(VIEW_MEETING_LIST));
this.addCommand({
    id: "open-dashboard",
    name: "Open meeting dashboard",
    callback: () => this.activateView(VIEW_MEETING_LIST),
});
```

**Step 2: Implement MeetingListView**

`MeetingListView extends ItemView`:
- `getViewType()` → `VIEW_MEETING_LIST`
- `getDisplayText()` → "Recap Meetings"
- `onOpen()`:
  1. Query meeting notes via Dataview API: `app.plugins.plugins.dataview.api.pages('"_Recap"').where(p => p.tags?.includes("meeting"))`
  2. Or fallback: scan `_Recap/*/Meetings/` folders, parse frontmatter from each `.md` file
  3. Render filter bar (org, date range, meeting type, pipeline status)
  4. Render meeting rows sorted by date (newest first)
- Each `MeetingRow` shows: date, title, org badge, duration, pipeline status indicator, participant count
- Clicking a row opens the meeting note via `this.app.workspace.openLinkText()`

**Step 3: Implement FilterBar**

Dropdown filters for:
- Org (all / disbursecloud / personal / activism)
- Pipeline status (all / complete / processing / failed)
- Date range (quick picks: today, this week, this month, all)
- Search text (filters title and participants)

**Step 4: Implement PipelineStatus**

Reads `pipeline-status` from frontmatter, renders a colored dot:
- Green: complete
- Yellow: processing/transcribing/diarizing/analyzing/exporting
- Red: failed:*
- Gray: pending (calendar note, not yet recorded)

**Step 5: Build and test**

Create some sample meeting notes in `_Recap/Disbursecloud/Meetings/` with proper frontmatter. Open plugin, verify meeting list renders with filters.

**Step 6: Commit**

```bash
git add obsidian-recap/src/
git commit -m "feat: add meeting list view with Dataview queries and filters"
```

---

### Task 6: Settings tab

**Files:**
- Create: `obsidian-recap/src/settings.ts`
- Modify: `obsidian-recap/src/main.ts`

**Step 1: Implement PluginSettingTab**

```typescript
export class RecapSettingTab extends PluginSettingTab {
    plugin: RecapPlugin;

    display(): void {
        const { containerEl } = this;
        containerEl.empty();

        // Connection
        new Setting(containerEl).setName("Daemon URL").setDesc("...").addText(...);
        new Setting(containerEl).setName("Auth token path").setDesc("...").addText(...);

        // Daemon status (read from HTTP)
        // Show connected/disconnected, uptime, last sync

        // OAuth providers
        // Zoho: connected/disconnected + connect/disconnect buttons
        // Google: connected/disconnected + connect/disconnect buttons

        // Org configuration (read/write via daemon HTTP)

        // Known contacts list (read/write via daemon HTTP)

        // Detection settings (read/write via daemon HTTP)

        // Recording settings (read/write via daemon HTTP)
    }
}
```

**Step 2: Wire to plugin**

```typescript
this.addSettingTab(new RecapSettingTab(this.app, this));
```

**Step 3: First-run experience**

If the plugin has no saved settings (first launch):
- Show a notice: "Recap plugin needs to connect to the daemon. Open Settings → Recap to configure."
- Settings tab shows setup instructions and daemon URL field

**Step 4: Build and test**

Verify settings tab appears in Obsidian settings, daemon connection indicator works, OAuth buttons trigger flows.

**Step 5: Commit**

```bash
git add obsidian-recap/src/settings.ts obsidian-recap/src/main.ts
git commit -m "feat: add settings tab with daemon config and OAuth management"
```

---

### Task 7: Styles

**Files:**
- Modify: `obsidian-recap/styles.css`

**Step 1: Add plugin styles**

Minimal CSS that inherits from Obsidian's theme (dark mode comes free):
- `.recap-recording` — red text for recording indicator
- `.recap-offline` — yellow/orange for daemon offline
- `.recap-meeting-row` — hover state, padding for list items
- `.recap-pipeline-dot` — colored dots for pipeline status
- `.recap-filter-bar` — layout for filter controls
- `.recap-org-badge` — small colored badge for org names

Keep it minimal. Obsidian's theme handles most of the look.

**Step 2: Commit**

```bash
git add obsidian-recap/styles.css
git commit -m "feat: add plugin styles for meeting list and status indicators"
```

---

### Task 8: Push and verify

**Step 1: Build plugin**

```bash
cd obsidian-recap && npm run build
```

**Step 2: Install in Obsidian**

Copy `main.js`, `manifest.json`, `styles.css` to `.obsidian/plugins/recap/`. Enable plugin.

**Step 3: Verify**

- Ribbon icon opens meeting list
- Status bar shows daemon connection state
- Settings tab is accessible
- Meeting list shows notes from `_Recap/*/Meetings/`
- Filters work
- Ctrl+P commands appear

**Step 4: Push**

```bash
git push
```
