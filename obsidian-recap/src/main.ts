import { Plugin, Notice, TFile } from "obsidian";
import { DaemonClient, DaemonError, AttachEventConflict } from "./api";
import { RecapStatusBar } from "./components/StatusBarItem";
import { StartRecordingModal, OrgChoice } from "./components/StartRecordingModal";
import { RecapSettingTab } from "./settings";
import { MeetingListView, VIEW_MEETING_LIST } from "./views/MeetingListView";
import { LiveTranscriptView, VIEW_LIVE_TRANSCRIPT } from "./views/LiveTranscriptView";
import { SpeakerCorrectionModal } from "./views/SpeakerCorrectionModal";
import { CalendarEventPickerModal, CalendarEventCandidate } from "./views/CalendarEventPickerModal";
import { ConfirmReplaceModal } from "./views/ConfirmReplaceModal";
import type { Participant } from "./correction/resolve";
import { RenameProcessor } from "./renameProcessor";
import { NotificationHistory, NotificationHistoryModal } from "./notificationHistory";
import { DaemonLaunchSettings, DEFAULT_LAUNCH_SETTINGS } from "./launchSettings";
import { readAuthTokenWithRetry, AUTH_TOKEN_PATH } from "./authToken";
import { runLauncherStateMachine } from "./daemonLauncher";
import { noticeForOutcome } from "./daemonLauncherNotices";
import { vaultRelativeToConcrete } from "./vaultPaths";

// Obsidian plugins run inside Electron so Node built-ins are
// available via require(). The indirection through a runtime lookup
// keeps esbuild from trying to bundle "child_process" (a Node
// built-in not on the filesystem). At runtime Electron's require
// resolves the module normally.
const nodeRequire: NodeRequire = (globalThis as unknown as {
    require: NodeRequire;
}).require;
const { spawn } = nodeRequire("child_process") as typeof import("child_process");

interface RecapSettings extends DaemonLaunchSettings {
    daemonUrl: string;
}

const DEFAULT_SETTINGS: RecapSettings = {
    daemonUrl: "http://127.0.0.1:9847",
    ...DEFAULT_LAUNCH_SETTINGS,
};

export default class RecapPlugin extends Plugin {
    settings: RecapSettings = DEFAULT_SETTINGS;
    client: DaemonClient | null = null;
    statusBar: RecapStatusBar | null = null;
    renameProcessor: RenameProcessor | null = null;
    notificationHistory: NotificationHistory = new NotificationHistory();
    private lastKnownState: string = "idle";

