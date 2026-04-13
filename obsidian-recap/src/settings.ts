import { App, PluginSettingTab, Setting, Notice } from "obsidian";
import type RecapPlugin from "./main";

export class RecapSettingTab extends PluginSettingTab {
    plugin: RecapPlugin;

    constructor(app: App, plugin: RecapPlugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display(): void {
        const { containerEl } = this;
        containerEl.empty();

        containerEl.createEl("h2", { text: "Recap Settings" });

        // Connection section
        containerEl.createEl("h3", { text: "Daemon Connection" });

        new Setting(containerEl)
            .setName("Daemon URL")
            .setDesc("The URL of the Recap daemon (default: http://localhost:9847)")
            .addText(text => text
                .setPlaceholder("http://localhost:9847")
                .setValue(this.plugin.settings.daemonUrl)
                .onChange(async (value) => {
                    this.plugin.settings.daemonUrl = value;
                    await this.plugin.saveSettings();
                })
            );

        // Daemon status indicator
        const statusContainer = containerEl.createDiv({ cls: "recap-settings-status" });
        this.renderDaemonStatus(statusContainer);

        // OAuth section
        containerEl.createEl("h3", { text: "Calendar Providers" });

        const oauthContainer = containerEl.createDiv();
        this.renderOAuthProviders(oauthContainer);
    }

    private async renderDaemonStatus(container: HTMLElement): Promise<void> {
        container.empty();
        const statusEl = container.createDiv({ cls: "recap-daemon-status" });

        if (!this.plugin.client) {
            statusEl.createSpan({ text: "Not connected", cls: "recap-status-offline" });
            statusEl.createEl("p", {
                text: "Could not read auth token from _Recap/.recap/auth-token. Is the daemon running?",
                cls: "setting-item-description",
            });
            return;
        }

        try {
            const status = await this.plugin.client.getStatus();
            statusEl.createSpan({ text: "Connected", cls: "recap-status-connected" });
            statusEl.createEl("p", {
                text: `State: ${status.state} | Last calendar sync: ${status.last_calendar_sync || "never"}`,
                cls: "setting-item-description",
            });
        } catch {
            statusEl.createSpan({ text: "Daemon offline", cls: "recap-status-offline" });
        }
    }

    private async renderOAuthProviders(container: HTMLElement): Promise<void> {
        container.empty();

        if (!this.plugin.client) {
            container.createEl("p", { text: "Connect to daemon first to manage calendar providers." });
            return;
        }

        for (const provider of ["zoho", "google"]) {
            const providerDiv = container.createDiv({ cls: "recap-oauth-provider" });

            try {
                const status = await this.plugin.client.getOAuthStatus(provider);
                new Setting(providerDiv)
                    .setName(provider.charAt(0).toUpperCase() + provider.slice(1) + " Calendar")
                    .setDesc(status.connected ? "Connected" : "Not connected")
                    .addButton(button => {
                        if (status.connected) {
                            button.setButtonText("Disconnect")
                                .setWarning()
                                .onClick(async () => {
                                    await this.plugin.client!.disconnectOAuth(provider);
                                    new Notice(`${provider} disconnected`);
                                    this.renderOAuthProviders(container);
                                });
                        } else {
                            button.setButtonText("Connect")
                                .setCta()
                                .onClick(async () => {
                                    try {
                                        const result = await this.plugin.client!.startOAuth(provider);
                                        // Open the authorization URL in the browser
                                        window.open(result.authorize_url);
                                        new Notice(`Complete ${provider} authorization in your browser`);
                                    } catch (e) {
                                        new Notice(`Failed to start OAuth: ${e}`);
                                    }
                                });
                        }
                    });
            } catch {
                new Setting(providerDiv)
                    .setName(provider.charAt(0).toUpperCase() + provider.slice(1) + " Calendar")
                    .setDesc("Could not check status");
            }
        }
    }
}
