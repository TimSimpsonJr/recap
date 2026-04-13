# Phase 7: Obsidian Plugin (Advanced)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add speaker correction modal, live transcript view stub (WebSocket wiring, actual streaming content comes in Phase 8), file rename processing, and notification history.

**Architecture:** These features layer on top of the Phase 6 plugin core. The speaker correction modal is an Obsidian Modal. The live transcript view is an ItemView fed by WebSocket. File rename processing watches `.recap/rename-queue.json`.

**Tech Stack:** TypeScript, Obsidian API

---

### Task 1: Speaker correction modal

**Files:**
- Create: `obsidian-recap/src/views/SpeakerCorrectionModal.ts`
- Modify: `obsidian-recap/src/main.ts`

**Step 1: Implement the modal**

```typescript
export class SpeakerCorrectionModal extends Modal {
    speakers: SpeakerInfo[];    // {label: "SPEAKER_00", sampleClipPath: string}
    peopleNotes: string[];      // names from People/ folders for autocomplete
    knownContacts: string[];    // from daemon config
    onSubmit: (mapping: Record<string, string>) => void;

    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h2", { text: "Identify Speakers" });
        contentEl.createEl("p", { text: "The pipeline couldn't match speakers to names. Listen to a sample and assign names:" });

        for (const speaker of this.speakers) {
            const row = contentEl.createDiv({ cls: "recap-speaker-row" });

            // Speaker label
            row.createSpan({ text: speaker.label, cls: "recap-speaker-label" });

            // Play button for sample clip
            const playBtn = row.createEl("button", { text: "▶" });
            playBtn.addEventListener("click", () => {
                // Play speaker.sampleClipPath via HTML5 Audio
            });

            // Name input with autocomplete from People notes + known contacts
            const input = row.createEl("input", {
                type: "text",
                placeholder: "Enter name...",
                cls: "recap-speaker-input",
            });
            // Add autocomplete dropdown from this.peopleNotes + this.knownContacts
        }

        // Buttons
        const btnRow = contentEl.createDiv({ cls: "recap-modal-buttons" });
        btnRow.createEl("button", { text: "Cancel" }).addEventListener("click", () => this.close());
        btnRow.createEl("button", { text: "Apply & Redo", cls: "mod-cta" }).addEventListener("click", () => {
            const mapping = this.collectMapping();
            this.onSubmit(mapping);
            this.close();
        });
    }
}
```

**Step 2: Add banner to meeting notes with unidentified speakers**

When opening a meeting note, check if frontmatter contains `pipeline-status: complete` and the content has `SPEAKER_` labels. If so, show a notice or add a banner view at the top.

Register a `file-open` event in `main.ts`:

```typescript
this.registerEvent(
    this.app.workspace.on("file-open", (file) => {
        if (file && this.hasSpeakerLabels(file)) {
            new Notice("This meeting has unidentified speakers. Click to fix.", 10000);
            // Or show banner in reading view
        }
    })
);
```

**Step 3: Wire modal to daemon**

When "Apply & Redo" is clicked:
1. POST speaker mapping to daemon: `/api/meetings/speakers` with `{recording_path, mapping}`
2. Daemon re-runs export stage with corrected names
3. Meeting note gets rewritten with real names

**Step 4: Get people names for autocomplete**

```typescript
private getPeopleNames(): string[] {
    // Scan _Recap/*/People/ folders for .md files
    // Return file names (without .md extension)
    const files = this.app.vault.getFiles().filter(f =>
        f.path.includes("/People/") && f.path.startsWith("_Recap/")
    );
    return files.map(f => f.basename);
}
```

**Step 5: Build, test, commit**

```bash
cd obsidian-recap && npm run build
git add obsidian-recap/src/
git commit -m "feat: add speaker correction modal with audio playback and autocomplete"
```

---

### Task 2: Live transcript view (stub)

**Files:**
- Create: `obsidian-recap/src/views/LiveTranscriptView.ts`
- Modify: `obsidian-recap/src/main.ts`

**Step 1: Implement view**

This is the shell that will receive streaming transcript data in Phase 8. For now, it shows the recording state and a placeholder.

```typescript
export const VIEW_LIVE_TRANSCRIPT = "recap-live-transcript";

export class LiveTranscriptView extends ItemView {
    private transcriptEl: HTMLElement;
    private statusEl: HTMLElement;

    getViewType(): string { return VIEW_LIVE_TRANSCRIPT; }
    getDisplayText(): string { return "Live Transcript"; }

    async onOpen(): Promise<void> {
        const container = this.containerEl.children[1];
        container.empty();

        this.statusEl = container.createDiv({ cls: "recap-live-status" });
        this.transcriptEl = container.createDiv({ cls: "recap-live-transcript" });

        this.updateStatus("idle");
    }

    updateStatus(state: string): void {
        switch (state) {
            case "recording":
                this.statusEl.setText("⏺ Recording — live transcript will appear here");
                break;
            case "idle":
                this.statusEl.setText("Not recording. Start a recording to see live transcript.");
                break;
        }
    }

    appendUtterance(speaker: string, text: string): void {
        const line = this.transcriptEl.createDiv({ cls: "recap-utterance" });
        line.createSpan({ text: `${speaker}: `, cls: "recap-speaker" });
        line.createSpan({ text });
        this.transcriptEl.scrollTop = this.transcriptEl.scrollHeight;
    }

    clear(): void {
        this.transcriptEl.empty();
    }
}
```