    async onload() {
        await this.loadSettings();

        // Register views
        this.registerView(
            VIEW_MEETING_LIST,
            (leaf) => new MeetingListView(leaf, {
                getClient: () => this.client,
                onStartRecording: () => this.startRecordingInteractive(),
                onStopRecording: () => this.stopRecordingInteractive(),
                onLinkToCalendar: (file) => this.openLinkToCalendarFlow(file),
            }),
        );
        this.registerView(
            VIEW_LIVE_TRANSCRIPT,
            (leaf) => new LiveTranscriptView(leaf, async () => {
                if (!this.client) return null;
                try {
                    const status = await this.client.getStatus();
                    return status.state;
                } catch (e) {
                    console.error("Recap: live transcript status poll failed:", e);
                    return null;
                }
            }),
        );

        // Status bar (built before state machine so setOffline works)
        const statusBarEl = this.addStatusBarItem();
        this.statusBar = new RecapStatusBar(statusBarEl);

        // Default launcher log path: use vault's _Recap/.recap/launcher.log
        // resolved to the OS-absolute path via Obsidian's adapter.
        const defaultLogPath = vaultRelativeToConcrete(
            this.app.vault.adapter,
            "_Recap/.recap/launcher.log",
        );

        // Run the probe/spawn/poll state machine before building
        // DaemonClient. Outcome drives notice + status bar + rehydrate.
        const outcome = await runLauncherStateMachine({
            baseUrl: this.settings.daemonUrl,
            settings: this.settings,
            spawnFn: spawn as any,
            defaultLogPath,
        });
        const decision = noticeForOutcome(outcome);
        if (decision.notice) new Notice(decision.notice);

        if (decision.statusBarOffline) {
            this.statusBar.setOffline();
        }

        // Rename processor — no dependency on client, safe to run early
        this.renameProcessor = new RenameProcessor(this.app, "_Recap/.recap/rename-queue.json");
        await this.renameProcessor.processQueue();

        if (decision.shouldRehydrate) {
            await this.rehydrateClient();
        }

        // Commands
        this.addCommand({
            id: "start-recording",
            name: "Start recording",
            callback: () => this.startRecordingInteractive(),
        });

        this.addCommand({
            id: "stop-recording",
            name: "Stop recording",
            callback: () => this.stopRecordingInteractive(),
        });

        // Manual retry of the launcher state machine. Forces
        // autostartEnabled=true so this works even when the user has
        // globally disabled autostart — the point of a manual retry.
        this.addCommand({
            id: "start-daemon-now",
            name: "Start daemon now",
            callback: async () => {
                const defaultLogPath = vaultRelativeToConcrete(
                    this.app.vault.adapter,
                    "_Recap/.recap/launcher.log",
                );
                const outcome = await runLauncherStateMachine({
                    baseUrl: this.settings.daemonUrl,
                    settings: { ...this.settings, autostartEnabled: true },
                    spawnFn: spawn as any,
                    defaultLogPath,
                });
                const d = noticeForOutcome(outcome);
                if (d.notice) new Notice(d.notice);
                if (d.statusBarOffline) this.statusBar?.setOffline();
                if (d.shouldRehydrate) await this.rehydrateClient();
            },
        });

        this.addCommand({
            id: "open-dashboard",
            name: "Open meeting dashboard",
            callback: () => this.activateView(VIEW_MEETING_LIST),
        });

        this.addCommand({
            id: "open-live-transcript",
            name: "Open live transcript",
            callback: () => this.activateView(VIEW_LIVE_TRANSCRIPT),
        });

        this.addCommand({
            id: "view-notifications",
            name: "View notification history",
            callback: () => {
                new NotificationHistoryModal(this.app, this.notificationHistory).open();
            },
        });

        this.addCommand({
            id: "reprocess-meeting",
            name: "Reprocess current meeting",
            checkCallback: (checking) => {
                const file = this.app.workspace.getActiveFile();
                if (file && file.path.startsWith("_Recap/") && file.path.includes("/Meetings/")) {
                    if (!checking) {
                        this.reprocessMeeting(file);
                    }
                    return true;
                }
                return false;
            },
        });

        // Detect unidentified speakers on file open
        this.registerEvent(
            this.app.workspace.on("file-open", (file) => {
                if (!file || !this.client) return;
                if (!file.path.startsWith("_Recap/") || !file.path.includes("/Meetings/")) return;

                this.app.vault.cachedRead(file).then(content => {
                    if (content.includes("SPEAKER_")) {
                        new Notice(
                            "This meeting has unidentified speakers. Use 'Recap: Fix speakers' to correct them.",
                            10000,
                        );
                    }
                });
            }),
        );

        this.addCommand({
            id: "fix-speakers",
            name: "Fix unidentified speakers",
            checkCallback: (checking) => {
                const file = this.app.workspace.getActiveFile();
                if (file && file.path.startsWith("_Recap/") && file.path.includes("/Meetings/")) {
                    if (!checking) {
                        this.openSpeakerCorrection(file);
                    }
                    return true;
                }
                return false;
            },
        });

        this.addCommand({
            id: "recap-link-to-calendar-event",
            name: "Link to calendar event",
            checkCallback: (checking: boolean) => {
                const file = this.app.workspace.getActiveFile();
                if (!file) return false;
                const cache = this.app.metadataCache.getFileCache(file);
                const eventId = cache?.frontmatter?.["event-id"];
                const isUnscheduled = typeof eventId === "string"
                    && eventId.startsWith("unscheduled:");
                if (!isUnscheduled) return false;
                if (checking) return true;
                void this.openLinkToCalendarFlow(file);
                return true;
            },
        });

        // Settings tab
        this.addSettingTab(new RecapSettingTab(this.app, this));

        // Ribbon icon
        this.addRibbonIcon("mic", "Recap", () => this.activateView(VIEW_MEETING_LIST));
    }

