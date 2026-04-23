import { App, PluginSettingTab, Setting, Notice } from "obsidian";
import type {
    ApiCalendarProvider,
    ApiConfigDto,
    ApiDetectionRule,
    ApiKnownContact,
    ApiOrg,
} from "./api";
import type RecapPlugin from "./main";

export class RecapSettingTab extends PluginSettingTab {
    plugin: RecapPlugin;
    // Working copies edited in place by each section's UI; flushed to
    // the daemon by their Save button. Seeded from a single
    // getConfig() call per display().
    private orgsEdits: ApiOrg[] = [];
    private detectionEdits: Record<string, Partial<ApiDetectionRule>> = {};
    private calendarEdits: Record<string, Partial<ApiCalendarProvider>> = {};
    private contactsEdits: ApiKnownContact[] = [];

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
            .setDesc("The URL of the Recap daemon (default: http://127.0.0.1:9847)")
            .addText(text => text
                .setPlaceholder("http://127.0.0.1:9847")
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

        // Config-backed sections (Tasks 10-11). All four sections share
        // a single /api/config fetch so the UI is internally consistent.
        containerEl.createEl("h3", { text: "Organizations" });
        const orgsContainer = containerEl.createDiv({ cls: "recap-settings-orgs" });

        containerEl.createEl("h3", { text: "Meeting detection" });
        const detectionContainer = containerEl.createDiv({
            cls: "recap-settings-detection",
        });

        containerEl.createEl("h3", { text: "Calendar sync" });
        const calendarContainer = containerEl.createDiv({
            cls: "recap-settings-calendar",
        });

        containerEl.createEl("h3", { text: "Known contacts" });
        const contactsContainer = containerEl.createDiv({
            cls: "recap-settings-contacts",
        });

        containerEl.createEl("h3", { text: "Daemon lifecycle" });
        const daemonContainer = containerEl.createDiv({
            cls: "recap-settings-daemon",
        });

        void this.loadConfigSections({
            orgs: orgsContainer,
            detection: detectionContainer,
            calendar: calendarContainer,
            contacts: contactsContainer,
        });
        void this.renderDaemonLifecycle(daemonContainer);

        containerEl.createEl("h3", { text: "Daemon launch" });
        const launchContainer = containerEl.createDiv({
            cls: "recap-settings-launch",
        });
        this.renderLaunchSection(launchContainer);
    }

