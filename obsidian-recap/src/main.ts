import { Plugin, Notice, TFile } from "obsidian";
import { DaemonClient } from "./api";
import { RecapStatusBar } from "./components/StatusBarItem";
import { StartRecordingModal, OrgChoice } from "./components/StartRecordingModal";
import { RecapSettingTab } from "./settings";
import { MeetingListView, VIEW_MEETING_LIST } from "./views/MeetingListView";
import { LiveTranscriptView, VIEW_LIVE_TRANSCRIPT } from "./views/LiveTranscriptView";
import { SpeakerCorrectionModal, SpeakerInfo } from "./views/SpeakerCorrectionModal";
import { RenameProcessor } from "./renameProcessor";
import { NotificationHistory, NotificationHistoryModal } from "./notificationHistory";
import { DaemonLaunchSettings, DEFAULT_LAUNCH_SETTINGS } from "./launchSettings";
import { readAuthTokenWithRetry, AUTH_TOKEN_PATH } from "./authToken";

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

        // Read auth token from vault
        const token = await this.readAuthToken();
        if (!token) {
            new Notice("Recap: Could not read daemon auth token. Check _Recap/.recap/auth-token");
        }

        if (token) {
            this.client = new DaemonClient(this.settings.daemonUrl, token);
            this.notificationHistory.setClient(this.client);
        }

        // Status bar
        const statusBarEl = this.addStatusBarItem();
        this.statusBar = new RecapStatusBar(statusBarEl);

        // Rename processor
        this.renameProcessor = new RenameProcessor(this.app, "_Recap/.recap/rename-queue.json");
        await this.renameProcessor.processQueue();

        // WebSocket connection
        if (this.client) {
            this.connectWebSocket();
            // Initial status fetch
            try {
                const status = await this.client.getStatus();
                this.lastKnownState = status.state;
                this.statusBar.updateState(status.state, status.recording?.org);
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                new Notice(`Recap: initial daemon status fetch failed — ${msg}`);
                console.error("Recap:", e);
                this.statusBar.setOffline();
            }
        } else {
            this.statusBar.setOffline();
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

        const content = await this.app.vault.cachedRead(file);

        // Extract SPEAKER_XX labels from content
        const speakerLabels = [...new Set(
            (content.match(/SPEAKER_\d+/g) || [])
        )];

        if (speakerLabels.length === 0) {
            new Notice("No unidentified speakers found in this note");
            return;
        }

        // Get people names from vault
        const peopleFiles = this.app.vault.getMarkdownFiles().filter(f =>
            f.path.startsWith("_Recap/") && f.path.includes("/People/")
        );
        const peopleNames = peopleFiles.map(f => f.basename);

        // Get recording path and org from frontmatter
        const cache = this.app.metadataCache.getFileCache(file);
        const frontmatter = cache?.frontmatter;
        const recordingPath = frontmatter?.recording?.replace(/\[\[|\]\]/g, "") || "";
        const org = frontmatter?.org || "";

        const speakers: SpeakerInfo[] = speakerLabels.map(label => ({
            label,
            sampleClipPath: "", // TODO: daemon could serve sample clips
        }));

        new SpeakerCorrectionModal(
            this.app,
            speakers,
            peopleNames,
            [], // known contacts - could fetch from daemon
            recordingPath,
            org,
            this.client,
        ).open();
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