    onunload() {
        this.notificationHistory.detach();
        this.client?.disconnectWebSocket();
    }

    /**
     * Shared entry point for both the command palette "Recap: Start
     * recording" command and the Meetings panel's Start button. Returns
     * once the picker has been opened (the actual daemon call happens in
     * the picker callback); the promise does NOT await the daemon.
     */
    async startRecordingInteractive(): Promise<void> {
        if (!this.client) {
            new Notice("Recap: Daemon not connected");
            return;
        }
        // Pull org list AND available analysis backends from the daemon
        // so the modal can offer both dropdowns. Each org carries its
        // configured ``default_backend`` so the common case (org X ->
        // backend Y) is one click; the user can override per-recording.
        let orgs: OrgChoice[] = [];
        let backends: string[] = ["claude", "ollama"];
        try {
            const resp = await this.client.get<{
                orgs: OrgChoice[];
                backends: string[];
            }>("/api/config/orgs");
            orgs = resp.orgs;
            if (resp.backends && resp.backends.length > 0) {
                backends = resp.backends;
            }
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: org list fetch failed — using default. ${msg}`);
            console.error("Recap:", e);
            orgs = [{ name: "default", default_backend: "claude" }];
        }
        new StartRecordingModal(this.app, orgs, backends, async ({ org, backend }) => {
            try {
                await this.client!.startRecording(org, backend);
                new Notice(`Recording started (${org}, ${backend})`);
            } catch (e) {
                new Notice(`Failed to start recording: ${e}`);
            }
        }).open();
    }

    /** Shared stop path used by the command palette and the panel button. */
    async stopRecordingInteractive(): Promise<void> {
        if (!this.client) {
            new Notice("Recap: Daemon not connected");
            return;
        }
        try {
            await this.client.stopRecording();
            new Notice("Recording stopped");
        } catch (e) {
            new Notice(`Failed to stop recording: ${e}`);
        }
    }

    /** Push a daemon state update to every open Meetings panel. */
    private broadcastDaemonState(state: string | null, org?: string): void {
        const leaves = this.app.workspace.getLeavesOfType(VIEW_MEETING_LIST);
        for (const leaf of leaves) {
            const view = leaf.view;
            if (view instanceof MeetingListView) {
                view.updateDaemonState(state, org);
            }
        }
    }

    async loadSettings() {
        this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    }

    async saveSettings() {
        await this.saveData(this.settings);
    }

    private async openSpeakerCorrection(file: TFile): Promise<void> {
        if (!this.client) {
            new Notice("Daemon not connected");
            return;
        }

        const cache = this.app.metadataCache.getFileCache(file);
        const fm = cache?.frontmatter;
        const recording = (fm?.recording ?? "").toString()
            .replace(/\[\[|\]\]/g, "");
        // Daemon's resolve_recording_path takes a bare stem, not a
        // filename; strip the .flac/.m4a/.aac extension. Matches the
        // FLAC->M4A ladder in recap/artifacts.py::resolve_recording_path.
        // ``.aac`` is included defensively for archived recordings that
        // may carry that extension.
        const stem = recording.replace(/\.(flac|m4a|aac)$/i, "");
        const org = (fm?.org ?? "").toString();
        const orgSubfolder = (fm?.["org-subfolder"] ?? "").toString();
        if (!stem) {
            new Notice("No recording in frontmatter");
            return;
        }
        if (!orgSubfolder) {
            new Notice("Missing org-subfolder in frontmatter");
            return;
        }

        // Daemon returns BOTH speakers (from transcript) AND participants
        // (from recording metadata sidecar, with emails for calendar-
        // sourced entries).
        let resp: {
            speakers: Array<{speaker_id: string; display: string}>;
            participants: Array<{name: string; email: string | null}>;
        };
        try {
            resp = await this.client.getMeetingSpeakers(stem);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Could not load speakers: ${msg}`);
            console.error("Recap:", e);
            return;
        }
        if (resp.speakers.length === 0) {
            new Notice("No speakers in transcript");
            return;
        }

