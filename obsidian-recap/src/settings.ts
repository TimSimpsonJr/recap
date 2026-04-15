import { App, PluginSettingTab, Setting, Notice } from "obsidian";
import type { ApiOrg } from "./api";
import type RecapPlugin from "./main";

export class RecapSettingTab extends PluginSettingTab {
    plugin: RecapPlugin;
    // Local working copy of orgs, edited in place by the UI; flushed to
    // the daemon by the Save orgs button. Seeded from getConfig() on
    // each display(); a Refresh button reloads it.
    private orgsEdits: ApiOrg[] = [];

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
                    await this.plugin.reconnect();
                })
            );

        // Daemon status indicator
        const statusContainer = containerEl.createDiv({ cls: "recap-settings-status" });
        this.renderDaemonStatus(statusContainer);

        // OAuth section
        containerEl.createEl("h3", { text: "Calendar Providers" });

        const oauthContainer = containerEl.createDiv();
        this.renderOAuthProviders(oauthContainer);

        // Orgs section (Task 10)
        containerEl.createEl("h3", { text: "Organizations" });
        const orgsContainer = containerEl.createDiv({ cls: "recap-settings-orgs" });
        void this.renderOrgs(orgsContainer);
    }

    private async renderOrgs(container: HTMLElement): Promise<void> {
        container.empty();

        if (!this.plugin.client) {
            container.createEl("p", {
                text: "Connect to the daemon to manage organizations.",
                cls: "setting-item-description",
            });
            return;
        }

        let fetched: ApiOrg[];
        try {
            const cfg = await this.plugin.client.getConfig();
            fetched = cfg.orgs.map(o => ({ ...o }));
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: could not load orgs — ${msg}`);
            console.error("Recap:", e);
            container.createEl("p", {
                text: "Could not load orgs from daemon. See console for details.",
                cls: "setting-item-description",
            });
            return;
        }

        this.orgsEdits = fetched;
        this.renderOrgsList(container);
    }

    private renderOrgsList(container: HTMLElement): void {
        container.empty();

        if (this.orgsEdits.length === 0) {
            container.createEl("p", {
                text: "No orgs configured. Add one to get started.",
                cls: "setting-item-description",
            });
        }

        this.orgsEdits.forEach((org, index) => {
            const row = new Setting(container);
            row.setName(`Org ${index + 1}`);

            row.addText(text => text
                .setPlaceholder("name (e.g. work)")
                .setValue(org.name)
                .onChange(value => { org.name = value; })
            );
            row.addText(text => text
                .setPlaceholder("subfolder (e.g. _Recap/Work)")
                .setValue(org.subfolder)
                .onChange(value => { org.subfolder = value; })
            );
            row.addToggle(toggle => toggle
                .setTooltip("Default org")
                .setValue(org.default)
                .onChange(value => {
                    if (value) {
                        // Single-default semantics: clear all others.
                        this.orgsEdits.forEach((other, i) => {
                            other.default = i === index;
                        });
                        this.renderOrgsList(container);
                    } else {
                        org.default = false;
                    }
                })
            );
            row.addExtraButton(btn => btn
                .setIcon("trash")
                .setTooltip("Remove")
                .onClick(() => {
                    this.orgsEdits.splice(index, 1);
                    this.renderOrgsList(container);
                })
            );
        });

        new Setting(container)
            .addButton(btn => btn
                .setButtonText("Add org")
                .onClick(() => {
                    this.orgsEdits.push({
                        name: "",
                        subfolder: "",
                        default: this.orgsEdits.length === 0,
                    });
                    this.renderOrgsList(container);
                })
            )
            .addButton(btn => btn
                .setButtonText("Save orgs")
                .setCta()
                .onClick(async () => {
                    await this.saveOrgs();
                })
            );
    }

    private async saveOrgs(): Promise<void> {
        if (!this.plugin.client) {
            new Notice("Recap: Daemon not connected");
            return;
        }
        // Client-side validation: names must be non-empty and unique.
        const cleaned = this.orgsEdits
            .map(o => ({
                name: o.name.trim(),
                subfolder: o.subfolder.trim(),
                default: o.default,
            }))
            .filter(o => o.name.length > 0);
        const names = new Set<string>();
        for (const o of cleaned) {
            if (names.has(o.name)) {
                new Notice(`Recap: duplicate org name "${o.name}"`);
                return;
            }
            names.add(o.name);
        }
        const defaults = cleaned.filter(o => o.default);
        if (cleaned.length > 0 && defaults.length === 0) {
            new Notice("Recap: at least one org must be marked default");
            return;
        }
        if (defaults.length > 1) {
            new Notice("Recap: only one org can be marked default");
            return;
        }

        try {
            const resp = await this.plugin.client.patchConfig({
                orgs: cleaned,
            });
            const msg = resp.restart_required
                ? "Orgs saved. Restart the daemon (tray → Quit, then relaunch) to apply."
                : "Orgs saved.";
            new Notice(`Recap: ${msg}`);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: save orgs failed — ${msg}`);
            console.error("Recap:", e);
        }
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