    private renderLaunchSection(el: HTMLElement): void {
        new Setting(el)
            .setName("Auto-start daemon with Obsidian")
            .setDesc(
                "When enabled, the plugin starts the daemon if it's not already "
                + "running. Disable if you manage the daemon separately (e.g. via "
                + "an OS scheduler)."
            )
            .addToggle(t => t
                .setValue(this.plugin.settings.autostartEnabled)
                .onChange(async (v) => {
                    this.plugin.settings.autostartEnabled = v;
                    await this.plugin.saveSettings();
                }),
            );

        new Setting(el)
            .setName("Launcher executable")
            .setDesc(
                "Full path to Python/uv executable or a binary name on PATH. "
                + "Example: 'uv' or 'C:\\Python312\\python.exe'."
            )
            .addText(t => t
                .setPlaceholder("uv")
                .setValue(this.plugin.settings.launcherExecutable)
                .onChange(async (v) => {
                    this.plugin.settings.launcherExecutable = v.trim();
                    await this.plugin.saveSettings();
                }),
            );

        new Setting(el)
            .setName("Launcher arguments")
            .setDesc(
                "One argument per line. Typical: 'run', 'python', '-m', "
                + "'recap.launcher', 'config.yaml'."
            )
            .addTextArea(t => {
                t.setPlaceholder("run\npython\n-m\nrecap.launcher\nconfig.yaml")
                 .setValue(this.plugin.settings.launcherArgs.join("\n"))
                 .onChange(async (v) => {
                     this.plugin.settings.launcherArgs = v.split("\n")
                         .map(s => s.trim())
                         .filter(s => s.length > 0);
                     await this.plugin.saveSettings();
                 });
                t.inputEl.rows = 6;
                return t;
            });

        new Setting(el)
            .setName("Working directory")
            .setDesc(
                "Usually the Recap repo root. Used as the cwd for the spawned "
                + "launcher. Example: 'C:\\Users\\you\\Documents\\Projects\\recap'."
            )
            .addText(t => t
                .setPlaceholder("C:\\Users\\you\\Documents\\Projects\\recap")
                .setValue(this.plugin.settings.launcherCwd)
                .onChange(async (v) => {
                    this.plugin.settings.launcherCwd = v.trim();
                    await this.plugin.saveSettings();
                }),
            );

        new Setting(el)
            .setName("Launcher log path")
            .setDesc(
                "Absolute path for launcher.log. Leave blank to use "
                + "'{vault}/_Recap/.recap/launcher.log'."
            )
            .addText(t => t
                .setPlaceholder("(default)")
                .setValue(this.plugin.settings.launcherLogPath)
                .onChange(async (v) => {
                    this.plugin.settings.launcherLogPath = v.trim();
                    await this.plugin.saveSettings();
                }),
            );

        new Setting(el)
            .setName("Start daemon now")
            .setDesc(
                "Spawn the launcher immediately using the current settings "
                + "without waiting for an Obsidian reload. Useful after fixing a "
                + "configuration error."
            )
            .addButton(b => b
                .setButtonText("Start daemon now")
                .setCta()
                .onClick(async () => {
                    // Invoke the registered command. The command id is scoped
                    // by Obsidian to "{plugin-id}:{command-id}". Plugin id is
                    // "recap" per obsidian-recap/manifest.json.
                    interface CommandsLike {
                        executeCommandById?: (id: string) => boolean;
                    }
                    const cmds = (this.app as unknown as { commands?: CommandsLike }).commands;
                    if (cmds?.executeCommandById) {
                        cmds.executeCommandById("recap:start-daemon-now");
                    } else {
                        new Notice("Recap: 'Start daemon now' command not available. Reload plugin.");
                    }
                }),
            );
    }