        const peopleNames = this.scanNotesByFolder(`${orgSubfolder}/People`);
        const companyNames = this.scanNotesByFolder(
            `${orgSubfolder}/Companies`,
        );
        let knownContacts: import("./api").ApiKnownContact[] = [];
        try {
            const cfg = await this.client.getConfig();
            knownContacts = cfg.known_contacts || [];
        } catch (e) {
            console.warn("Recap: could not load known contacts", e);
        }

        // Participants come from the daemon (with emails for calendar
        // entries), not frontmatter — the frontmatter's participants
        // field is wikilinked names only and can't carry email hints.
        const meetingParticipants: Participant[] = resp.participants.map(p => ({
            name: p.name,
            email: p.email ?? undefined,
        }));

        new SpeakerCorrectionModal(
            this.app,
            resp.speakers,
            peopleNames,
            companyNames,
            knownContacts,
            meetingParticipants,
            stem,
            org,
            orgSubfolder,
            this.client,
        ).open();
    }

    private async openLinkToCalendarFlow(file: TFile): Promise<void> {
        if (!this.client) { new Notice("Daemon not connected"); return; }

        const cache = this.app.metadataCache.getFileCache(file);
        const fm = cache?.frontmatter;
        const recording = (fm?.recording ?? "").toString().replace(/\[\[|\]\]/g, "");
        const stem = recording.replace(/\.(flac|m4a|aac)$/i, "");
        const orgSubfolder = fm?.["org-subfolder"] || "";
        const recordingDate = fm?.date || "";
        if (!stem || !orgSubfolder || !recordingDate) {
            new Notice("Missing recording/date/org-subfolder in frontmatter");
            return;
        }

        const candidates = this.scanCalendarStubCandidates(
            orgSubfolder, recordingDate,
        );
        if (candidates.length === 0) {
            new Notice("No calendar events found within one day of this recording");
            return;
        }

        new CalendarEventPickerModal(this.app, candidates, async (picked) => {
            await this.submitAttachEvent(file, stem, picked.event_id);
        }).open();
    }

    private scanCalendarStubCandidates(
        orgSubfolder: string, recordingDate: string,
    ): CalendarEventCandidate[] {
        const prefix = orgSubfolder.endsWith("/")
            ? `${orgSubfolder}Meetings/`
            : `${orgSubfolder}/Meetings/`;
        const recordingDay = new Date(recordingDate + "T00:00:00Z");
        const out: CalendarEventCandidate[] = [];

        for (const file of this.app.vault.getMarkdownFiles()) {
            if (!file.path.startsWith(prefix)) continue;
            const fm = this.app.metadataCache.getFileCache(file)?.frontmatter;
            if (!fm) continue;
            const eventId = fm["event-id"];
            if (typeof eventId !== "string") continue;
            if (eventId.startsWith("unscheduled:")) continue;

            const date = fm.date;
            if (typeof date !== "string") continue;
            const eventDay = new Date(date + "T00:00:00Z");
            const diffDays = Math.abs(
                (eventDay.getTime() - recordingDay.getTime()) / (24 * 60 * 60 * 1000),
            );
            if (diffDays > 1) continue;

            out.push({
                event_id: eventId,
                title: String(fm.title ?? file.basename),
                date,
                time: String(fm.time ?? ""),
                calendar_source: String(fm["calendar-source"] ?? ""),
                note_path: file.path,
            });
        }
        // Design Section 6 locks "same date first, then by time" within the
        // +/-1 day window. Sort by absolute day-difference primarily so a
        // previous-day candidate cannot leapfrog the most-likely same-day
        // event; fall back to time, then date as a tie-breaker.
        out.sort((a, b) => {
            const aDay = new Date(a.date + "T00:00:00Z");
            const bDay = new Date(b.date + "T00:00:00Z");
            const aDiff = Math.abs((aDay.getTime() - recordingDay.getTime()) / 86400000);
            const bDiff = Math.abs((bDay.getTime() - recordingDay.getTime()) / 86400000);
            if (aDiff !== bDiff) return aDiff - bDiff;
            if (a.time !== b.time) return a.time.localeCompare(b.time);
            return a.date.localeCompare(b.date);
        });
        return out;
    }

    private async submitAttachEvent(
        sourceFile: TFile, stem: string, eventId: string, replace: boolean = false,
    ): Promise<void> {
        if (!this.client) return;
        try {
            const result = await this.client.attachEvent({stem, event_id: eventId, replace});
            new Notice(result.noop
                ? "Already bound to this event."
                : "Linked to calendar event. Opening note...");
            await this.openTargetNote(result.note_path);
        } catch (e) {
            if (e instanceof DaemonError) {
                if (e.status === 409 && e.body && typeof e.body === "object") {
                    const body = e.body as AttachEventConflict;
                    if (body.error === "recording_conflict") {
                        const confirmed = await new ConfirmReplaceModal(
                            this.app, body.existing_recording, stem,
                        ).prompt();
                        if (confirmed) {
                            await this.submitAttachEvent(sourceFile, stem, eventId, true);
                        }
                        return;
                    }
                }
                if (e.status === 400) {
                    new Notice(`Recap: ${e.message || "bad request"}`);
                    return;
                }
                if (e.status === 404) {
                    new Notice(`Recap: not found`);
                    return;
                }
            }
            new Notice(`Recap: link failed -- ${e}`);
        }
    }

    private async openTargetNote(notePath: string): Promise<void> {
        const file = this.app.vault.getAbstractFileByPath(notePath);
        if (file instanceof TFile) {
            await this.app.workspace.getLeaf().openFile(file);
        }
    }

    private scanNotesByFolder(folderPath: string): string[] {
        const prefix = folderPath.endsWith("/")
            ? folderPath : `${folderPath}/`;
        return this.app.vault.getMarkdownFiles()
            .filter(f => f.path.startsWith(prefix))
            .map(f => f.basename);
    }

    private async reprocessMeeting(file: TFile): Promise<void> {
        if (!this.client) {
            new Notice("Daemon not connected");
            return;
        }
        const cache = this.app.metadataCache.getFileCache(file);
        const frontmatter = cache?.frontmatter;
        const recordingPath = frontmatter?.recording?.replace(/\[\[|\]\]/g, "") || "";
        const org = frontmatter?.org || "";

        if (!recordingPath) {
            new Notice("No recording path found in frontmatter");
            return;
        }

        try {
            await this.client.reprocess(recordingPath, undefined, org);
            new Notice("Reprocessing started...");
        } catch (e) {
            new Notice(`Failed to reprocess: ${e}`);
        }
    }

    private connectWebSocket(): void {
        if (!this.client) return;

        // Bug 6: Re-fetch status on WebSocket connect to clear offline state
        this.client.on("_connected", async () => {
            this.statusBar?.setConnected();
            // Backfill any journal entries emitted while the daemon was unreachable;
            // DaemonClient keeps its onJournalEntry handlers across reconnects, but
            // HTTP tail of /api/events is only done here.
            void this.notificationHistory.load();
            try {
                const status = await this.client!.getStatus();
                this.lastKnownState = status.state;
                this.statusBar?.updateState(status.state, status.recording?.org);
                this.broadcastDaemonState(status.state, status.recording?.org);
            } catch {
                this.statusBar?.setOffline();
                this.broadcastDaemonState(null);
                new Notice("Recap: Reconnected, but daemon status refresh failed");
            }
        });

        // Status-bar + live-transcript updates driven by state_change.
        // Notification entries are produced by the daemon journal and streamed
        // to the plugin via WebSocket; see NotificationHistory.setClient.
        this.client.on("state_change", (event) => {
            const state = event.state as string;
            const org = event.org as string | undefined;
            this.lastKnownState = state;

            this.statusBar?.updateState(state, org);
            this.broadcastDaemonState(state, org);

            // Update live transcript view status
            const leaves = this.app.workspace.getLeavesOfType(VIEW_LIVE_TRANSCRIPT);
            for (const leaf of leaves) {
                (leaf.view as LiveTranscriptView).updateStatus(state);
            }
        });

        // Bug 2: Wire transcript_segment events to live transcript view
        this.client.on("transcript_segment", (event) => {
            const leaves = this.app.workspace.getLeavesOfType(VIEW_LIVE_TRANSCRIPT);
            for (const leaf of leaves) {
                (leaf.view as LiveTranscriptView).appendUtterance(
                    (event.speaker as string) || "UNKNOWN",
                    (event.text as string) || "",
                );
            }
        });

        // Wire error events (history entry comes from daemon journal over WS)
        this.client.on("error", (event) => {
            const message = (event.message as string) || "Unknown error";
            new Notice(`Recap error: ${message}`, 8000);
        });

        // Wire silence_warning events (history entry comes from daemon journal over WS)
        this.client.on("silence_warning", (event) => {
            const message = (event.message as string) || "Extended silence during recording";
            new Notice(`Recap: ${message}`, 8000);
        });

        // Wire rename_queued events to trigger rename processing
        this.client.on("rename_queued", async () => {
            await this.renameProcessor?.processQueue();
        });

        this.client.connectWebSocket(() => {
            this.statusBar?.setOffline();
            this.broadcastDaemonState(null);
        });
    }

    // Bug 5: Reconnect when daemon URL changes in settings
    async reconnect(): Promise<void> {
        this.client?.disconnectWebSocket();
        this.notificationHistory.detach();
        const token = await this.readAuthToken();
        if (token) {
            this.client = new DaemonClient(this.settings.daemonUrl, token);
            this.notificationHistory.setClient(this.client);
            this.connectWebSocket();
            try {
                const status = await this.client.getStatus();
                this.lastKnownState = status.state;
                this.statusBar?.updateState(status.state, status.recording?.org);
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                new Notice(`Recap: reconnection to daemon failed — ${msg}`);
                console.error("Recap:", e);
                this.statusBar?.setOffline();
            }
        } else {
            this.client = null;
            this.statusBar?.setOffline();
        }
    }

    private async readAuthToken(): Promise<string> {
        try {
            return await readAuthTokenWithRetry(
                this.app.vault.adapter,
                AUTH_TOKEN_PATH,
                1,  // single attempt for initial onload; rehydrateClient retries
            );
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: could not read auth token — ${msg}`);
            console.error("Recap:", e);
            return "";
        }
    }

    /**
     * Re-read the auth token, rebuild DaemonClient, and reconnect.
     *
     * Used after a plugin-spawned daemon start (token file appears AFTER
     * onload's initial read). Retries a few times because the daemon
     * writes the token shortly after binding the port.
     */
    async rehydrateClient(): Promise<boolean> {
        const token = await readAuthTokenWithRetry(this.app.vault.adapter);
        if (!token) {
            new Notice(
                `Recap: daemon running but auth token not found at ${AUTH_TOKEN_PATH}. ` +
                "Re-pair via tray menu."
            );
            return false;
        }
        this.client?.disconnectWebSocket();
        this.notificationHistory.detach();
        this.client = new DaemonClient(this.settings.daemonUrl, token);
        this.notificationHistory.setClient(this.client);
        this.connectWebSocket();
        try {
            const status = await this.client.getStatus();
            this.lastKnownState = status.state;
            this.statusBar?.updateState(status.state, status.recording?.org);
            return true;
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: post-spawn status fetch failed — ${msg}`);
            this.statusBar?.setOffline();
            return false;
        }
    }

    async activateView(viewType: string): Promise<void> {
        const { workspace } = this.app;
        let leaf = workspace.getLeavesOfType(viewType)[0];
        if (!leaf) {
            const newLeaf = workspace.getRightLeaf(false);
            if (newLeaf) {
                await newLeaf.setViewState({ type: viewType, active: true });
                leaf = newLeaf;
            }
        }
        if (leaf) {
            workspace.revealLeaf(leaf);
        }

        // Bug 4: If opening the live transcript, sync it with the current daemon state
        if (viewType === VIEW_LIVE_TRANSCRIPT && this.client) {
            const leaves = workspace.getLeavesOfType(VIEW_LIVE_TRANSCRIPT);
            for (const l of leaves) {
                const view = l.view as LiveTranscriptView;
                try {
                    const status = await this.client.getStatus();
                    view.updateStatus(status.state);
                } catch (e) {
                    const msg = e instanceof Error ? e.message : String(e);
                    new Notice(`Recap: could not sync live transcript view — ${msg}`);
                    console.error("Recap:", e);
                }
            }
        }
    }
}