**Step 2: Register view and command**

```typescript
this.registerView(VIEW_LIVE_TRANSCRIPT, (leaf) => new LiveTranscriptView(leaf));
this.addCommand({
    id: "open-live-transcript",
    name: "Open live transcript",
    callback: () => this.activateView(VIEW_LIVE_TRANSCRIPT),
});
```

**Step 3: Wire WebSocket events**

When WebSocket receives `state_change` → `recording`: update live transcript view status.
When WebSocket receives transcript data (Phase 8): call `appendUtterance()`.

**Step 4: Build, test, commit**

```bash
cd obsidian-recap && npm run build
git add obsidian-recap/src/
git commit -m "feat: add live transcript view stub (streaming content in Phase 8)"
```

---

### Task 3: File rename processing

**Files:**
- Create: `obsidian-recap/src/renameProcessor.ts`
- Modify: `obsidian-recap/src/main.ts`

**Step 1: Implement rename processor**

```typescript
export class RenameProcessor {
    private app: App;
    private queuePath: string;  // _Recap/.recap/rename-queue.json

    constructor(app: App, queuePath: string) {
        this.app = app;
        this.queuePath = queuePath;
    }

    async processQueue(): Promise<void> {
        // Read rename-queue.json
        // For each entry: {oldPath: "...", newPath: "..."}
        //   - Use this.app.vault.rename(file, newPath)
        //   - Obsidian automatically updates all wikilinks
        //   - Remove entry from queue
        // Write updated queue back (or delete if empty)
    }
}
```

**Step 2: Wire to plugin**

On plugin load and on WebSocket reconnect, process the rename queue:

```typescript
// In onload():
this.renameProcessor = new RenameProcessor(this.app, "_Recap/.recap/rename-queue.json");
await this.renameProcessor.processQueue();

// On WebSocket connect:
this.client.connectWebSocket((event) => {
    if (event.event === "rename_queued") {
        this.renameProcessor.processQueue();
    }
    // ... other event handling
}, () => { /* disconnect handler */ });
```

**Step 3: Build, test, commit**

Create a test `rename-queue.json` with a rename entry. Start plugin, verify file is renamed and wikilinks update.

```bash
cd obsidian-recap && npm run build
git add obsidian-recap/src/
git commit -m "feat: add file rename processor for calendar date changes"
```

---

### Task 4: Notification history

**Files:**
- Create: `obsidian-recap/src/notificationHistory.ts`
- Modify: `obsidian-recap/src/main.ts`

**Step 1: Implement notification store**

```typescript
export interface RecapNotification {
    timestamp: string;
    type: "info" | "warning" | "error";
    title: string;
    message: string;
}

export class NotificationHistory {
    private notifications: RecapNotification[] = [];
    private maxSize = 100;

    add(notification: RecapNotification): void {
        this.notifications.unshift(notification);
        if (this.notifications.length > this.maxSize) {
            this.notifications.pop();
        }
    }

    getAll(): RecapNotification[] {
        return [...this.notifications];
    }

    clear(): void {
        this.notifications = [];
    }
}
```

**Step 2: Wire WebSocket events to notification history**

Capture daemon events (pipeline complete, errors, silence warnings) as notifications.

**Step 3: Add command to view history**

```typescript
this.addCommand({
    id: "view-notifications",
    name: "View notification history",
    callback: () => {
        // Show a modal or leaf with notification list
    },
});
```

Could be a simple modal listing recent notifications with timestamps and colored icons.

**Step 4: Build, test, commit**

```bash
cd obsidian-recap && npm run build
git add obsidian-recap/src/
git commit -m "feat: add notification history for daemon events"
```

---

### Task 5: Reprocess command

**Files:**
- Modify: `obsidian-recap/src/main.ts`

**Step 1: Add reprocess command**

When viewing a meeting note, allow triggering reprocessing:

```typescript
this.addCommand({
    id: "reprocess-meeting",
    name: "Reprocess current meeting",
    checkCallback: (checking) => {
        const file = this.app.workspace.getActiveFile();
        if (file && file.path.includes("/Meetings/")) {
            if (!checking) {
                // Read recording path from frontmatter
                // Show stage picker (from which stage to reprocess)
                // POST to daemon /api/meetings/reprocess
            }
            return true;
        }
        return false;
    },
});
```

**Step 2: Build, test, commit**

```bash
cd obsidian-recap && npm run build
git add obsidian-recap/src/main.ts
git commit -m "feat: add reprocess command for meeting notes"
```

---

### Task 6: Push and verify

**Step 1: Build and install**

```bash
cd obsidian-recap && npm run build
```

**Step 2: Full plugin test**

1. Open Obsidian with plugin enabled and daemon running
2. Verify meeting list shows notes
3. Start recording via command palette
4. Verify status bar updates
5. Open live transcript view (should show "Recording" status)
6. Stop recording
7. Wait for pipeline, verify meeting note appears in list
8. If speakers unidentified, verify banner/notice appears
9. Open speaker correction modal, verify autocomplete works
10. Check notification history

**Step 3: Push**

```bash
git push
```