    private async loadConfigSections(containers: {
        orgs: HTMLElement;
        detection: HTMLElement;
        calendar: HTMLElement;
        contacts: HTMLElement;
    }): Promise<void> {
        if (!this.plugin.client) {
            const hint = "Connect to the daemon to manage this section.";
            for (const el of Object.values(containers)) {
                el.empty();
                el.createEl("p", { text: hint, cls: "setting-item-description" });
            }
            return;
        }

        let cfg: ApiConfigDto;
        try {
            cfg = await this.plugin.client.getConfig();
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: could not load config — ${msg}`);
            console.error("Recap:", e);
            for (const el of Object.values(containers)) {
                el.empty();
                el.createEl("p", {
                    text: "Could not load config from daemon. See console for details.",
                    cls: "setting-item-description",
                });
            }
            return;
        }

        this.orgsEdits = cfg.orgs.map(o => ({ ...o }));
        this.detectionEdits = Object.fromEntries(
            Object.entries(cfg.detection).map(([k, v]) => [k, { ...v }]),
        );
        this.calendarEdits = Object.fromEntries(
            Object.entries(cfg.calendar).map(([k, v]) => [k, { ...v }]),
        );
        this.contactsEdits = cfg.known_contacts.map(c => ({
            ...c,
            aliases: [...c.aliases],
        }));

        this.renderOrgsList(containers.orgs);
        this.renderDetectionSection(containers.detection);
        this.renderCalendarSection(containers.calendar);
        this.renderContactsSection(containers.contacts);
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

    // ---- Detection ----

    private renderDetectionSection(container: HTMLElement): void {
        container.empty();

        const platforms = Object.keys(this.detectionEdits);
        if (platforms.length === 0) {
            container.createEl("p", {
                text: "No detection rules configured.",
                cls: "setting-item-description",
            });
            return;
        }

        for (const platform of platforms) {
            const rule = this.detectionEdits[platform];
            const row = new Setting(container).setName(platform);
            row.addToggle(toggle => toggle
                .setTooltip("Enabled")
                .setValue(rule.enabled ?? false)
                .onChange(value => { rule.enabled = value; })
            );
            row.addDropdown(drop => drop
                .addOption("auto-record", "auto-record")
                .addOption("prompt", "prompt")
                .setValue(rule.behavior ?? "prompt")
                .onChange(value => {
                    rule.behavior = value as "auto-record" | "prompt";
                })
            );
        }

        new Setting(container).addButton(btn => btn
            .setButtonText("Save detection")
            .setCta()
            .onClick(async () => {
                await this.saveDetection();
            })
        );
    }

    private async saveDetection(): Promise<void> {
        if (!this.plugin.client) {
            new Notice("Recap: Daemon not connected");
            return;
        }
        try {
            const resp = await this.plugin.client.patchConfig({
                detection: this.detectionEdits as Record<
                    string, ApiDetectionRule
                >,
            });
            const msg = resp.restart_required
                ? "Detection saved. Restart the daemon to apply."
                : "Detection saved.";
            new Notice(`Recap: ${msg}`);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: save detection failed — ${msg}`);
            console.error("Recap:", e);
        }
    }

    // ---- Calendar ----

    private renderCalendarSection(container: HTMLElement): void {
        container.empty();

        const providers = Object.keys(this.calendarEdits);
        if (providers.length === 0) {
            container.createEl("p", {
                text: "No calendar providers configured.",
                cls: "setting-item-description",
            });
            return;
        }

        for (const provider of providers) {
            const cfg = this.calendarEdits[provider];
            const row = new Setting(container).setName(provider);
            row.addToggle(toggle => toggle
                .setTooltip("Enabled")
                .setValue(cfg.enabled ?? false)
                .onChange(value => { cfg.enabled = value; })
            );
            row.addText(text => text
                .setPlaceholder("calendar id")
                .setValue(cfg.calendar_id ?? "")
                .onChange(value => {
                    cfg.calendar_id = value.trim() === "" ? null : value;
                })
            );
            row.addText(text => text
                .setPlaceholder("org")
                .setValue(cfg.org ?? "")
                .onChange(value => {
                    cfg.org = value.trim() === "" ? null : value;
                })
            );
        }

        new Setting(container).addButton(btn => btn
            .setButtonText("Save calendar")
            .setCta()
            .onClick(async () => {
                await this.saveCalendar();
            })
        );
    }

    private async saveCalendar(): Promise<void> {
        if (!this.plugin.client) {
            new Notice("Recap: Daemon not connected");
            return;
        }
        try {
            const resp = await this.plugin.client.patchConfig({
                calendar: this.calendarEdits as Record<
                    string, ApiCalendarProvider
                >,
            });
            const msg = resp.restart_required
                ? "Calendar saved. Restart the daemon to apply."
                : "Calendar saved.";
            new Notice(`Recap: ${msg}`);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: save calendar failed — ${msg}`);
            console.error("Recap:", e);
        }
    }

    // ---- Contacts ----

    private renderContactsSection(container: HTMLElement): void {
        container.empty();

        if (this.contactsEdits.length === 0) {
            container.createEl("p", {
                text: "No known contacts yet. Add one to help the pipeline map speakers to people.",
                cls: "setting-item-description",
            });
        }

        this.contactsEdits.forEach((contact, index) => {
            const row = new Setting(container).setName(`Contact ${index + 1}`);
            row.addText(text => text
                .setPlaceholder("name")
                .setValue(contact.name)
                .onChange(value => { contact.name = value; })
            );
            row.addText(text => text
                .setPlaceholder("display name (for speaker matching)")
                .setValue(contact.display_name ?? "")
                .onChange(value => {
                    contact.display_name =
                        value.trim() === "" ? null : value;
                })
            );
            row.addText(text => text
                .setPlaceholder("aliases (comma-separated)")
                .setValue(contact.aliases.join(", "))
                .onChange(value => {
                    contact.aliases = value
                        .split(",")
                        .map(s => s.trim())
                        .filter(s => s.length > 0);
                })
            );
            row.addText(text => text
                .setPlaceholder("email")
                .setValue(contact.email ?? "")
                .onChange(value => {
                    contact.email = value.trim() === "" ? null : value;
                })
            );
            row.addExtraButton(btn => btn
                .setIcon("trash")
                .setTooltip("Remove")
                .onClick(() => {
                    this.contactsEdits.splice(index, 1);
                    this.renderContactsSection(container);
                })
            );
        });

        new Setting(container)
            .addButton(btn => btn
                .setButtonText("Add contact")
                .onClick(() => {
                    this.contactsEdits.push({
                        name: "",
                        aliases: [],
                        email: null,
                        display_name: null,
                    });
                    this.renderContactsSection(container);
                })
            )
            .addButton(btn => btn
                .setButtonText("Save contacts")
                .setCta()
                .onClick(async () => {
                    await this.saveContacts();
                })
            );
    }

    private async saveContacts(): Promise<void> {
        if (!this.plugin.client) {
            new Notice("Recap: Daemon not connected");
            return;
        }
        const cleaned = this.contactsEdits
            .map(c => ({
                name: c.name.trim(),
                aliases: c.aliases,
                email: c.email,
                display_name: c.display_name,
            }))
            .filter(c => c.name.length > 0);
        try {
            const resp = await this.plugin.client.patchConfig({
                known_contacts: cleaned,
            });
            const msg = resp.restart_required
                ? "Contacts saved. Restart the daemon to apply."
                : "Contacts saved.";
            new Notice(`Recap: ${msg}`);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: save contacts failed — ${msg}`);
            console.error("Recap:", e);
        }
    }

    // ---- Daemon lifecycle ----

    private async renderDaemonLifecycle(container: HTMLElement): Promise<void> {
        container.empty();

        if (!this.plugin.client) {
            container.createEl("p", {
                text: "Connect to the daemon to see lifecycle info.",
                cls: "setting-item-description",
            });
            return;
        }

        let stateLine = "State: unknown";
        // The daemon only advertises ``can_restart: true`` when launched
        // via ``recap.launcher`` (env ``RECAP_MANAGED=1``). Standalone
        // daemons can shut down but cannot self-restart -- button is
        // disabled with an explanation below.
        let canRestart = false;
        try {
            const status = await this.plugin.client.getStatus();
            const uptime = Math.floor(status.uptime_seconds || 0);
            stateLine = `State: ${status.state}, uptime: ${uptime}s`;
            canRestart = Boolean(status.can_restart);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            stateLine = `State: unreachable \u2014 ${msg}`;
            console.error("Recap:", e);
        }

        container.createEl("p", {
            text: stateLine,
            cls: "setting-item-description",
        });

        const restartSetting = new Setting(container)
            .setName("Restart daemon")
            .setDesc(
                canRestart
                    ? "Ask the daemon to shut down; the launcher wrapper "
                      + "will spawn a fresh child automatically."
                    : "Daemon is running standalone. Relaunch via "
                      + "'uv run python -m recap.launcher <config-path>' "
                      + "to enable one-click restarts from here.",
            );
        restartSetting.addButton(btn => {
            btn.setButtonText("Restart daemon");
            if (!canRestart) {
                btn.setDisabled(true);
                return;
            }
            btn.setCta().onClick(async () => {
                btn.setDisabled(true);
                btn.setButtonText("Restarting\u2026");
                try {
                    await this.plugin.client!.requestShutdown(true);
                    new Notice(
                        "Recap: restart requested. The daemon will be back "
                        + "in a few seconds.",
                        6000,
                    );
                } catch (e) {
                    const msg = e instanceof Error ? e.message : String(e);
                    new Notice(`Recap: restart failed \u2014 ${msg}`, 8000);
                    btn.setDisabled(false);
                    btn.setButtonText("Restart daemon");
                }
            });
        });
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
        } catch (e) {
            statusEl.createSpan({ text: "Daemon offline", cls: "recap-status-offline" });
            console.error("Recap: daemon status fetch failed:", e);
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
            } catch (e) {
                new Setting(providerDiv)
                    .setName(provider.charAt(0).toUpperCase() + provider.slice(1) + " Calendar")
                    .setDesc("Could not check status");
                console.error("Recap:", e);
            }
        }
    }
}
