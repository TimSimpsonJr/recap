var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/main.ts
var main_exports = {};
__export(main_exports, {
  default: () => RecapPlugin
});
module.exports = __toCommonJS(main_exports);
var import_obsidian9 = require("obsidian");

// src/api.ts
var import_obsidian = require("obsidian");
var DaemonError = class extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
    this.name = "DaemonError";
  }
};
var DaemonClient = class {
  baseUrl;
  token;
  ws = null;
  reconnectTimer = null;
  eventHandlers = /* @__PURE__ */ new Map();
  constructor(baseUrl, token) {
    this.baseUrl = baseUrl;
    this.token = token;
  }
  // --- HTTP methods ---
  async get(path) {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      headers: { "Authorization": `Bearer ${this.token}` }
    });
    if (!resp.ok) {
      throw new DaemonError(resp.status, await resp.text());
    }
    return resp.json();
  }
  async post(path, body) {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${this.token}`,
        "Content-Type": "application/json"
      },
      body: body ? JSON.stringify(body) : void 0
    });
    if (!resp.ok) {
      throw new DaemonError(resp.status, await resp.text());
    }
    return resp.json();
  }
  async delete(path) {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${this.token}` }
    });
    if (!resp.ok) {
      throw new DaemonError(resp.status, await resp.text());
    }
  }
  // --- WebSocket ---
  connectWebSocket(onDisconnect) {
    if (this.ws)
      return;
    const wsUrl = this.baseUrl.replace(/^https?/, (m) => m === "https" ? "wss" : "ws") + `/api/ws?token=${encodeURIComponent(this.token)}`;
    this.ws = new WebSocket(wsUrl);
    this.ws.onopen = () => {
      const handlers = this.eventHandlers.get("_connected") || [];
      handlers.forEach((h) => h({ event: "_connected" }));
    };
    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const handlers = this.eventHandlers.get(data.event) || [];
        handlers.forEach((h) => h(data));
        const wildcardHandlers = this.eventHandlers.get("*") || [];
        wildcardHandlers.forEach((h) => h(data));
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        new import_obsidian.Notice(`Recap: malformed WebSocket message \u2014 ${msg}`);
        console.error("Recap:", e);
      }
    };
    this.ws.onclose = () => {
      this.ws = null;
      onDisconnect?.();
      this.reconnectTimer = setTimeout(() => {
        this.connectWebSocket(onDisconnect);
      }, 1e4);
    };
    this.ws.onerror = (error) => {
      console.error("WebSocket error:", error);
    };
  }
  disconnectWebSocket() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
  on(event, handler) {
    const handlers = this.eventHandlers.get(event) || [];
    handlers.push(handler);
    this.eventHandlers.set(event, handlers);
    return () => {
      const current = this.eventHandlers.get(event);
      if (!current)
        return;
      const idx = current.indexOf(handler);
      if (idx !== -1) {
        current.splice(idx, 1);
      }
    };
  }
  off(event, handler) {
    const handlers = this.eventHandlers.get(event) || [];
    this.eventHandlers.set(event, handlers.filter((h) => h !== handler));
  }
  get isConnected() {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }
  // --- Convenience methods ---
  async getStatus() {
    return this.get("/api/status");
  }
  async startRecording(org, backend) {
    const body = { org };
    if (backend)
      body.backend = backend;
    return this.post("/api/record/start", body);
  }
  async stopRecording() {
    return this.post("/api/record/stop");
  }
  async reprocess(recordingPath, fromStage, org) {
    await this.post("/api/meetings/reprocess", {
      recording_path: recordingPath,
      from_stage: fromStage,
      org
    });
  }
  async submitSpeakerCorrections(recordingPath, mapping, org) {
    await this.post("/api/meetings/speakers", {
      recording_path: recordingPath,
      mapping,
      org
    });
  }
  async getOAuthStatus(provider) {
    return this.get(`/api/oauth/${provider}/status`);
  }
  async startOAuth(provider) {
    return this.post(`/api/oauth/${provider}/start`);
  }
  async disconnectOAuth(provider) {
    await this.delete(`/api/oauth/${provider}`);
  }
  async arm(eventId, startTime, org) {
    await this.post("/api/arm", { event_id: eventId, start_time: startTime, org });
  }
  async disarm() {
    await this.post("/api/disarm");
  }
  async tailEvents(since, limit) {
    const params = new URLSearchParams();
    if (since !== void 0)
      params.set("since", since);
    if (limit !== void 0)
      params.set("limit", String(limit));
    const query = params.toString();
    const path = query ? `/api/events?${query}` : "/api/events";
    const resp = await this.get(path);
    return resp.entries;
  }
  onJournalEntry(handler) {
    const dispatch = (event) => {
      const entry = event.entry;
      if (entry)
        handler(entry);
    };
    return this.on("journal_entry", dispatch);
  }
  async getConfig() {
    return this.get("/api/config");
  }
  /** URL for streaming. Not used for auth'd fetches (tokens must not
   * land in query strings that could leak through referrers or logs);
   * see ``fetchSpeakerClip`` for the Bearer-authed variant. */
  getSpeakerClipUrl(stem, speaker, duration = 5) {
    const params = new URLSearchParams({
      speaker,
      duration: String(duration)
    });
    return `${this.baseUrl}/api/recordings/${encodeURIComponent(stem)}/clip?${params.toString()}`;
  }
  async fetchSpeakerClip(stem, speaker, duration = 5) {
    const resp = await fetch(
      this.getSpeakerClipUrl(stem, speaker, duration),
      {
        headers: { "Authorization": `Bearer ${this.token}` }
      }
    );
    if (!resp.ok) {
      throw new DaemonError(resp.status, await resp.text());
    }
    return resp.blob();
  }
  async patchConfig(patch) {
    const resp = await fetch(`${this.baseUrl}/api/config`, {
      method: "PATCH",
      headers: {
        "Authorization": `Bearer ${this.token}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(patch)
    });
    if (!resp.ok) {
      throw new DaemonError(resp.status, await resp.text());
    }
    return resp.json();
  }
};

// src/components/StatusBarItem.ts
var RecapStatusBar = class {
  el;
  constructor(statusBarEl) {
    this.el = statusBarEl;
    this.el.addClass("recap-status-bar");
  }
  updateState(state, org) {
    this.el.empty();
    switch (state) {
      case "recording":
        this.el.setText(`\u23FA Recording (${org || ""})`);
        this.el.addClass("recap-recording");
        this.el.removeClass("recap-offline", "recap-processing");
        break;
      case "processing":
        this.el.setText("\u2699 Processing...");
        this.el.addClass("recap-processing");
        this.el.removeClass("recap-recording", "recap-offline");
        break;
      case "armed":
        this.el.setText("\u25C9 Armed");
        this.el.removeClass("recap-recording", "recap-offline", "recap-processing");
        break;
      default:
        this.el.setText("");
        this.el.removeClass("recap-recording", "recap-offline", "recap-processing");
    }
  }
  setOffline() {
    this.el.setText("\u26A0 Daemon offline");
    this.el.addClass("recap-offline");
    this.el.removeClass("recap-recording", "recap-processing");
  }
  setConnected() {
    if (this.el.hasClass("recap-offline")) {
      this.el.setText("");
      this.el.removeClass("recap-offline");
    }
  }
};

// src/components/StartRecordingModal.ts
var import_obsidian2 = require("obsidian");
var StartRecordingModal = class extends import_obsidian2.Modal {
  orgs;
  backends;
  onSubmit;
  selectedOrg;
  selectedBackend;
  backendDropdownEl = null;
  constructor(app, orgs, backends, onSubmit) {
    super(app);
    this.orgs = orgs.length > 0 ? orgs : [{ name: "default", default_backend: "claude" }];
    this.backends = backends.length > 0 ? backends : ["claude"];
    this.onSubmit = onSubmit;
    this.selectedOrg = this.orgs[0].name;
    this.selectedBackend = this.orgs[0].default_backend;
  }
  onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl("h3", { text: "Start recording" });
    new import_obsidian2.Setting(contentEl).setName("Organization").setDesc("Which org this meeting belongs to.").addDropdown((d) => {
      for (const o of this.orgs)
        d.addOption(o.name, o.name);
      d.setValue(this.selectedOrg);
      d.onChange((v) => {
        this.selectedOrg = v;
        const match = this.orgs.find((o) => o.name === v);
        if (match) {
          this.selectedBackend = match.default_backend;
          if (this.backendDropdownEl) {
            this.backendDropdownEl.value = this.selectedBackend;
          }
        }
      });
    });
    new import_obsidian2.Setting(contentEl).setName("Analysis backend").setDesc("Which LLM processes the transcript after recording.").addDropdown((d) => {
      for (const b of this.backends)
        d.addOption(b, this._label(b));
      d.setValue(this.selectedBackend);
      d.onChange((v) => {
        this.selectedBackend = v;
      });
      this.backendDropdownEl = d.selectEl;
    });
    new import_obsidian2.Setting(contentEl).addButton(
      (b) => b.setButtonText("Start recording").setCta().onClick(() => {
        this.close();
        this.onSubmit({
          org: this.selectedOrg,
          backend: this.selectedBackend
        });
      })
    ).addButton(
      (b) => b.setButtonText("Cancel").onClick(() => this.close())
    );
  }
  onClose() {
    this.contentEl.empty();
  }
  _label(backend) {
    switch (backend) {
      case "claude":
        return "Claude";
      case "ollama":
        return "Ollama";
      default:
        return backend;
    }
  }
};

// src/settings.ts
var import_obsidian3 = require("obsidian");
var RecapSettingTab = class extends import_obsidian3.PluginSettingTab {
  plugin;
  // Working copies edited in place by each section's UI; flushed to
  // the daemon by their Save button. Seeded from a single
  // getConfig() call per display().
  orgsEdits = [];
  detectionEdits = {};
  calendarEdits = {};
  contactsEdits = [];
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }
  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Recap Settings" });
    containerEl.createEl("h3", { text: "Daemon Connection" });
    new import_obsidian3.Setting(containerEl).setName("Daemon URL").setDesc("The URL of the Recap daemon (default: http://127.0.0.1:9847)").addText(
      (text) => text.setPlaceholder("http://127.0.0.1:9847").setValue(this.plugin.settings.daemonUrl).onChange(async (value) => {
        this.plugin.settings.daemonUrl = value;
        await this.plugin.saveSettings();
        await this.plugin.reconnect();
      })
    );
    const statusContainer = containerEl.createDiv({ cls: "recap-settings-status" });
    this.renderDaemonStatus(statusContainer);
    containerEl.createEl("h3", { text: "Calendar Providers" });
    const oauthContainer = containerEl.createDiv();
    this.renderOAuthProviders(oauthContainer);
    containerEl.createEl("h3", { text: "Organizations" });
    const orgsContainer = containerEl.createDiv({ cls: "recap-settings-orgs" });
    containerEl.createEl("h3", { text: "Meeting detection" });
    const detectionContainer = containerEl.createDiv({
      cls: "recap-settings-detection"
    });
    containerEl.createEl("h3", { text: "Calendar sync" });
    const calendarContainer = containerEl.createDiv({
      cls: "recap-settings-calendar"
    });
    containerEl.createEl("h3", { text: "Known contacts" });
    const contactsContainer = containerEl.createDiv({
      cls: "recap-settings-contacts"
    });
    containerEl.createEl("h3", { text: "Daemon lifecycle" });
    const daemonContainer = containerEl.createDiv({
      cls: "recap-settings-daemon"
    });
    void this.loadConfigSections({
      orgs: orgsContainer,
      detection: detectionContainer,
      calendar: calendarContainer,
      contacts: contactsContainer
    });
    void this.renderDaemonLifecycle(daemonContainer);
  }
  async loadConfigSections(containers) {
    if (!this.plugin.client) {
      const hint = "Connect to the daemon to manage this section.";
      for (const el of Object.values(containers)) {
        el.empty();
        el.createEl("p", { text: hint, cls: "setting-item-description" });
      }
      return;
    }
    let cfg;
    try {
      cfg = await this.plugin.client.getConfig();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian3.Notice(`Recap: could not load config \u2014 ${msg}`);
      console.error("Recap:", e);
      for (const el of Object.values(containers)) {
        el.empty();
        el.createEl("p", {
          text: "Could not load config from daemon. See console for details.",
          cls: "setting-item-description"
        });
      }
      return;
    }
    this.orgsEdits = cfg.orgs.map((o) => ({ ...o }));
    this.detectionEdits = Object.fromEntries(
      Object.entries(cfg.detection).map(([k, v]) => [k, { ...v }])
    );
    this.calendarEdits = Object.fromEntries(
      Object.entries(cfg.calendar).map(([k, v]) => [k, { ...v }])
    );
    this.contactsEdits = cfg.known_contacts.map((c) => ({
      ...c,
      aliases: [...c.aliases]
    }));
    this.renderOrgsList(containers.orgs);
    this.renderDetectionSection(containers.detection);
    this.renderCalendarSection(containers.calendar);
    this.renderContactsSection(containers.contacts);
  }
  renderOrgsList(container) {
    container.empty();
    if (this.orgsEdits.length === 0) {
      container.createEl("p", {
        text: "No orgs configured. Add one to get started.",
        cls: "setting-item-description"
      });
    }
    this.orgsEdits.forEach((org, index) => {
      const row = new import_obsidian3.Setting(container);
      row.setName(`Org ${index + 1}`);
      row.addText(
        (text) => text.setPlaceholder("name (e.g. work)").setValue(org.name).onChange((value) => {
          org.name = value;
        })
      );
      row.addText(
        (text) => text.setPlaceholder("subfolder (e.g. _Recap/Work)").setValue(org.subfolder).onChange((value) => {
          org.subfolder = value;
        })
      );
      row.addToggle(
        (toggle) => toggle.setTooltip("Default org").setValue(org.default).onChange((value) => {
          if (value) {
            this.orgsEdits.forEach((other, i) => {
              other.default = i === index;
            });
            this.renderOrgsList(container);
          } else {
            org.default = false;
          }
        })
      );
      row.addExtraButton(
        (btn) => btn.setIcon("trash").setTooltip("Remove").onClick(() => {
          this.orgsEdits.splice(index, 1);
          this.renderOrgsList(container);
        })
      );
    });
    new import_obsidian3.Setting(container).addButton(
      (btn) => btn.setButtonText("Add org").onClick(() => {
        this.orgsEdits.push({
          name: "",
          subfolder: "",
          default: this.orgsEdits.length === 0
        });
        this.renderOrgsList(container);
      })
    ).addButton(
      (btn) => btn.setButtonText("Save orgs").setCta().onClick(async () => {
        await this.saveOrgs();
      })
    );
  }
  async saveOrgs() {
    if (!this.plugin.client) {
      new import_obsidian3.Notice("Recap: Daemon not connected");
      return;
    }
    const cleaned = this.orgsEdits.map((o) => ({
      name: o.name.trim(),
      subfolder: o.subfolder.trim(),
      default: o.default
    })).filter((o) => o.name.length > 0);
    const names = /* @__PURE__ */ new Set();
    for (const o of cleaned) {
      if (names.has(o.name)) {
        new import_obsidian3.Notice(`Recap: duplicate org name "${o.name}"`);
        return;
      }
      names.add(o.name);
    }
    const defaults = cleaned.filter((o) => o.default);
    if (cleaned.length > 0 && defaults.length === 0) {
      new import_obsidian3.Notice("Recap: at least one org must be marked default");
      return;
    }
    if (defaults.length > 1) {
      new import_obsidian3.Notice("Recap: only one org can be marked default");
      return;
    }
    try {
      const resp = await this.plugin.client.patchConfig({
        orgs: cleaned
      });
      const msg = resp.restart_required ? "Orgs saved. Restart the daemon (tray \u2192 Quit, then relaunch) to apply." : "Orgs saved.";
      new import_obsidian3.Notice(`Recap: ${msg}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian3.Notice(`Recap: save orgs failed \u2014 ${msg}`);
      console.error("Recap:", e);
    }
  }
  // ---- Detection ----
  renderDetectionSection(container) {
    container.empty();
    const platforms = Object.keys(this.detectionEdits);
    if (platforms.length === 0) {
      container.createEl("p", {
        text: "No detection rules configured.",
        cls: "setting-item-description"
      });
      return;
    }
    for (const platform of platforms) {
      const rule = this.detectionEdits[platform];
      const row = new import_obsidian3.Setting(container).setName(platform);
      row.addToggle(
        (toggle) => toggle.setTooltip("Enabled").setValue(rule.enabled ?? false).onChange((value) => {
          rule.enabled = value;
        })
      );
      row.addDropdown(
        (drop) => drop.addOption("auto-record", "auto-record").addOption("prompt", "prompt").setValue(rule.behavior ?? "prompt").onChange((value) => {
          rule.behavior = value;
        })
      );
    }
    new import_obsidian3.Setting(container).addButton(
      (btn) => btn.setButtonText("Save detection").setCta().onClick(async () => {
        await this.saveDetection();
      })
    );
  }
  async saveDetection() {
    if (!this.plugin.client) {
      new import_obsidian3.Notice("Recap: Daemon not connected");
      return;
    }
    try {
      const resp = await this.plugin.client.patchConfig({
        detection: this.detectionEdits
      });
      const msg = resp.restart_required ? "Detection saved. Restart the daemon to apply." : "Detection saved.";
      new import_obsidian3.Notice(`Recap: ${msg}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian3.Notice(`Recap: save detection failed \u2014 ${msg}`);
      console.error("Recap:", e);
    }
  }
  // ---- Calendar ----
  renderCalendarSection(container) {
    container.empty();
    const providers = Object.keys(this.calendarEdits);
    if (providers.length === 0) {
      container.createEl("p", {
        text: "No calendar providers configured.",
        cls: "setting-item-description"
      });
      return;
    }
    for (const provider of providers) {
      const cfg = this.calendarEdits[provider];
      const row = new import_obsidian3.Setting(container).setName(provider);
      row.addToggle(
        (toggle) => toggle.setTooltip("Enabled").setValue(cfg.enabled ?? false).onChange((value) => {
          cfg.enabled = value;
        })
      );
      row.addText(
        (text) => text.setPlaceholder("calendar id").setValue(cfg.calendar_id ?? "").onChange((value) => {
          cfg.calendar_id = value.trim() === "" ? null : value;
        })
      );
      row.addText(
        (text) => text.setPlaceholder("org").setValue(cfg.org ?? "").onChange((value) => {
          cfg.org = value.trim() === "" ? null : value;
        })
      );
    }
    new import_obsidian3.Setting(container).addButton(
      (btn) => btn.setButtonText("Save calendar").setCta().onClick(async () => {
        await this.saveCalendar();
      })
    );
  }
  async saveCalendar() {
    if (!this.plugin.client) {
      new import_obsidian3.Notice("Recap: Daemon not connected");
      return;
    }
    try {
      const resp = await this.plugin.client.patchConfig({
        calendar: this.calendarEdits
      });
      const msg = resp.restart_required ? "Calendar saved. Restart the daemon to apply." : "Calendar saved.";
      new import_obsidian3.Notice(`Recap: ${msg}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian3.Notice(`Recap: save calendar failed \u2014 ${msg}`);
      console.error("Recap:", e);
    }
  }
  // ---- Contacts ----
  renderContactsSection(container) {
    container.empty();
    if (this.contactsEdits.length === 0) {
      container.createEl("p", {
        text: "No known contacts yet. Add one to help the pipeline map speakers to people.",
        cls: "setting-item-description"
      });
    }
    this.contactsEdits.forEach((contact, index) => {
      const row = new import_obsidian3.Setting(container).setName(`Contact ${index + 1}`);
      row.addText(
        (text) => text.setPlaceholder("name").setValue(contact.name).onChange((value) => {
          contact.name = value;
        })
      );
      row.addText(
        (text) => text.setPlaceholder("display name (for speaker matching)").setValue(contact.display_name ?? "").onChange((value) => {
          contact.display_name = value.trim() === "" ? null : value;
        })
      );
      row.addText(
        (text) => text.setPlaceholder("aliases (comma-separated)").setValue(contact.aliases.join(", ")).onChange((value) => {
          contact.aliases = value.split(",").map((s) => s.trim()).filter((s) => s.length > 0);
        })
      );
      row.addText(
        (text) => text.setPlaceholder("email").setValue(contact.email ?? "").onChange((value) => {
          contact.email = value.trim() === "" ? null : value;
        })
      );
      row.addExtraButton(
        (btn) => btn.setIcon("trash").setTooltip("Remove").onClick(() => {
          this.contactsEdits.splice(index, 1);
          this.renderContactsSection(container);
        })
      );
    });
    new import_obsidian3.Setting(container).addButton(
      (btn) => btn.setButtonText("Add contact").onClick(() => {
        this.contactsEdits.push({
          name: "",
          aliases: [],
          email: null,
          display_name: null
        });
        this.renderContactsSection(container);
      })
    ).addButton(
      (btn) => btn.setButtonText("Save contacts").setCta().onClick(async () => {
        await this.saveContacts();
      })
    );
  }
  async saveContacts() {
    if (!this.plugin.client) {
      new import_obsidian3.Notice("Recap: Daemon not connected");
      return;
    }
    const cleaned = this.contactsEdits.map((c) => ({
      name: c.name.trim(),
      aliases: c.aliases,
      email: c.email,
      display_name: c.display_name
    })).filter((c) => c.name.length > 0);
    try {
      const resp = await this.plugin.client.patchConfig({
        known_contacts: cleaned
      });
      const msg = resp.restart_required ? "Contacts saved. Restart the daemon to apply." : "Contacts saved.";
      new import_obsidian3.Notice(`Recap: ${msg}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian3.Notice(`Recap: save contacts failed \u2014 ${msg}`);
      console.error("Recap:", e);
    }
  }
  // ---- Daemon lifecycle ----
  async renderDaemonLifecycle(container) {
    container.empty();
    if (!this.plugin.client) {
      container.createEl("p", {
        text: "Connect to the daemon to see lifecycle info.",
        cls: "setting-item-description"
      });
      return;
    }
    let stateLine = "State: unknown";
    try {
      const status = await this.plugin.client.getStatus();
      const uptime = Math.floor(status.uptime_seconds || 0);
      stateLine = `State: ${status.state}, uptime: ${uptime}s`;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      stateLine = `State: unreachable \u2014 ${msg}`;
      console.error("Recap:", e);
    }
    container.createEl("p", {
      text: stateLine,
      cls: "setting-item-description"
    });
    new import_obsidian3.Setting(container).setName("Restart daemon").setDesc(
      "Config changes require a daemon restart. Right-click the Recap tray icon \u2192 Quit, then relaunch."
    ).addButton(
      (btn) => btn.setButtonText("How to restart").onClick(() => {
        new import_obsidian3.Notice(
          "Recap: right-click the tray icon \u2192 Quit, then relaunch the daemon.",
          8e3
        );
      })
    );
  }
  async renderDaemonStatus(container) {
    container.empty();
    const statusEl = container.createDiv({ cls: "recap-daemon-status" });
    if (!this.plugin.client) {
      statusEl.createSpan({ text: "Not connected", cls: "recap-status-offline" });
      statusEl.createEl("p", {
        text: "Could not read auth token from _Recap/.recap/auth-token. Is the daemon running?",
        cls: "setting-item-description"
      });
      return;
    }
    try {
      const status = await this.plugin.client.getStatus();
      statusEl.createSpan({ text: "Connected", cls: "recap-status-connected" });
      statusEl.createEl("p", {
        text: `State: ${status.state} | Last calendar sync: ${status.last_calendar_sync || "never"}`,
        cls: "setting-item-description"
      });
    } catch (e) {
      statusEl.createSpan({ text: "Daemon offline", cls: "recap-status-offline" });
      console.error("Recap: daemon status fetch failed:", e);
    }
  }
  async renderOAuthProviders(container) {
    container.empty();
    if (!this.plugin.client) {
      container.createEl("p", { text: "Connect to daemon first to manage calendar providers." });
      return;
    }
    for (const provider of ["zoho", "google"]) {
      const providerDiv = container.createDiv({ cls: "recap-oauth-provider" });
      try {
        const status = await this.plugin.client.getOAuthStatus(provider);
        new import_obsidian3.Setting(providerDiv).setName(provider.charAt(0).toUpperCase() + provider.slice(1) + " Calendar").setDesc(status.connected ? "Connected" : "Not connected").addButton((button) => {
          if (status.connected) {
            button.setButtonText("Disconnect").setWarning().onClick(async () => {
              await this.plugin.client.disconnectOAuth(provider);
              new import_obsidian3.Notice(`${provider} disconnected`);
              this.renderOAuthProviders(container);
            });
          } else {
            button.setButtonText("Connect").setCta().onClick(async () => {
              try {
                const result = await this.plugin.client.startOAuth(provider);
                window.open(result.authorize_url);
                new import_obsidian3.Notice(`Complete ${provider} authorization in your browser`);
              } catch (e) {
                new import_obsidian3.Notice(`Failed to start OAuth: ${e}`);
              }
            });
          }
        });
      } catch (e) {
        new import_obsidian3.Setting(providerDiv).setName(provider.charAt(0).toUpperCase() + provider.slice(1) + " Calendar").setDesc("Could not check status");
        console.error("Recap:", e);
      }
    }
  }
};

// src/views/MeetingListView.ts
var import_obsidian4 = require("obsidian");

// src/components/FilterBar.ts
var FilterBar = class {
  container;
  state = { org: "all", status: "all", search: "" };
  onChange;
  constructor(parent, orgs, onChange) {
    this.onChange = onChange;
    this.container = parent.createDiv({ cls: "recap-filter-bar" });
    this.render(orgs);
  }
  render(orgs) {
    const orgSelect = this.container.createEl("select", { cls: "recap-filter-select" });
    orgSelect.createEl("option", { value: "all", text: "All orgs" });
    for (const org of orgs) {
      orgSelect.createEl("option", { value: org, text: org });
    }
    orgSelect.addEventListener("change", () => {
      this.state.org = orgSelect.value;
      this.onChange(this.state);
    });
    const statusSelect = this.container.createEl("select", { cls: "recap-filter-select" });
    for (const [value, label] of [["all", "All status"], ["complete", "Complete"], ["failed", "Failed"], ["pending", "Pending"], ["processing", "Processing"]]) {
      statusSelect.createEl("option", { value, text: label });
    }
    statusSelect.addEventListener("change", () => {
      this.state.status = statusSelect.value;
      this.onChange(this.state);
    });
    const searchInput = this.container.createEl("input", {
      type: "text",
      placeholder: "Search meetings...",
      cls: "recap-filter-search"
    });
    searchInput.addEventListener("input", () => {
      this.state.search = searchInput.value;
      this.onChange(this.state);
    });
  }
};

// src/components/PipelineStatus.ts
function renderPipelineStatus(container, status) {
  const dot = container.createSpan({ cls: "recap-pipeline-dot" });
  if (status === "complete") {
    dot.addClass("recap-status-complete");
    dot.setAttribute("aria-label", "Complete");
  } else if (status === "pending") {
    dot.addClass("recap-status-pending");
    dot.setAttribute("aria-label", "Pending");
  } else if (status?.startsWith("failed")) {
    dot.addClass("recap-status-failed");
    dot.setAttribute("aria-label", `Failed: ${status}`);
  } else {
    dot.addClass("recap-status-processing");
    dot.setAttribute("aria-label", status || "Processing");
  }
}

// src/utils/format.ts
function formatDate(dateStr) {
  if (!dateStr)
    return "";
  const isoDateMatch = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  let d;
  if (isoDateMatch) {
    const [, y, m, day] = isoDateMatch;
    d = new Date(Number(y), Number(m) - 1, Number(day));
  } else {
    d = new Date(dateStr);
  }
  if (isNaN(d.getTime()))
    return dateStr;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// src/components/MeetingRow.ts
function renderMeetingRow(container, meeting, onClick) {
  const row = container.createDiv({ cls: "recap-meeting-row" });
  row.addEventListener("click", () => onClick(meeting.path));
  const titleRow = row.createDiv({ cls: "recap-meeting-title-row" });
  titleRow.createSpan({ text: meeting.title, cls: "recap-meeting-title" });
  const metaRow = row.createDiv({ cls: "recap-meeting-meta-row" });
  renderPipelineStatus(metaRow, meeting.pipelineStatus);
  metaRow.createSpan({ text: formatDate(meeting.date), cls: "recap-meeting-date" });
  metaRow.createSpan({ text: meeting.org, cls: "recap-org-badge" });
  if (meeting.duration) {
    metaRow.createSpan({ text: meeting.duration, cls: "recap-meeting-duration" });
  }
  if (meeting.participants.length > 0) {
    metaRow.createSpan({
      text: `${meeting.participants.length} people`,
      cls: "recap-meeting-participants"
    });
  }
  return row;
}

// src/views/MeetingListView.ts
var RELOAD_DEBOUNCE_MS = 300;
var VIEW_MEETING_LIST = "recap-meeting-list";
var MeetingListView = class extends import_obsidian4.ItemView {
  meetings = [];
  filteredMeetings = [];
  listContainer = null;
  deps;
  // Status row elements (created in onOpen, updated via updateDaemonState).
  statusDotEl = null;
  statusLabelEl = null;
  actionBtnEl = null;
  currentState = null;
  currentOrg = void 0;
  // Track current filter so reloads after vault events preserve what the
  // user has selected (org dropdown, status dropdown, search box).
  filterState = null;
  // Pending reload timer for debouncing bursts of vault create/modify events.
  reloadTimer = null;
  // Meeting-scope prefixes configured by the daemon (org subfolders).
  // Cached from loadMeetings() so vault event handlers can cheaply decide
  // whether a changed file is within the scope we care about.
  meetingPathPrefixes = [];
  constructor(leaf, deps) {
    super(leaf);
    this.deps = deps;
  }
  getViewType() {
    return VIEW_MEETING_LIST;
  }
  getDisplayText() {
    return "Recap Meetings";
  }
  getIcon() {
    return "mic";
  }
  async onOpen() {
    const container = this.containerEl.children[1];
    container.empty();
    container.addClass("recap-meeting-list-container");
    container.createEl("h4", { text: "Meetings" });
    this.renderStatusRow(container);
    await this.refreshDaemonStateFromClient();
    await this.loadMeetings();
    const orgs = [...new Set(this.meetings.map((m) => m.org).filter(Boolean))];
    new FilterBar(container, orgs, (state) => {
      this.applyFilters(state);
    });
    this.listContainer = container.createDiv({ cls: "recap-meeting-list" });
    this.renderMeetings();
    this.registerEvent(
      this.app.vault.on("create", (f) => this.maybeScheduleReload(f.path))
    );
    this.registerEvent(
      this.app.vault.on("delete", (f) => this.maybeScheduleReload(f.path))
    );
    this.registerEvent(
      this.app.vault.on("rename", (f, oldPath) => {
        this.maybeScheduleReload(f.path);
        this.maybeScheduleReload(oldPath);
      })
    );
    this.registerEvent(
      this.app.metadataCache.on(
        "changed",
        (f) => this.maybeScheduleReload(f.path)
      )
    );
  }
  maybeScheduleReload(path) {
    if (!path.endsWith(".md") || !path.includes("/Meetings/"))
      return;
    if (this.meetingPathPrefixes.length > 0) {
      const inScope = this.meetingPathPrefixes.some(
        (sub) => path.startsWith(sub + "/") || path === sub
      );
      if (!inScope)
        return;
    }
    this.scheduleReload();
  }
  scheduleReload() {
    if (this.reloadTimer !== null)
      window.clearTimeout(this.reloadTimer);
    this.reloadTimer = window.setTimeout(() => {
      this.reloadTimer = null;
      void this.reloadMeetings();
    }, RELOAD_DEBOUNCE_MS);
  }
  /** Reload the meeting list from the vault, preserving the active filter. */
  async reloadMeetings() {
    await this.loadMeetings();
    if (this.filterState !== null) {
      this.applyFilters(this.filterState);
    } else {
      this.renderMeetings();
    }
  }
  /**
   * Render the status row at the top of the panel. Mirrors the pattern
   * used by other Obsidian plugins: a coloured dot, a short state label,
   * and a Start/Stop button whose affordance matches the current state.
   */
  renderStatusRow(container) {
    const row = container.createDiv({ cls: "recap-status-row" });
    this.statusDotEl = row.createEl("span", { cls: "recap-status-dot recap-status-offline" });
    this.statusLabelEl = row.createEl("span", { cls: "recap-status-label", text: "Connecting\u2026" });
    this.actionBtnEl = row.createEl("button", {
      cls: "recap-action-btn",
      text: "Start recording"
    });
    this.actionBtnEl.disabled = true;
    this.actionBtnEl.addEventListener("click", async () => {
      if (!this.actionBtnEl || this.actionBtnEl.disabled)
        return;
      const wasRecording = this.currentState === "recording";
      this.actionBtnEl.disabled = true;
      try {
        if (wasRecording) {
          await this.deps.onStopRecording();
        } else {
          await this.deps.onStartRecording();
        }
      } finally {
        if (this.actionBtnEl)
          this.actionBtnEl.disabled = false;
      }
    });
  }
  /** Pull daemon status once at open time so the header isn't stuck on "Connecting…". */
  async refreshDaemonStateFromClient() {
    const client = this.deps.getClient();
    if (!client) {
      this.updateDaemonState(null);
      return;
    }
    try {
      const status = await client.getStatus();
      this.updateDaemonState(status.state, status.recording?.org);
    } catch {
      this.updateDaemonState(null);
    }
  }
  /**
   * Public entry point: update the status row in response to a state_change
   * WebSocket event, an offline notification, or a successful reconnect.
   * Passing ``null`` renders the offline look.
   */
  updateDaemonState(state, org) {
    const wasProcessing = this.currentState === "processing";
    const stillProcessing = state === "processing";
    this.currentState = state;
    this.currentOrg = org;
    if (wasProcessing && !stillProcessing) {
      this.scheduleReload();
    }
    if (!this.statusDotEl || !this.statusLabelEl || !this.actionBtnEl)
      return;
    this.statusDotEl.removeClass(
      "recap-status-ok",
      "recap-status-recording",
      "recap-status-processing",
      "recap-status-offline"
    );
    if (state === null) {
      this.statusDotEl.addClass("recap-status-offline");
      this.statusLabelEl.setText("Daemon offline");
      this.actionBtnEl.setText("Start recording");
      this.actionBtnEl.disabled = true;
      return;
    }
    switch (state) {
      case "recording":
        this.statusDotEl.addClass("recap-status-recording");
        this.statusLabelEl.setText(org ? `Recording (${org})` : "Recording");
        this.actionBtnEl.setText("Stop recording");
        this.actionBtnEl.disabled = false;
        break;
      case "processing":
        this.statusDotEl.addClass("recap-status-processing");
        this.statusLabelEl.setText("Processing\u2026");
        this.actionBtnEl.setText("Start recording");
        this.actionBtnEl.disabled = true;
        break;
      case "armed":
        this.statusDotEl.addClass("recap-status-ok");
        this.statusLabelEl.setText(org ? `Armed (${org})` : "Armed");
        this.actionBtnEl.setText("Start recording");
        this.actionBtnEl.disabled = false;
        break;
      case "detected":
        this.statusDotEl.addClass("recap-status-ok");
        this.statusLabelEl.setText("Meeting detected");
        this.actionBtnEl.setText("Start recording");
        this.actionBtnEl.disabled = false;
        break;
      default:
        this.statusDotEl.addClass("recap-status-ok");
        this.statusLabelEl.setText("Idle");
        this.actionBtnEl.setText("Start recording");
        this.actionBtnEl.disabled = false;
    }
  }
  async loadMeetings() {
    this.meetings = [];
    let subfolders = [];
    const client = this.deps.getClient();
    if (client) {
      try {
        const cfg = await client.getConfig();
        subfolders = cfg.orgs.map((o) => o.subfolder).filter((s) => !!s && s.length > 0);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        new import_obsidian4.Notice(
          `Recap: could not load org config \u2014 scanning whole vault. ${msg}`
        );
        console.error("Recap:", e);
      }
    }
    this.meetingPathPrefixes = subfolders;
    const allFiles = this.app.vault.getMarkdownFiles();
    const scopedFiles = subfolders.length === 0 ? allFiles : allFiles.filter(
      (f) => subfolders.some(
        (sub) => f.path.startsWith(sub + "/") || f.path === sub
      )
    );
    for (const file of scopedFiles) {
      if (!file.path.includes("/Meetings/"))
        continue;
      try {
        const cache = this.app.metadataCache.getFileCache(file);
        const frontmatter = cache?.frontmatter;
        if (!frontmatter)
          continue;
        this.meetings.push({
          path: file.path,
          title: frontmatter.title || file.basename,
          date: frontmatter.date || "",
          org: frontmatter.org || "",
          duration: frontmatter.duration || "",
          pipelineStatus: frontmatter["pipeline-status"] || "pending",
          participants: this.parseParticipants(frontmatter.participants || []),
          platform: frontmatter.platform || ""
        });
      } catch (e) {
        console.error(
          "Recap: could not read meeting frontmatter for",
          file.path,
          ":",
          e
        );
      }
    }
    this.meetings.sort((a, b) => b.date.localeCompare(a.date));
    this.filteredMeetings = [...this.meetings];
  }
  parseParticipants(raw) {
    if (!Array.isArray(raw))
      return [];
    return raw.map((p) => p.replace(/\[\[|\]\]/g, ""));
  }
  applyFilters(state) {
    this.filterState = state;
    this.filteredMeetings = this.meetings.filter((m) => {
      if (state.org !== "all" && m.org !== state.org)
        return false;
      if (state.status !== "all") {
        if (state.status === "failed" && !m.pipelineStatus.startsWith("failed"))
          return false;
        if (state.status !== "failed" && m.pipelineStatus !== state.status)
          return false;
      }
      if (state.search) {
        const q = state.search.toLowerCase();
        const searchable = `${m.title} ${m.participants.join(" ")}`.toLowerCase();
        if (!searchable.includes(q))
          return false;
      }
      return true;
    });
    this.renderMeetings();
  }
  renderMeetings() {
    if (!this.listContainer)
      return;
    this.listContainer.empty();
    if (this.filteredMeetings.length === 0) {
      this.listContainer.createDiv({
        text: "No meetings found",
        cls: "recap-empty-state"
      });
      return;
    }
    for (const meeting of this.filteredMeetings) {
      renderMeetingRow(this.listContainer, meeting, (path) => {
        const file = this.app.vault.getAbstractFileByPath(path);
        if (file instanceof import_obsidian4.TFile) {
          this.app.workspace.getLeaf(false).openFile(file);
        }
      });
    }
  }
  async onClose() {
    this.listContainer = null;
  }
};

// src/views/LiveTranscriptView.ts
var import_obsidian5 = require("obsidian");
var VIEW_LIVE_TRANSCRIPT = "recap-live-transcript";
var LiveTranscriptView = class extends import_obsidian5.ItemView {
  transcriptEl = null;
  statusEl = null;
  getStatus;
  constructor(leaf, getStatus) {
    super(leaf);
    this.getStatus = getStatus ?? null;
  }
  getViewType() {
    return VIEW_LIVE_TRANSCRIPT;
  }
  getDisplayText() {
    return "Live Transcript";
  }
  getIcon() {
    return "scroll-text";
  }
  async onOpen() {
    const container = this.containerEl.children[1];
    container.empty();
    container.addClass("recap-live-transcript-container");
    this.statusEl = container.createDiv({ cls: "recap-live-status" });
    this.transcriptEl = container.createDiv({ cls: "recap-live-transcript" });
    if (this.getStatus) {
      const currentState = await this.getStatus();
      this.updateStatus(currentState ?? "idle");
    } else {
      this.updateStatus("idle");
    }
  }
  updateStatus(state) {
    if (!this.statusEl)
      return;
    this.statusEl.empty();
    switch (state) {
      case "recording":
        this.statusEl.setText("\u23FA Recording \u2014 transcript will appear in the meeting note after the pipeline completes.");
        this.statusEl.addClass("recap-recording");
        break;
      default:
        this.statusEl.setText("Live transcript is not available in this version. Recorded meetings will show the full transcript in the note after the pipeline completes.");
        this.statusEl.removeClass("recap-recording");
    }
  }
  appendUtterance(speaker, text) {
    if (!this.transcriptEl)
      return;
    const line = this.transcriptEl.createDiv({ cls: "recap-utterance" });
    line.createSpan({ text: `${speaker}: `, cls: "recap-utterance-speaker" });
    line.createSpan({ text });
    this.transcriptEl.scrollTop = this.transcriptEl.scrollHeight;
  }
  clear() {
    if (this.transcriptEl) {
      this.transcriptEl.empty();
    }
  }
  async onClose() {
    this.transcriptEl = null;
    this.statusEl = null;
  }
};

// src/views/SpeakerCorrectionModal.ts
var import_obsidian6 = require("obsidian");
function stemFromRecordingPath(recordingPath) {
  const basename = recordingPath.split(/[/\\]/).pop() || recordingPath;
  return basename.replace(/\.(flac|m4a|aac)$/i, "");
}
var SpeakerCorrectionModal = class extends import_obsidian6.Modal {
  speakers;
  peopleNames;
  knownContacts;
  recordingPath;
  org;
  client;
  mapping = {};
  objectUrls = [];
  constructor(app, speakers, peopleNames, knownContacts, recordingPath, org, client) {
    super(app);
    this.speakers = speakers;
    this.peopleNames = peopleNames;
    this.knownContacts = knownContacts;
    this.recordingPath = recordingPath;
    this.org = org;
    this.client = client;
  }
  onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("recap-speaker-modal");
    contentEl.createEl("h2", { text: "Identify Speakers" });
    contentEl.createEl("p", {
      text: "The pipeline couldn't match speakers to names. Assign a name to each speaker label:",
      cls: "setting-item-description"
    });
    const stem = stemFromRecordingPath(this.recordingPath);
    const datalist = contentEl.createEl("datalist");
    datalist.id = "recap-known-contacts";
    this.populateContactsDatalist(datalist);
    for (const speaker of this.speakers) {
      const row = contentEl.createDiv({ cls: "recap-speaker-row" });
      row.createSpan({
        text: speaker.label,
        cls: "recap-speaker-label"
      });
      const audioEl = row.createEl("audio");
      audioEl.controls = true;
      audioEl.preload = "none";
      audioEl.addClass("recap-speaker-audio");
      void this.loadClipInto(audioEl, stem, speaker.label, row);
      const input = row.createEl("input", {
        type: "text",
        placeholder: "Enter name...",
        cls: "recap-speaker-input"
      });
      input.setAttribute("list", "recap-known-contacts");
      input.addEventListener("input", () => {
        this.mapping[speaker.label] = input.value;
      });
    }
    const btnRow = contentEl.createDiv({ cls: "recap-modal-buttons" });
    const cancelBtn = btnRow.createEl("button", { text: "Cancel" });
    cancelBtn.addEventListener("click", () => this.close());
    const applyBtn = btnRow.createEl("button", {
      text: "Apply & Redo",
      cls: "mod-cta"
    });
    applyBtn.addEventListener("click", async () => {
      const validMapping = {};
      for (const [label, name] of Object.entries(this.mapping)) {
        if (name.trim()) {
          validMapping[label] = name.trim();
        }
      }
      if (Object.keys(validMapping).length === 0) {
        new import_obsidian6.Notice("No speakers assigned");
        return;
      }
      try {
        await this.client.submitSpeakerCorrections(
          this.recordingPath,
          validMapping,
          this.org
        );
        new import_obsidian6.Notice(
          "Speaker corrections submitted \u2014 reprocessing..."
        );
        this.close();
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        new import_obsidian6.Notice(`Recap: submit corrections failed \u2014 ${msg}`);
        console.error("Recap:", e);
      }
    });
  }
  async populateContactsDatalist(datalist) {
    const fallback = [
      .../* @__PURE__ */ new Set([...this.peopleNames, ...this.knownContacts])
    ].sort();
    for (const name of fallback) {
      datalist.createEl("option", { value: name });
    }
    try {
      const cfg = await this.client.getConfig();
      datalist.empty();
      const combined = /* @__PURE__ */ new Set([
        ...this.peopleNames,
        ...this.knownContacts
      ]);
      for (const contact of cfg.known_contacts) {
        if (contact.name)
          combined.add(contact.name);
        if (contact.display_name)
          combined.add(contact.display_name);
      }
      for (const name of [...combined].sort()) {
        datalist.createEl("option", { value: name });
      }
    } catch (e) {
      console.error(
        "Recap: could not load known contacts for autocomplete:",
        e
      );
    }
  }
  async loadClipInto(audioEl, stem, speaker, row) {
    try {
      const blob = await this.client.fetchSpeakerClip(
        stem,
        speaker,
        5
      );
      const url = URL.createObjectURL(blob);
      this.objectUrls.push(url);
      audioEl.src = url;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      audioEl.remove();
      row.createSpan({
        text: `(clip unavailable: ${msg})`,
        cls: "recap-speaker-clip-error",
        attr: { style: "opacity: 0.6; font-style: italic;" }
      });
      console.error(
        "Recap: fetch clip failed for",
        speaker,
        ":",
        e
      );
    }
  }
  onClose() {
    for (const url of this.objectUrls) {
      try {
        URL.revokeObjectURL(url);
      } catch (e) {
        console.error("Recap: URL.revokeObjectURL failed:", e);
      }
    }
    this.objectUrls = [];
    this.contentEl.empty();
  }
};

// src/renameProcessor.ts
var import_obsidian7 = require("obsidian");
var RenameProcessor = class {
  app;
  queuePath;
  constructor(app, queuePath) {
    this.app = app;
    this.queuePath = queuePath;
  }
  async processQueue() {
    const queueExists = await this.app.vault.adapter.exists(this.queuePath);
    if (!queueExists)
      return;
    let entries;
    try {
      const content = await this.app.vault.adapter.read(this.queuePath);
      entries = JSON.parse(content);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian7.Notice(`Recap: rename queue read failed \u2014 ${msg}`);
      console.error("Recap:", e);
      return;
    }
    if (!Array.isArray(entries) || entries.length === 0)
      return;
    const remaining = [];
    for (const entry of entries) {
      try {
        const file = this.app.vault.getAbstractFileByPath(entry.old_path);
        if (file instanceof import_obsidian7.TFile) {
          await this.app.fileManager.renameFile(file, entry.new_path);
        } else {
          console.warn(`Recap rename: file not found: ${entry.old_path}`);
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        new import_obsidian7.Notice(
          `Recap: rename ${entry.old_path} \u2192 ${entry.new_path} failed \u2014 ${msg}`
        );
        console.error("Recap:", e);
        remaining.push(entry);
      }
    }
    if (remaining.length > 0) {
      try {
        await this.app.vault.adapter.write(
          this.queuePath,
          JSON.stringify(remaining, null, 2)
        );
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        new import_obsidian7.Notice(`Recap: could not persist rename queue retries \u2014 ${msg}`);
        console.error("Recap:", e);
      }
    } else {
      try {
        await this.app.vault.adapter.remove(this.queuePath);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        new import_obsidian7.Notice(`Recap: could not remove empty rename queue \u2014 ${msg}`);
        console.error("Recap:", e);
      }
    }
  }
};

// src/notificationHistory.ts
var import_obsidian8 = require("obsidian");
function entryToNotification(entry) {
  const payload = entry.payload;
  const title = payload?.title ?? entry.event.replace(/_/g, " ");
  return { timestamp: entry.ts, type: entry.level, title, message: entry.message };
}
var NotificationHistory = class {
  client = null;
  cache = [];
  unsubscribe = null;
  maxSize = 100;
  listeners = [];
  setClient(client) {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
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
  async load() {
    const client = this.client;
    if (!client)
      return;
    try {
      const entries = await client.tailEvents(void 0, this.maxSize);
      if (this.client !== client)
        return;
      this.cache = entries.map(entryToNotification);
      this.notifyListeners();
    } catch (e) {
      if (this.client !== client)
        return;
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian8.Notice(`Recap: notification history backfill failed \u2014 ${msg}`);
      console.error("Recap:", e);
    }
  }
  getAll() {
    return [...this.cache];
  }
  subscribe(callback) {
    this.listeners.push(callback);
    return () => {
      const idx = this.listeners.indexOf(callback);
      if (idx >= 0)
        this.listeners.splice(idx, 1);
    };
  }
  detach() {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
    this.client = null;
    this.cache = [];
    this.notifyListeners();
  }
  notifyListeners() {
    for (const cb of this.listeners) {
      try {
        cb();
      } catch (e) {
        console.error("Recap: notification history listener threw:", e);
      }
    }
  }
};
var NotificationHistoryModal = class extends import_obsidian8.Modal {
  constructor(app, history) {
    super(app);
    this.history = history;
  }
  unsubscribe = null;
  onOpen() {
    this.render();
    this.unsubscribe = this.history.subscribe(() => this.render());
  }
  onClose() {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
    this.contentEl.empty();
  }
  render() {
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
};

// src/main.ts
var DEFAULT_SETTINGS = {
  daemonUrl: "http://127.0.0.1:9847"
};
var RecapPlugin = class extends import_obsidian9.Plugin {
  settings = DEFAULT_SETTINGS;
  client = null;
  statusBar = null;
  renameProcessor = null;
  notificationHistory = new NotificationHistory();
  lastKnownState = "idle";
  async onload() {
    await this.loadSettings();
    this.registerView(
      VIEW_MEETING_LIST,
      (leaf) => new MeetingListView(leaf, {
        getClient: () => this.client,
        onStartRecording: () => this.startRecordingInteractive(),
        onStopRecording: () => this.stopRecordingInteractive()
      })
    );
    this.registerView(
      VIEW_LIVE_TRANSCRIPT,
      (leaf) => new LiveTranscriptView(leaf, async () => {
        if (!this.client)
          return null;
        try {
          const status = await this.client.getStatus();
          return status.state;
        } catch (e) {
          console.error("Recap: live transcript status poll failed:", e);
          return null;
        }
      })
    );
    const token = await this.readAuthToken();
    if (!token) {
      new import_obsidian9.Notice("Recap: Could not read daemon auth token. Check _Recap/.recap/auth-token");
    }
    if (token) {
      this.client = new DaemonClient(this.settings.daemonUrl, token);
      this.notificationHistory.setClient(this.client);
    }
    const statusBarEl = this.addStatusBarItem();
    this.statusBar = new RecapStatusBar(statusBarEl);
    this.renameProcessor = new RenameProcessor(this.app, "_Recap/.recap/rename-queue.json");
    await this.renameProcessor.processQueue();
    if (this.client) {
      this.connectWebSocket();
      try {
        const status = await this.client.getStatus();
        this.lastKnownState = status.state;
        this.statusBar.updateState(status.state, status.recording?.org);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        new import_obsidian9.Notice(`Recap: initial daemon status fetch failed \u2014 ${msg}`);
        console.error("Recap:", e);
        this.statusBar.setOffline();
      }
    } else {
      this.statusBar.setOffline();
    }
    this.addCommand({
      id: "start-recording",
      name: "Start recording",
      callback: () => this.startRecordingInteractive()
    });
    this.addCommand({
      id: "stop-recording",
      name: "Stop recording",
      callback: () => this.stopRecordingInteractive()
    });
    this.addCommand({
      id: "open-dashboard",
      name: "Open meeting dashboard",
      callback: () => this.activateView(VIEW_MEETING_LIST)
    });
    this.addCommand({
      id: "open-live-transcript",
      name: "Open live transcript",
      callback: () => this.activateView(VIEW_LIVE_TRANSCRIPT)
    });
    this.addCommand({
      id: "view-notifications",
      name: "View notification history",
      callback: () => {
        new NotificationHistoryModal(this.app, this.notificationHistory).open();
      }
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
      }
    });
    this.registerEvent(
      this.app.workspace.on("file-open", (file) => {
        if (!file || !this.client)
          return;
        if (!file.path.startsWith("_Recap/") || !file.path.includes("/Meetings/"))
          return;
        this.app.vault.cachedRead(file).then((content) => {
          if (content.includes("SPEAKER_")) {
            new import_obsidian9.Notice(
              "This meeting has unidentified speakers. Use 'Recap: Fix speakers' to correct them.",
              1e4
            );
          }
        });
      })
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
      }
    });
    this.addSettingTab(new RecapSettingTab(this.app, this));
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
  async startRecordingInteractive() {
    if (!this.client) {
      new import_obsidian9.Notice("Recap: Daemon not connected");
      return;
    }
    let orgs = [];
    let backends = ["claude", "ollama"];
    try {
      const resp = await this.client.get("/api/config/orgs");
      orgs = resp.orgs;
      if (resp.backends && resp.backends.length > 0) {
        backends = resp.backends;
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian9.Notice(`Recap: org list fetch failed \u2014 using default. ${msg}`);
      console.error("Recap:", e);
      orgs = [{ name: "default", default_backend: "claude" }];
    }
    new StartRecordingModal(this.app, orgs, backends, async ({ org, backend }) => {
      try {
        await this.client.startRecording(org, backend);
        new import_obsidian9.Notice(`Recording started (${org}, ${backend})`);
      } catch (e) {
        new import_obsidian9.Notice(`Failed to start recording: ${e}`);
      }
    }).open();
  }
  /** Shared stop path used by the command palette and the panel button. */
  async stopRecordingInteractive() {
    if (!this.client) {
      new import_obsidian9.Notice("Recap: Daemon not connected");
      return;
    }
    try {
      await this.client.stopRecording();
      new import_obsidian9.Notice("Recording stopped");
    } catch (e) {
      new import_obsidian9.Notice(`Failed to stop recording: ${e}`);
    }
  }
  /** Push a daemon state update to every open Meetings panel. */
  broadcastDaemonState(state, org) {
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
  async openSpeakerCorrection(file) {
    if (!this.client) {
      new import_obsidian9.Notice("Daemon not connected");
      return;
    }
    const content = await this.app.vault.cachedRead(file);
    const speakerLabels = [...new Set(
      content.match(/SPEAKER_\d+/g) || []
    )];
    if (speakerLabels.length === 0) {
      new import_obsidian9.Notice("No unidentified speakers found in this note");
      return;
    }
    const peopleFiles = this.app.vault.getMarkdownFiles().filter(
      (f) => f.path.startsWith("_Recap/") && f.path.includes("/People/")
    );
    const peopleNames = peopleFiles.map((f) => f.basename);
    const cache = this.app.metadataCache.getFileCache(file);
    const frontmatter = cache?.frontmatter;
    const recordingPath = frontmatter?.recording?.replace(/\[\[|\]\]/g, "") || "";
    const org = frontmatter?.org || "";
    const speakers = speakerLabels.map((label) => ({
      label,
      sampleClipPath: ""
      // TODO: daemon could serve sample clips
    }));
    new SpeakerCorrectionModal(
      this.app,
      speakers,
      peopleNames,
      [],
      // known contacts - could fetch from daemon
      recordingPath,
      org,
      this.client
    ).open();
  }
  async reprocessMeeting(file) {
    if (!this.client) {
      new import_obsidian9.Notice("Daemon not connected");
      return;
    }
    const cache = this.app.metadataCache.getFileCache(file);
    const frontmatter = cache?.frontmatter;
    const recordingPath = frontmatter?.recording?.replace(/\[\[|\]\]/g, "") || "";
    const org = frontmatter?.org || "";
    if (!recordingPath) {
      new import_obsidian9.Notice("No recording path found in frontmatter");
      return;
    }
    try {
      await this.client.reprocess(recordingPath, void 0, org);
      new import_obsidian9.Notice("Reprocessing started...");
    } catch (e) {
      new import_obsidian9.Notice(`Failed to reprocess: ${e}`);
    }
  }
  connectWebSocket() {
    if (!this.client)
      return;
    this.client.on("_connected", async () => {
      this.statusBar?.setConnected();
      void this.notificationHistory.load();
      try {
        const status = await this.client.getStatus();
        this.lastKnownState = status.state;
        this.statusBar?.updateState(status.state, status.recording?.org);
        this.broadcastDaemonState(status.state, status.recording?.org);
      } catch {
        this.statusBar?.setOffline();
        this.broadcastDaemonState(null);
        new import_obsidian9.Notice("Recap: Reconnected, but daemon status refresh failed");
      }
    });
    this.client.on("state_change", (event) => {
      const state = event.state;
      const org = event.org;
      this.lastKnownState = state;
      this.statusBar?.updateState(state, org);
      this.broadcastDaemonState(state, org);
      const leaves = this.app.workspace.getLeavesOfType(VIEW_LIVE_TRANSCRIPT);
      for (const leaf of leaves) {
        leaf.view.updateStatus(state);
      }
    });
    this.client.on("transcript_segment", (event) => {
      const leaves = this.app.workspace.getLeavesOfType(VIEW_LIVE_TRANSCRIPT);
      for (const leaf of leaves) {
        leaf.view.appendUtterance(
          event.speaker || "UNKNOWN",
          event.text || ""
        );
      }
    });
    this.client.on("error", (event) => {
      const message = event.message || "Unknown error";
      new import_obsidian9.Notice(`Recap error: ${message}`, 8e3);
    });
    this.client.on("silence_warning", (event) => {
      const message = event.message || "Extended silence during recording";
      new import_obsidian9.Notice(`Recap: ${message}`, 8e3);
    });
    this.client.on("rename_queued", async () => {
      await this.renameProcessor?.processQueue();
    });
    this.client.connectWebSocket(() => {
      this.statusBar?.setOffline();
      this.broadcastDaemonState(null);
    });
  }
  // Bug 5: Reconnect when daemon URL changes in settings
  async reconnect() {
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
        new import_obsidian9.Notice(`Recap: reconnection to daemon failed \u2014 ${msg}`);
        console.error("Recap:", e);
        this.statusBar?.setOffline();
      }
    } else {
      this.client = null;
      this.statusBar?.setOffline();
    }
  }
  async readAuthToken() {
    const tokenPath = "_Recap/.recap/auth-token";
    const exists = await this.app.vault.adapter.exists(tokenPath);
    if (!exists)
      return "";
    try {
      return (await this.app.vault.adapter.read(tokenPath)).trim();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian9.Notice(`Recap: could not read auth token \u2014 ${msg}`);
      console.error("Recap:", e);
      return "";
    }
  }
  async activateView(viewType) {
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
    if (viewType === VIEW_LIVE_TRANSCRIPT && this.client) {
      const leaves = workspace.getLeavesOfType(VIEW_LIVE_TRANSCRIPT);
      for (const l of leaves) {
        const view = l.view;
        try {
          const status = await this.client.getStatus();
          view.updateStatus(status.state);
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          new import_obsidian9.Notice(`Recap: could not sync live transcript view \u2014 ${msg}`);
          console.error("Recap:", e);
        }
      }
    }
  }
};
