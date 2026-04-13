import { Plugin, Notice } from "obsidian";
import { DaemonClient } from "./api";
import { RecapStatusBar } from "./components/StatusBarItem";
import { OrgPickerModal } from "./components/OrgPickerModal";

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

    async onload() {
        await this.loadSettings();

        // Read auth token from vault
        const tokenPath = "_Recap/.recap/auth-token";
        let token = "";
        try {
            token = (await this.app.vault.adapter.read(tokenPath)).trim();
        } catch {
            new Notice("Recap: Could not read daemon auth token. Check _Recap/.recap/auth-token");
        }

        if (token) {
            this.client = new DaemonClient(this.settings.daemonUrl, token);
        }

        // Status bar
        const statusBarEl = this.addStatusBarItem();
        this.statusBar = new RecapStatusBar(statusBarEl);

        // WebSocket connection
        if (this.client) {
            this.client.on("state_change", (event) => {
                this.statusBar?.updateState(
                    event.state as string,
                    event.org as string | undefined,
                );
            });
            this.client.connectWebSocket(() => {
                this.statusBar?.setOffline();
            });
            // Initial status fetch
            try {
                const status = await this.client.getStatus();
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
            callback: () => {
                if (!this.client) {
                    new Notice("Recap: Daemon not connected");
                    return;
                }
                // TODO: get org list from daemon config
                const orgs = ["disbursecloud", "personal", "activism"];
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
            callback: () => {
                new Notice("Meeting dashboard not yet implemented");
            },
        });

        // Ribbon icon
        this.addRibbonIcon("mic", "Recap", () => {
            new Notice("Meeting dashboard not yet implemented");
        });
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
}
