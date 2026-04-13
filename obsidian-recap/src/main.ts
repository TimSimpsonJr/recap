import { Plugin, Notice, TFile } from "obsidian";
import { DaemonClient } from "./api";
import { RecapStatusBar } from "./components/StatusBarItem";
import { OrgPickerModal } from "./components/OrgPickerModal";
import { RecapSettingTab } from "./settings";
import { MeetingListView, VIEW_MEETING_LIST } from "./views/MeetingListView";
import { LiveTranscriptView, VIEW_LIVE_TRANSCRIPT } from "./views/LiveTranscriptView";
import { SpeakerCorrectionModal, SpeakerInfo } from "./views/SpeakerCorrectionModal";
import { RenameProcessor } from "./renameProcessor";
import { NotificationHistory, NotificationHistoryModal } from "./notificationHistory";

interface RecapSettings {
    daemonUrl: string;
}

const DEFAULT_SETTINGS: RecapSettings = {
    daemonUrl: "http://localhost:9847",
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
        this.registerView(VIEW_MEETING_LIST, (leaf) => new MeetingListView(leaf));
        this.registerView(VIEW_LIVE_TRANSCRIPT, (leaf) => new LiveTranscriptView(leaf));

        // Read auth token from vault
        const token = await this.readAuthToken();
        if (!token) {
            new Notice("Recap: Could not read daemon auth token. Check _Recap/.recap/auth-token");
        }

        if (token) {
            this.client = new DaemonClient(this.settings.daemonUrl, token);
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
            } catch {
                this.statusBar.setOffline();
            }
        } else {
            this.statusBar.setOffline();
        }

        // Commands
        this.addCommand({
            id: "start-recording",
            name: "Start recording",
            callback: async () => {
                if (!this.client) {
                    new Notice("Recap: Daemon not connected");
                    return;
                }
                // Fetch org list from daemon config endpoint
                let orgs: string[] = [];
                try {
                    const resp = await this.client!.get<{orgs: string[]}>("/api/config/orgs");
                    orgs = resp.orgs;
                } catch {
                    orgs = ["default"];
                }
                new OrgPickerModal(this.app, orgs, async (org) => {
                    try {
                        await this.client!.startRecording(org);
                        new Notice(`Recording started (${org})`);
                    } catch (e) {
                        new Notice(`Failed to start recording: ${e}`);
                    }
                }).open();
            },
        });

        this.addCommand({
            id: "stop-recording",
            name: "Stop recording",
            callback: async () => {
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

        // Settings tab
        this.addSettingTab(new RecapSettingTab(this.app, this));

        // Ribbon icon
        this.addRibbonIcon("mic", "Recap", () => this.activateView(VIEW_MEETING_LIST));
    }

    onunload() {
        this.client?.disconnectWebSocket();
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
            try {
                const status = await this.client!.getStatus();
                this.lastKnownState = status.state;
                this.statusBar?.updateState(status.state, status.recording?.org);
            } catch { /* will retry on next reconnect */ }
        });

        // Bug 3: Wire state_change to notifications using actual daemon events
        this.client.on("state_change", (event) => {
            const previousState = this.lastKnownState;
            const state = event.state as string;
            this.lastKnownState = state;

            this.statusBar?.updateState(state, event.org as string | undefined);

            // Update live transcript view status
            const leaves = this.app.workspace.getLeavesOfType(VIEW_LIVE_TRANSCRIPT);
            for (const leaf of leaves) {
                (leaf.view as LiveTranscriptView).updateStatus(state);
            }

            // Generate notifications from state transitions
            if (state === "recording") {
                this.notificationHistory.add("info", "Recording Started", `Recording for ${event.org || "unknown"}`);
            } else if (state === "processing") {
                this.notificationHistory.add("info", "Processing", "Pipeline running...");
            } else if (state === "idle" && previousState === "processing") {
                this.notificationHistory.add("info", "Complete", "Meeting processed");
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

        // Wire error events
        this.client.on("error", (event) => {
            this.notificationHistory.add("error", "Daemon Error", (event.message as string) || "Unknown error");
        });

        // Wire silence_warning events
        this.client.on("silence_warning", (event) => {
            this.notificationHistory.add("warning", "Silence Detected", (event.message as string) || "Extended silence during recording");
        });

        // Wire rename_queued events to trigger rename processing
        this.client.on("rename_queued", async () => {
            await this.renameProcessor?.processQueue();
        });

        this.client.connectWebSocket(() => {
            this.statusBar?.setOffline();
        });
    }

    // Bug 5: Reconnect when daemon URL changes in settings
    async reconnect(): Promise<void> {
        this.client?.disconnectWebSocket();
        const token = await this.readAuthToken();
        if (token) {
            this.client = new DaemonClient(this.settings.daemonUrl, token);
            this.connectWebSocket();
            try {
                const status = await this.client.getStatus();
                this.lastKnownState = status.state;
                this.statusBar?.updateState(status.state, status.recording?.org);
            } catch {
                this.statusBar?.setOffline();
            }
        } else {
            this.client = null;
            this.statusBar?.setOffline();
        }
    }

    private async readAuthToken(): Promise<string> {
        const tokenPath = "_Recap/.recap/auth-token";
        try {
            return (await this.app.vault.adapter.read(tokenPath)).trim();
        } catch {
            return "";
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
                } catch { /* daemon offline, view already shows idle */ }
            }
        }
    }
}
