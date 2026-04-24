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
  /** Fetch the transcript's distinct ``(speaker_id, display)`` pairs
   * along with the recording's metadata ``participants`` (names +
   * optional emails from calendar-sourced entries). Drives the
   * #28 speaker-correction modal's resolution engine. */
  async getMeetingSpeakers(stem) {
    return this.get(
      `/api/meetings/${encodeURIComponent(stem)}/speakers`
    );
  }
  /** Save a #28-style speaker correction: ``mapping`` keyed by
   * ``speaker_id`` + atomic ``contact_mutations`` the daemon applies
   * before reprocess. Supersedes the pre-#28 ``recording_path``-keyed
   * submit, which has been removed — the daemon still accepts that
   * shape on the wire for back-compat but no plugin code emits it. */
  async saveSpeakerCorrections(params) {
    return this.post("/api/meetings/speakers", params);
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
  /**
   * Ask the daemon to shut down. ``restart: true`` is only honored
   * when the daemon was launched via ``recap.launcher`` (returns 409
   * otherwise). The daemon sends the 200 before tearing down, so the
   * caller should poll ``/api/status`` to observe the replacement
   * process coming online.
   */
  async requestShutdown(restart) {
    await this.post("/api/admin/shutdown", { restart });
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
   * see ``fetchSpeakerClip`` for the Bearer-authed variant.
   *
   * Query key is ``speaker_id`` as of #28 — the daemon still accepts
   * ``speaker`` as a fallback during the transition (Task 9), but
   * the plugin always sends the stable diarized identity so clip
   * cache entries survive display relabels. */
  getSpeakerClipUrl(stem, speakerId, duration = 5) {
    const params = new URLSearchParams({
      speaker_id: speakerId,
      duration: String(duration)
    });
    return `${this.baseUrl}/api/recordings/${encodeURIComponent(stem)}/clip?${params.toString()}`;
  }
  async fetchSpeakerClip(stem, speakerId, duration = 5) {
    const resp = await fetch(
      this.getSpeakerClipUrl(stem, speakerId, duration),
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
    containerEl.createEl("h3", { text: "Daemon launch" });
    const launchContainer = containerEl.createDiv({
      cls: "recap-settings-launch"
    });
    this.renderLaunchSection(launchContainer);
  }
  renderLaunchSection(el) {
    new import_obsidian3.Setting(el).setName("Auto-start daemon with Obsidian").setDesc(
      "When enabled, the plugin starts the daemon if it's not already running. Disable if you manage the daemon separately (e.g. via an OS scheduler)."
    ).addToggle(
      (t) => t.setValue(this.plugin.settings.autostartEnabled).onChange(async (v) => {
        this.plugin.settings.autostartEnabled = v;
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian3.Setting(el).setName("Launcher executable").setDesc(
      "Full path to Python/uv executable or a binary name on PATH. Example: 'uv' or 'C:\\Python312\\python.exe'."
    ).addText(
      (t) => t.setPlaceholder("uv").setValue(this.plugin.settings.launcherExecutable).onChange(async (v) => {
        this.plugin.settings.launcherExecutable = v.trim();
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian3.Setting(el).setName("Launcher arguments").setDesc(
      "One argument per line. Typical: 'run', 'python', '-m', 'recap.launcher', 'config.yaml'."
    ).addTextArea((t) => {
      t.setPlaceholder("run\npython\n-m\nrecap.launcher\nconfig.yaml").setValue(this.plugin.settings.launcherArgs.join("\n")).onChange(async (v) => {
        this.plugin.settings.launcherArgs = v.split("\n").map((s) => s.trim()).filter((s) => s.length > 0);
        await this.plugin.saveSettings();
      });
      t.inputEl.rows = 6;
      return t;
    });
    new import_obsidian3.Setting(el).setName("Working directory").setDesc(
      "Usually the Recap repo root. Used as the cwd for the spawned launcher. Example: 'C:\\Users\\you\\Documents\\Projects\\recap'."
    ).addText(
      (t) => t.setPlaceholder("C:\\Users\\you\\Documents\\Projects\\recap").setValue(this.plugin.settings.launcherCwd).onChange(async (v) => {
        this.plugin.settings.launcherCwd = v.trim();
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian3.Setting(el).setName("Launcher log path").setDesc(
      "Absolute path for launcher.log. Leave blank to use '{vault}/_Recap/.recap/launcher.log'."
    ).addText(
      (t) => t.setPlaceholder("(default)").setValue(this.plugin.settings.launcherLogPath).onChange(async (v) => {
        this.plugin.settings.launcherLogPath = v.trim();
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian3.Setting(el).setName("Start daemon now").setDesc(
      "Spawn the launcher immediately using the current settings without waiting for an Obsidian reload. Useful after fixing a configuration error."
    ).addButton(
      (b) => b.setButtonText("Start daemon now").setCta().onClick(async () => {
        const cmds = this.app.commands;
        if (cmds?.executeCommandById) {
          cmds.executeCommandById("recap:start-daemon-now");
        } else {
          new import_obsidian3.Notice("Recap: 'Start daemon now' command not available. Reload plugin.");
        }
      })
    );
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
      cls: "setting-item-description"
    });
    const restartSetting = new import_obsidian3.Setting(container).setName("Restart daemon").setDesc(
      canRestart ? "Ask the daemon to shut down; the launcher wrapper will spawn a fresh child automatically." : "Daemon is running standalone. Relaunch via 'uv run python -m recap.launcher <config-path>' to enable one-click restarts from here."
    );
    restartSetting.addButton((btn) => {
      btn.setButtonText("Restart daemon");
      if (!canRestart) {
        btn.setDisabled(true);
        return;
      }
      btn.setCta().onClick(async () => {
        btn.setDisabled(true);
        btn.setButtonText("Restarting\u2026");
        try {
          await this.plugin.client.requestShutdown(true);
          new import_obsidian3.Notice(
            "Recap: restart requested. The daemon will be back in a few seconds.",
            6e3
          );
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          new import_obsidian3.Notice(`Recap: restart failed \u2014 ${msg}`, 8e3);
          btn.setDisabled(false);
          btn.setButtonText("Restart daemon");
        }
      });
    });
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

// src/components/TabStrip.ts
var LABELS = {
  today: "Today",
  upcoming: "Upcoming",
  past: "Past"
};
var ORDER = ["today", "upcoming", "past"];
var TabStrip = class {
  active;
  onChange;
  buttons = /* @__PURE__ */ new Map();
  constructor(parent, initial, onChange) {
    this.active = initial;
    this.onChange = onChange;
    const strip = parent.createDiv({ cls: "recap-tab-strip" });
    for (const tab of ORDER) {
      const btn = strip.createDiv({ cls: "recap-tab-button", text: LABELS[tab] });
      if (tab === initial)
        btn.addClass("is-active");
      btn.addEventListener("click", () => this.setActive(tab));
      this.buttons.set(tab, btn);
    }
  }
  setActive(tab) {
    if (tab === this.active)
      return;
    this.buttons.get(this.active)?.removeClass("is-active");
    this.buttons.get(tab)?.addClass("is-active");
    this.active = tab;
    this.onChange(tab);
  }
};

// src/components/NowDivider.ts
function renderNowDivider(container, now = /* @__PURE__ */ new Date()) {
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  return container.createDiv({
    cls: "recap-now-divider",
    text: `Now \xB7 ${hh}:${mm}`
  });
}

// src/components/FilterBar.ts
var EMPTY_FILTER_STATE = {
  org: "all",
  status: "all",
  company: "all",
  search: ""
};
var FilterBar = class {
  container;
  tabMode;
  orgs;
  companies;
  state;
  onChange;
  constructor(parent, tabMode, orgs, companies, initialState, onChange) {
    this.container = parent.createDiv({ cls: "recap-filter-bar" });
    this.tabMode = tabMode;
    this.orgs = orgs;
    this.companies = companies;
    this.state = { ...initialState };
    this.onChange = onChange;
    this.render();
  }
  render() {
    this.container.empty();
    if (this.tabMode === "upcoming" || this.tabMode === "past") {
      this.renderOrgSelect();
    }
    if (this.tabMode === "past") {
      this.renderCompanySelect();
      this.renderStatusSelect();
    }
    this.renderSearchInput();
  }
  renderOrgSelect() {
    const orgSelect = this.container.createEl("select", { cls: "recap-filter-select" });
    orgSelect.createEl("option", { value: "all", text: "All orgs" });
    for (const org of this.orgs) {
      orgSelect.createEl("option", { value: org, text: org });
    }
    orgSelect.value = this.state.org;
    orgSelect.addEventListener("change", () => {
      this.state.org = orgSelect.value;
      this.onChange(this.state);
    });
  }
  renderCompanySelect() {
    const companySelect = this.container.createEl("select", { cls: "recap-filter-select" });
    companySelect.createEl("option", { value: "all", text: "All companies" });
    for (const company of this.companies) {
      companySelect.createEl("option", { value: company, text: company });
    }
    companySelect.value = this.state.company;
    companySelect.addEventListener("change", () => {
      this.state.company = companySelect.value;
      this.onChange(this.state);
    });
  }
  renderStatusSelect() {
    const statusSelect = this.container.createEl("select", { cls: "recap-filter-select" });
    const options = [
      ["all", "All status"],
      ["complete", "Complete"],
      ["failed", "Failed"],
      ["pending", "Pending"],
      ["processing", "Processing"]
    ];
    for (const [value, label] of options) {
      statusSelect.createEl("option", { value, text: label });
    }
    statusSelect.value = this.state.status;
    statusSelect.addEventListener("change", () => {
      this.state.status = statusSelect.value;
      this.onChange(this.state);
    });
  }
  renderSearchInput() {
    const searchInput = this.container.createEl("input", {
      type: "text",
      placeholder: "Search meetings...",
      cls: "recap-filter-search"
    });
    searchInput.value = this.state.search;
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
function renderMeetingRow(container, meeting, onClick, opts) {
  const row = container.createDiv({ cls: "recap-meeting-row" });
  if (opts?.isPast) {
    row.addClass("recap-meeting-row-past");
  }
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

// src/lib/meetingTime.ts
var ALL_DAY = {
  start: "00:00",
  end: "23:59",
  allDay: true
};
var TIME_RANGE = /^(([01]\d|2[0-3]):[0-5]\d)-(([01]\d|2[0-3]):[0-5]\d)$/;
function parseMeetingTime(raw) {
  if (raw == null) {
    return ALL_DAY;
  }
  const trimmed = raw.trim();
  const match = TIME_RANGE.exec(trimmed);
  if (!match) {
    return ALL_DAY;
  }
  return {
    start: match[1],
    end: match[3],
    allDay: false
  };
}
function todayIsoDate(now = /* @__PURE__ */ new Date()) {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

// src/lib/deriveMeetings.ts
function minutesSinceMidnight(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}
function isRowPast(m, now) {
  const parsed = parseMeetingTime(m.time);
  if (parsed.allDay)
    return false;
  const nowMin = now.getHours() * 60 + now.getMinutes();
  return minutesSinceMidnight(parsed.end) < nowMin;
}
function matchesOrg(m, filter) {
  return filter.org === "all" || m.org === filter.org;
}
function matchesCompany(m, filter) {
  if (filter.company === "all")
    return true;
  return m.companies.includes(filter.company);
}
function matchesStatus(m, filter) {
  if (filter.status === "all")
    return true;
  if (filter.status === "failed")
    return m.pipelineStatus.startsWith("failed");
  return m.pipelineStatus === filter.status;
}
function matchesSearch(m, filter) {
  if (!filter.search)
    return true;
  const q = filter.search.toLowerCase();
  if (m.title.toLowerCase().includes(q))
    return true;
  return m.participants.some((p) => p.toLowerCase().includes(q));
}
function passesAllFilters(m, filter) {
  return matchesOrg(m, filter) && matchesCompany(m, filter) && matchesStatus(m, filter) && matchesSearch(m, filter);
}
function decorate(m, now) {
  return { ...m, isPast: isRowPast(m, now) };
}
function deriveTodayMeetings(meetings, now, filter) {
  const today = todayIsoDate(now);
  const rows = meetings.filter((m) => m.date === today).filter((m) => passesAllFilters(m, filter)).map((m) => decorate(m, now)).sort(
    (a, b) => minutesSinceMidnight(parseMeetingTime(a.time).start) - minutesSinceMidnight(parseMeetingTime(b.time).start)
  );
  const firstNonPast = rows.findIndex((r) => !r.isPast);
  const nowDividerIndex = firstNonPast > 0 ? firstNonPast : null;
  return { rows, nowDividerIndex };
}
function deriveUpcomingMeetings(meetings, now, filter) {
  const today = todayIsoDate(now);
  return meetings.filter((m) => m.date > today).filter((m) => passesAllFilters(m, filter)).map((m) => decorate(m, now)).sort((a, b) => {
    if (a.date !== b.date)
      return a.date.localeCompare(b.date);
    return minutesSinceMidnight(parseMeetingTime(a.time).start) - minutesSinceMidnight(parseMeetingTime(b.time).start);
  });
}
function derivePastMeetings(meetings, now, filter) {
  const today = todayIsoDate(now);
  return meetings.filter((m) => m.date < today).filter((m) => passesAllFilters(m, filter)).map((m) => decorate(m, now)).sort((a, b) => {
    if (a.date !== b.date)
      return b.date.localeCompare(a.date);
    return minutesSinceMidnight(parseMeetingTime(b.time).start) - minutesSinceMidnight(parseMeetingTime(a.time).start);
  });
}

// src/views/MeetingListView.ts
var RELOAD_DEBOUNCE_MS = 300;
var VIEW_MEETING_LIST = "recap-meeting-list";
var MeetingListView = class extends import_obsidian4.ItemView {
  meetings = [];
  listContainer = null;
  deps;
  // Status row elements (created in onOpen, updated via updateDaemonState).
  statusDotEl = null;
  statusLabelEl = null;
  actionBtnEl = null;
  currentState = null;
  currentOrg = void 0;
  // Three-tab layout state: which tab is active, and a per-tab filter state
  // so switching between tabs doesn't blow away what the user typed into
  // the search box on another tab.
  activeTab = "today";
  filterStates = {
    today: { ...EMPTY_FILTER_STATE },
    upcoming: { ...EMPTY_FILTER_STATE },
    past: { ...EMPTY_FILTER_STATE }
  };
  filterSlot = null;
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
    new TabStrip(container, this.activeTab, (tab) => {
      this.activeTab = tab;
      this.refreshFilterBar();
      this.renderMeetings();
    });
    this.filterSlot = container.createDiv({ cls: "recap-filter-slot" });
    this.refreshFilterBar();
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
    this.refreshFilterBar();
    this.renderMeetings();
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
          time: frontmatter.time || "",
          org: frontmatter.org || "",
          duration: frontmatter.duration || "",
          pipelineStatus: frontmatter["pipeline-status"] || "pending",
          participants: this.parseParticipants(frontmatter.participants || []),
          companies: this.parseParticipants(frontmatter.companies || []),
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
  }
  parseParticipants(raw) {
    if (!Array.isArray(raw))
      return [];
    return raw.map((p) => p.replace(/\[\[|\]\]/g, ""));
  }
  refreshFilterBar() {
    const orgs = [...new Set(this.meetings.map((m) => m.org).filter(Boolean))];
    const companies = [...new Set(
      this.meetings.flatMap((m) => m.companies).filter(Boolean)
    )].sort();
    const state = this.filterStates[this.activeTab];
    if (this.filterSlot === null)
      return;
    this.filterSlot.empty();
    new FilterBar(
      this.filterSlot,
      this.activeTab,
      orgs,
      companies,
      state,
      (next) => {
        this.filterStates[this.activeTab] = next;
        this.renderMeetings();
      }
    );
  }
  openMeeting(path) {
    const file = this.app.vault.getAbstractFileByPath(path);
    if (file instanceof import_obsidian4.TFile) {
      this.app.workspace.getLeaf(false).openFile(file);
    }
  }
  renderMeetings() {
    if (!this.listContainer)
      return;
    this.listContainer.empty();
    const now = /* @__PURE__ */ new Date();
    const state = this.filterStates[this.activeTab];
    if (this.activeTab === "today") {
      const { rows: rows2, nowDividerIndex } = deriveTodayMeetings(
        this.meetings,
        now,
        state
      );
      this.renderRowsWithDivider(rows2, nowDividerIndex, now);
      return;
    }
    const rows = this.activeTab === "upcoming" ? deriveUpcomingMeetings(this.meetings, now, state) : derivePastMeetings(this.meetings, now, state);
    this.renderRows(rows);
  }
  renderRows(rows) {
    if (!this.listContainer)
      return;
    if (rows.length === 0) {
      this.listContainer.createDiv({
        text: "No meetings found",
        cls: "recap-empty-state"
      });
      return;
    }
    for (const row of rows) {
      renderMeetingRow(
        this.listContainer,
        row,
        (path) => this.openMeeting(path),
        { isPast: row.isPast }
      );
    }
  }
  renderRowsWithDivider(rows, nowDividerIndex, now) {
    if (!this.listContainer)
      return;
    if (rows.length === 0) {
      this.listContainer.createDiv({
        text: "No meetings today",
        cls: "recap-empty-state"
      });
      return;
    }
    rows.forEach((row, i) => {
      if (nowDividerIndex !== null && i === nowDividerIndex) {
        renderNowDivider(this.listContainer, now);
      }
      renderMeetingRow(
        this.listContainer,
        row,
        (path) => this.openMeeting(path),
        { isPast: row.isPast }
      );
    });
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

// src/correction/normalize.ts
var MULTI_WS = /\s+/g;
var STRIP_PUNCT = /[.,]/g;
function normalize(text) {
  let s = text.trim();
  if (!s)
    return "";
  s = s.replace(STRIP_PUNCT, "");
  s = s.replace(MULTI_WS, " ");
  return s.toLowerCase().trim();
}

// src/correction/resolve.ts
var SPEAKER_ID_RE = /^SPEAKER_\d+$/;
var UNKNOWN_RE = /^(UNKNOWN|Unknown Speaker.*)$/i;
var PARENTHETICAL_RE = /\([^)]+\)/;
function resolve(typed, ctx, options) {
  const normalized = normalize(typed);
  if (!normalized)
    return { kind: "ineligible", reason: "empty", typed };
  const linked = tryMatches(typed, normalized, ctx);
  if (linked)
    return linked;
  const stripped = typed.replace(PARENTHETICAL_RE, "").trim();
  if (stripped !== typed && normalize(stripped)) {
    const retried = tryMatches(stripped, normalize(stripped), ctx);
    if (retried)
      return retried;
  }
  if (!options?.skipNearMatch) {
    const near = findNearMatch(normalized, ctx);
    if (near)
      return { kind: "near_match_ambiguous", suggestion: near, typed };
  }
  const ineligibility = checkIneligibility(typed, normalized, ctx);
  if (ineligibility)
    return ineligibility;
  const participant = ctx.meetingParticipants.find(
    (p) => normalize(p.name) === normalized && p.email
  );
  return { kind: "create_new_contact", name: typed, email: participant?.email ?? void 0 };
}
function tryMatches(typed, normalized, ctx) {
  const participant = ctx.meetingParticipants.find(
    (p) => normalize(p.name) === normalized && p.email
  );
  if (participant?.email) {
    const byEmail = ctx.knownContacts.find(
      (c) => c.email?.toLowerCase() === participant.email.toLowerCase()
    );
    if (byEmail)
      return {
        kind: "link_to_existing",
        canonical_name: byEmail.name,
        requires_contact_create: false
      };
  }
  for (const c of ctx.knownContacts) {
    const candidates = [c.name, c.display_name, ...c.aliases || []];
    for (const cand of candidates) {
      if (cand && normalize(cand) === normalized) {
        return {
          kind: "link_to_existing",
          canonical_name: c.name,
          requires_contact_create: false
        };
      }
    }
  }
  const peopleMatch = ctx.peopleNames.find((n) => normalize(n) === normalized);
  if (peopleMatch) {
    return {
      kind: "link_to_existing",
      canonical_name: peopleMatch,
      requires_contact_create: true,
      email: participant?.email ?? void 0
    };
  }
  return null;
}
function findNearMatch(normalizedTyped, ctx) {
  const typedTokens = normalizedTyped.split(" ").filter(Boolean);
  if (typedTokens.length === 0)
    return null;
  const candidates = [
    ...ctx.knownContacts.map((c) => ({
      canonical: c.name,
      names: [c.name, c.display_name, ...c.aliases || []].filter(Boolean)
    })),
    ...ctx.peopleNames.map((n) => ({ canonical: n, names: [n] }))
  ];
  for (const cand of candidates) {
    for (const candName of cand.names) {
      if (initialAwareMatch(typedTokens, normalize(candName).split(" ").filter(Boolean))) {
        return cand.canonical;
      }
    }
  }
  return null;
}
function initialAwareMatch(typed, candidate) {
  if (typed.length === 0 || candidate.length === 0)
    return false;
  if (typed[0] !== candidate[0])
    return false;
  if (typed.length > candidate.length)
    return false;
  if (typed.length === candidate.length && typed.every((t, i) => t === candidate[i])) {
    return false;
  }
  for (let i = 1; i < typed.length; i++) {
    const t = typed[i];
    const c = candidate[i];
    if (t === c)
      continue;
    if (t.length === 1 && c.startsWith(t))
      continue;
    return false;
  }
  return true;
}
function checkIneligibility(typed, normalized, ctx) {
  const s = typed.trim();
  if (!s)
    return { kind: "ineligible", reason: "empty", typed };
  if (SPEAKER_ID_RE.test(s))
    return { kind: "ineligible", reason: "SPEAKER_XX", typed };
  if (UNKNOWN_RE.test(s))
    return { kind: "ineligible", reason: "Unknown Speaker", typed };
  if (PARENTHETICAL_RE.test(s))
    return { kind: "ineligible", reason: "parenthetical", typed };
  if (s.includes("/"))
    return { kind: "ineligible", reason: "multi-person (contains /)", typed };
  if (ctx.companyNames.some((c) => normalize(c) === normalized)) {
    return { kind: "ineligible", reason: "matches Company note", typed };
  }
  return null;
}

// src/views/SpeakerCorrectionModal.ts
var SpeakerCorrectionModal = class extends import_obsidian6.Modal {
  speakers;
  peopleNames;
  companyNames;
  knownContacts;
  meetingParticipants;
  stem;
  org;
  orgSubfolder;
  client;
  rows = [];
  objectUrls = [];
  saveBtn = null;
  constructor(app, speakers, peopleNames, companyNames, knownContacts, meetingParticipants, stem, org, orgSubfolder, client) {
    super(app);
    this.speakers = speakers;
    this.peopleNames = peopleNames;
    this.companyNames = companyNames;
    this.knownContacts = knownContacts;
    this.meetingParticipants = meetingParticipants;
    this.stem = stem;
    this.org = org;
    this.orgSubfolder = orgSubfolder;
    this.client = client;
  }
  onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("recap-speaker-modal");
    contentEl.createEl("h2", { text: "Identify Speakers" });
    contentEl.createEl("p", {
      text: "Assign a name to each speaker. The plugin will suggest links to existing contacts and flag rows that need attention.",
      cls: "setting-item-description"
    });
    const datalist = contentEl.createEl("datalist");
    datalist.id = "recap-known-contacts";
    this.populateContactsDatalist(datalist);
    for (const speaker of this.speakers) {
      this.renderRow(contentEl, speaker);
    }
    const btnRow = contentEl.createDiv({ cls: "recap-modal-buttons" });
    const cancelBtn = btnRow.createEl("button", { text: "Cancel" });
    cancelBtn.addEventListener("click", () => this.close());
    const saveBtn = btnRow.createEl("button", {
      text: "Save & Reprocess",
      cls: "mod-cta"
    });
    saveBtn.addEventListener("click", () => void this.onSubmit());
    this.saveBtn = saveBtn;
    this.refreshSaveButton();
  }
  renderRow(parent, speaker) {
    const row = parent.createDiv({ cls: "recap-speaker-row" });
    row.createSpan({
      text: speaker.speaker_id,
      cls: "recap-speaker-label"
    });
    const audioEl = row.createEl("audio");
    audioEl.controls = true;
    audioEl.preload = "none";
    audioEl.addClass("recap-speaker-audio");
    void this.loadClipInto(audioEl, speaker.speaker_id, row);
    const initialTyped = /^SPEAKER_\d+$/.test(speaker.display) ? "" : speaker.display;
    const input = row.createEl("input", {
      type: "text",
      placeholder: "Enter name...",
      cls: "recap-speaker-input",
      value: initialTyped
    });
    input.setAttribute("list", "recap-known-contacts");
    const hintEl = row.createDiv({ cls: "recap-speaker-hint" });
    const rowState = {
      speaker_id: speaker.speaker_id,
      display: speaker.display,
      typedName: initialTyped,
      currentPlan: this.computePlan(initialTyped),
      hintEl,
      inputEl: input
    };
    this.rows.push(rowState);
    const rerunPlan = () => {
      rowState.typedName = input.value;
      rowState.currentPlan = this.computePlan(input.value);
      this.renderHint(rowState);
      this.refreshSaveButton();
    };
    input.addEventListener("input", rerunPlan);
    input.addEventListener("blur", rerunPlan);
    this.renderHint(rowState);
  }
  computePlan(typed, options) {
    if (!typed.trim()) {
      return { kind: "ineligible", reason: "empty", typed };
    }
    const knownContactsForResolve = this.knownContacts.map((c) => ({
      name: c.name,
      display_name: c.display_name ?? c.name,
      aliases: c.aliases,
      email: c.email
    }));
    return resolve(typed, {
      knownContacts: knownContactsForResolve,
      peopleNames: this.peopleNames,
      companyNames: this.companyNames,
      meetingParticipants: this.meetingParticipants
    }, options);
  }
  renderHint(row) {
    row.hintEl.empty();
    row.hintEl.removeClass(
      "recap-speaker-hint-ok",
      "recap-speaker-hint-warn",
      "recap-speaker-hint-error"
    );
    const plan = row.currentPlan;
    switch (plan.kind) {
      case "link_to_existing": {
        row.hintEl.addClass("recap-speaker-hint-ok");
        const suffix = plan.requires_contact_create ? " (will also add contact)" : "";
        row.hintEl.createSpan({
          text: `Links to ${plan.canonical_name}${suffix}`
        });
        break;
      }
      case "create_new_contact": {
        row.hintEl.addClass("recap-speaker-hint-ok");
        row.hintEl.createSpan({
          text: "Will create new contact and People note"
        });
        break;
      }
      case "near_match_ambiguous": {
        row.hintEl.addClass("recap-speaker-hint-warn");
        row.hintEl.createSpan({
          text: `Did you mean ${plan.suggestion}? `
        });
        const useBtn = row.hintEl.createEl("button", {
          text: "Use existing",
          cls: "recap-hint-btn"
        });
        useBtn.addEventListener("click", () => {
          row.currentPlan = {
            kind: "link_to_existing",
            canonical_name: plan.suggestion,
            requires_contact_create: false
          };
          this.renderHint(row);
          this.refreshSaveButton();
        });
        const newBtn = row.hintEl.createEl("button", {
          text: "Create new anyway",
          cls: "recap-hint-btn"
        });
        newBtn.addEventListener("click", () => {
          row.currentPlan = this.computePlan(
            row.typedName,
            { skipNearMatch: true }
          );
          this.renderHint(row);
          this.refreshSaveButton();
        });
        break;
      }
      case "ineligible": {
        row.hintEl.addClass("recap-speaker-hint-error");
        const label = plan.reason === "empty" ? "Enter a name to continue" : `Rename required: ${plan.reason}`;
        row.hintEl.createSpan({ text: label });
        break;
      }
    }
  }
  refreshSaveButton() {
    if (!this.saveBtn)
      return;
    const blocked = this.rows.some(
      (r) => r.currentPlan.kind === "ineligible" || r.currentPlan.kind === "near_match_ambiguous"
    );
    this.saveBtn.disabled = blocked;
  }
  async onSubmit() {
    const mapping = {};
    const contact_mutations = [];
    for (const row of this.rows) {
      const plan = row.currentPlan;
      if (plan.kind === "link_to_existing") {
        mapping[row.speaker_id] = plan.canonical_name;
        if (plan.requires_contact_create) {
          const mutation = {
            action: "create",
            name: plan.canonical_name,
            display_name: plan.canonical_name
          };
          if (plan.email)
            mutation.email = plan.email;
          contact_mutations.push(mutation);
        } else if (normalize(row.typedName) !== normalize(plan.canonical_name)) {
          contact_mutations.push({
            action: "add_alias",
            name: plan.canonical_name,
            alias: row.typedName
          });
        }
      } else if (plan.kind === "create_new_contact") {
        mapping[row.speaker_id] = plan.name;
        const mutation = {
          action: "create",
          name: plan.name,
          display_name: plan.name
        };
        if (plan.email)
          mutation.email = plan.email;
        contact_mutations.push(mutation);
      }
    }
    if (Object.keys(mapping).length === 0) {
      new import_obsidian6.Notice("No speakers assigned");
      return;
    }
    try {
      await this.client.saveSpeakerCorrections({
        stem: this.stem,
        mapping,
        contact_mutations,
        org: this.org
      });
      new import_obsidian6.Notice(
        "Speaker corrections submitted \u2014 reprocessing..."
      );
      this.close();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian6.Notice(`Recap: submit corrections failed \u2014 ${msg}`);
      console.error("Recap:", e);
    }
  }
  async populateContactsDatalist(datalist) {
    const combined = /* @__PURE__ */ new Set([
      ...this.peopleNames
    ]);
    for (const c of this.knownContacts) {
      if (c.name)
        combined.add(c.name);
      if (c.display_name)
        combined.add(c.display_name);
      for (const alias of c.aliases || []) {
        if (alias)
          combined.add(alias);
      }
    }
    for (const name of [...combined].sort()) {
      datalist.createEl("option", { value: name });
    }
  }
  async loadClipInto(audioEl, speakerId, row) {
    try {
      const blob = await this.client.fetchSpeakerClip(
        this.stem,
        speakerId,
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
        speakerId,
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
    this.rows = [];
    this.saveBtn = null;
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

// src/launchSettings.ts
var DEFAULT_LAUNCH_SETTINGS = {
  autostartEnabled: true,
  launcherExecutable: "",
  launcherArgs: [],
  launcherCwd: "",
  launcherLogPath: ""
};

// src/authToken.ts
var AUTH_TOKEN_PATH = "_Recap/.recap/auth-token";
async function readAuthTokenWithRetry(adapter, path = AUTH_TOKEN_PATH, maxAttempts = 3, delayMs = 500) {
  for (let i = 0; i < maxAttempts; i++) {
    if (await adapter.exists(path)) {
      const raw = await adapter.read(path);
      return raw.trim();
    }
    if (i < maxAttempts - 1) {
      await new Promise((r) => setTimeout(r, delayMs));
    }
  }
  return "";
}

// src/daemonLauncher.ts
async function probeHealth(baseUrl, timeoutMs, fetchImpl = fetch) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetchImpl(`${baseUrl}/health`, {
      method: "GET",
      signal: controller.signal
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
function spawnLauncher(params, spawnFn) {
  return new Promise((resolve2) => {
    const opts = {
      cwd: params.cwd,
      env: { ...process.env, ...params.env },
      detached: true,
      stdio: "ignore",
      windowsHide: true
    };
    const child = spawnFn(params.executable, params.args, opts);
    const onSpawn = () => {
      child.removeListener("error", onError);
      child.unref();
      resolve2({ kind: "SPAWNED", child, pid: child.pid });
    };
    const onError = (err) => {
      child.removeListener("spawn", onSpawn);
      resolve2({
        kind: "ERROR",
        code: err.code,
        message: err.message || "spawn failed"
      });
    };
    child.once("spawn", onSpawn);
    child.once("error", onError);
  });
}
var DEFAULT_POLL_INTERVAL_MS = 500;
var DEFAULT_POLL_TOTAL_MS = 15e3;
var PROBE_TIMEOUT_MS = 2e3;
function pollUntilReady(params) {
  const {
    baseUrl,
    child,
    intervalMs = DEFAULT_POLL_INTERVAL_MS,
    totalMs = DEFAULT_POLL_TOTAL_MS,
    fetchImpl = fetch
  } = params;
  return new Promise((resolve2) => {
    let settled = false;
    const startedAt = Date.now();
    const finish = (result) => {
      if (settled)
        return;
      settled = true;
      child.removeListener("exit", onExit);
      resolve2(result);
    };
    const onExit = (code, signal) => {
      finish({ kind: "EXITED", exitCode: code, signal });
    };
    child.once("exit", onExit);
    const tick = async () => {
      if (settled)
        return;
      if (Date.now() - startedAt > totalMs) {
        finish({ kind: "TIMEOUT" });
        return;
      }
      const ok = await probeHealth(baseUrl, PROBE_TIMEOUT_MS, fetchImpl);
      if (settled)
        return;
      if (ok) {
        finish({ kind: "READY" });
        return;
      }
      setTimeout(tick, intervalMs);
    };
    tick();
  });
}
var INITIAL_PROBE_TIMEOUT_MS = 2e3;
function isConfigured(s) {
  return s.launcherExecutable.trim() !== "" && s.launcherArgs.length > 0 && s.launcherCwd.trim() !== "";
}
async function runLauncherStateMachine(params) {
  const {
    baseUrl,
    settings,
    spawnFn,
    fetchImpl = fetch,
    intervalMs,
    totalMs,
    defaultLogPath = ""
  } = params;
  if (await probeHealth(baseUrl, INITIAL_PROBE_TIMEOUT_MS, fetchImpl)) {
    return { kind: "ALREADY_RUNNING" };
  }
  if (!settings.autostartEnabled)
    return { kind: "DISABLED" };
  if (!isConfigured(settings))
    return { kind: "NOT_CONFIGURED" };
  const logPath = settings.launcherLogPath || defaultLogPath;
  const spawnResult = await spawnLauncher(
    {
      executable: settings.launcherExecutable,
      args: settings.launcherArgs,
      cwd: settings.launcherCwd,
      env: logPath ? { RECAP_LAUNCHER_LOG: logPath } : {}
    },
    spawnFn
  );
  if (spawnResult.kind === "ERROR") {
    return {
      kind: "SPAWN_ERROR",
      code: spawnResult.code,
      message: spawnResult.message
    };
  }
  const pollResult = await pollUntilReady({
    baseUrl,
    child: spawnResult.child,
    intervalMs,
    totalMs,
    fetchImpl
  });
  if (pollResult.kind === "READY") {
    return { kind: "SPAWNED_AND_READY", pid: spawnResult.pid };
  }
  if (pollResult.kind === "EXITED") {
    return {
      kind: "EARLY_EXIT",
      exitCode: pollResult.exitCode,
      signal: pollResult.signal
    };
  }
  return { kind: "POLL_TIMEOUT", pid: spawnResult.pid, logPath };
}

// src/daemonLauncherNotices.ts
function noticeForOutcome(outcome) {
  switch (outcome.kind) {
    case "ALREADY_RUNNING":
      return { notice: null, statusBarOffline: false, shouldRehydrate: true };
    case "DISABLED":
      return { notice: null, statusBarOffline: true, shouldRehydrate: false };
    case "NOT_CONFIGURED":
      return {
        notice: "Recap launcher not configured. Open Settings -> Recap -> Daemon launch.",
        statusBarOffline: true,
        shouldRehydrate: false
      };
    case "SPAWN_ERROR":
      return {
        notice: `Recap launcher failed to start: ${outcome.code ?? "error"} ${outcome.message}`,
        statusBarOffline: true,
        shouldRehydrate: false
      };
    case "EARLY_EXIT": {
      const codeStr = outcome.exitCode !== null ? String(outcome.exitCode) : "killed";
      return {
        notice: `Recap launcher exited with code ${codeStr} before daemon started. launcher.log may not exist if the launcher module itself failed. Verify launcherCwd and launcherExecutable in settings.`,
        statusBarOffline: true,
        shouldRehydrate: false
      };
    }
    case "POLL_TIMEOUT":
      return {
        notice: `Recap daemon started (launcher pid=${outcome.pid ?? "?"}) but didn't respond within 15s. Check ${outcome.logPath || "launcher.log"}.`,
        statusBarOffline: true,
        shouldRehydrate: false
      };
    case "SPAWNED_AND_READY":
      return { notice: null, statusBarOffline: false, shouldRehydrate: true };
  }
}

// src/vaultPaths.ts
function vaultRelativeToConcrete(adapter, vaultRelative) {
  const getFullPath = adapter.getFullPath;
  if (typeof getFullPath === "function") {
    try {
      return getFullPath.call(adapter, vaultRelative);
    } catch {
    }
  }
  return vaultRelative;
}

// src/main.ts
var nodeRequire = globalThis.require;
var { spawn } = nodeRequire("child_process");
var DEFAULT_SETTINGS = {
  daemonUrl: "http://127.0.0.1:9847",
  ...DEFAULT_LAUNCH_SETTINGS
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
    const statusBarEl = this.addStatusBarItem();
    this.statusBar = new RecapStatusBar(statusBarEl);
    const defaultLogPath = vaultRelativeToConcrete(
      this.app.vault.adapter,
      "_Recap/.recap/launcher.log"
    );
    const outcome = await runLauncherStateMachine({
      baseUrl: this.settings.daemonUrl,
      settings: this.settings,
      spawnFn: spawn,
      defaultLogPath
    });
    const decision = noticeForOutcome(outcome);
    if (decision.notice)
      new import_obsidian9.Notice(decision.notice);
    if (decision.statusBarOffline) {
      this.statusBar.setOffline();
    }
    this.renameProcessor = new RenameProcessor(this.app, "_Recap/.recap/rename-queue.json");
    await this.renameProcessor.processQueue();
    if (decision.shouldRehydrate) {
      await this.rehydrateClient();
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
      id: "start-daemon-now",
      name: "Start daemon now",
      callback: async () => {
        const defaultLogPath2 = vaultRelativeToConcrete(
          this.app.vault.adapter,
          "_Recap/.recap/launcher.log"
        );
        const outcome2 = await runLauncherStateMachine({
          baseUrl: this.settings.daemonUrl,
          settings: { ...this.settings, autostartEnabled: true },
          spawnFn: spawn,
          defaultLogPath: defaultLogPath2
        });
        const d = noticeForOutcome(outcome2);
        if (d.notice)
          new import_obsidian9.Notice(d.notice);
        if (d.statusBarOffline)
          this.statusBar?.setOffline();
        if (d.shouldRehydrate)
          await this.rehydrateClient();
      }
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
    const cache = this.app.metadataCache.getFileCache(file);
    const fm = cache?.frontmatter;
    const recording = (fm?.recording ?? "").toString().replace(/\[\[|\]\]/g, "");
    const stem = recording.replace(/\.(flac|m4a|aac)$/i, "");
    const org = (fm?.org ?? "").toString();
    const orgSubfolder = (fm?.["org-subfolder"] ?? "").toString();
    if (!stem) {
      new import_obsidian9.Notice("No recording in frontmatter");
      return;
    }
    if (!orgSubfolder) {
      new import_obsidian9.Notice("Missing org-subfolder in frontmatter");
      return;
    }
    let resp;
    try {
      resp = await this.client.getMeetingSpeakers(stem);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian9.Notice(`Could not load speakers: ${msg}`);
      console.error("Recap:", e);
      return;
    }
    if (resp.speakers.length === 0) {
      new import_obsidian9.Notice("No speakers in transcript");
      return;
    }
    const peopleNames = this.scanNotesByFolder(`${orgSubfolder}/People`);
    const companyNames = this.scanNotesByFolder(
      `${orgSubfolder}/Companies`
    );
    let knownContacts = [];
    try {
      const cfg = await this.client.getConfig();
      knownContacts = cfg.known_contacts || [];
    } catch (e) {
      console.warn("Recap: could not load known contacts", e);
    }
    const meetingParticipants = resp.participants.map((p) => ({
      name: p.name,
      email: p.email ?? void 0
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
      this.client
    ).open();
  }
  scanNotesByFolder(folderPath) {
    const prefix = folderPath.endsWith("/") ? folderPath : `${folderPath}/`;
    return this.app.vault.getMarkdownFiles().filter((f) => f.path.startsWith(prefix)).map((f) => f.basename);
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
    try {
      return await readAuthTokenWithRetry(
        this.app.vault.adapter,
        AUTH_TOKEN_PATH,
        1
        // single attempt for initial onload; rehydrateClient retries
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new import_obsidian9.Notice(`Recap: could not read auth token \u2014 ${msg}`);
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
  async rehydrateClient() {
    const token = await readAuthTokenWithRetry(this.app.vault.adapter);
    if (!token) {
      new import_obsidian9.Notice(
        `Recap: daemon running but auth token not found at ${AUTH_TOKEN_PATH}. Re-pair via tray menu.`
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
      new import_obsidian9.Notice(`Recap: post-spawn status fetch failed \u2014 ${msg}`);
      this.statusBar?.setOffline();
      return false;
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
