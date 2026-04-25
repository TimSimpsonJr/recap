import { ItemView, Menu, Notice, WorkspaceLeaf, TAbstractFile, TFile } from "obsidian";
import type { DaemonClient } from "../api";
import { TabStrip } from "../components/TabStrip";
import { renderNowDivider } from "../components/NowDivider";
import { FilterBar, FilterState, EMPTY_FILTER_STATE } from "../components/FilterBar";
import { MeetingData, renderMeetingRow } from "../components/MeetingRow";
import {
    Tab,
    deriveTodayMeetings,
    deriveUpcomingMeetings,
    derivePastMeetings,
    DecoratedRow,
} from "../lib/deriveMeetings";

/** Debounce window (ms) for coalescing bursts of vault events during a
 * pipeline write -- transcript.json, meeting note, stub profiles, and
 * recording metadata can all land within the same tick. */
const RELOAD_DEBOUNCE_MS = 300;

export const VIEW_MEETING_LIST = "recap-meeting-list";

export interface MeetingListViewDeps {
    getClient: () => DaemonClient | null;
    onStartRecording: () => Promise<void>;
    onStopRecording: () => Promise<void>;
    onLinkToCalendar: (file: TFile) => void;
}

export class MeetingListView extends ItemView {
    private meetings: MeetingData[] = [];
    private listContainer: HTMLElement | null = null;
    private deps: MeetingListViewDeps;

    // Status row elements (created in onOpen, updated via updateDaemonState).
    private statusDotEl: HTMLElement | null = null;
    private statusLabelEl: HTMLElement | null = null;
    private actionBtnEl: HTMLButtonElement | null = null;
    private currentState: string | null = null;
    private currentOrg: string | undefined = undefined;

    // Three-tab layout state: which tab is active, and a per-tab filter state
    // so switching between tabs doesn't blow away what the user typed into
    // the search box on another tab.
    private activeTab: Tab = "today";
    private filterStates: Record<Tab, FilterState> = {
        today: { ...EMPTY_FILTER_STATE },
        upcoming: { ...EMPTY_FILTER_STATE },
        past: { ...EMPTY_FILTER_STATE },
    };
    private filterSlot: HTMLElement | null = null;

    // Pending reload timer for debouncing bursts of vault create/modify events.
    private reloadTimer: number | null = null;
    // Meeting-scope prefixes configured by the daemon (org subfolders).
    // Cached from loadMeetings() so vault event handlers can cheaply decide
    // whether a changed file is within the scope we care about.
    private meetingPathPrefixes: string[] = [];

    constructor(leaf: WorkspaceLeaf, deps: MeetingListViewDeps) {
        super(leaf);
        this.deps = deps;
    }

    getViewType(): string { return VIEW_MEETING_LIST; }
    getDisplayText(): string { return "Recap Meetings"; }
    getIcon(): string { return "mic"; }

    async onOpen(): Promise<void> {
        const container = this.containerEl.children[1] as HTMLElement;
        container.empty();
        container.addClass("recap-meeting-list-container");

        // Header + daemon status row with Start/Stop button.
        container.createEl("h4", { text: "Meetings" });
        this.renderStatusRow(container);

        // Seed initial state from the daemon (falls back to offline if unreachable).
        await this.refreshDaemonStateFromClient();

        // Load meetings from vault
        await this.loadMeetings();

        // Three-tab strip sits above the filter bar; switching tabs rebuilds
        // the filter bar (different tabs expose different controls) and
        // re-renders the list.
        new TabStrip(container, this.activeTab, (tab) => {
            this.activeTab = tab;
            this.refreshFilterBar();
            this.renderMeetings();
        });
        this.filterSlot = container.createDiv({ cls: "recap-filter-slot" });
        this.refreshFilterBar();

        // Meeting list
        this.listContainer = container.createDiv({ cls: "recap-meeting-list" });
        this.renderMeetings();

        // Vault is the source of truth for the meeting list. Subscribe here
        // rather than only reacting to daemon state_change: notes can arrive
        // from pipeline writes, rename-queue processing in the plugin, and
        // manual user edits -- all of which the daemon doesn't broadcast.
        // ``registerEvent`` auto-unregisters on view close.
        this.registerEvent(
            this.app.vault.on("create", (f) => this.maybeScheduleReload(f.path)),
        );
        this.registerEvent(
            this.app.vault.on("delete", (f) => this.maybeScheduleReload(f.path)),
        );
        this.registerEvent(
            this.app.vault.on("rename", (f: TAbstractFile, oldPath: string) => {
                this.maybeScheduleReload(f.path);
                this.maybeScheduleReload(oldPath);
            }),
        );
        // Frontmatter changes (e.g. pipeline-status: pending -> complete)
        // flip how rows render without changing the file list.
        this.registerEvent(
            this.app.metadataCache.on("changed", (f) =>
                this.maybeScheduleReload(f.path),
            ),
        );
    }

    private maybeScheduleReload(path: string): void {
        if (!path.endsWith(".md") || !path.includes("/Meetings/")) return;
        // Only reload if the changed file is inside a configured meeting
        // subfolder. Without org config we trust the /Meetings/ path match
        // alone (scope was already whole-vault).
        if (this.meetingPathPrefixes.length > 0) {
            const inScope = this.meetingPathPrefixes.some(
                (sub) => path.startsWith(sub + "/") || path === sub,
            );
            if (!inScope) return;
        }
        this.scheduleReload();
    }

    private scheduleReload(): void {
        if (this.reloadTimer !== null) window.clearTimeout(this.reloadTimer);
        this.reloadTimer = window.setTimeout(() => {
            this.reloadTimer = null;
            void this.reloadMeetings();
        }, RELOAD_DEBOUNCE_MS);
    }

    /** Reload the meeting list from the vault, preserving the active filter. */
    private async reloadMeetings(): Promise<void> {
        await this.loadMeetings();
        // Rebuild the filter bar so org/company dropdowns reflect any new
        // values that arrived with the reload; per-tab FilterState is kept
        // on the view, so the user's current selections survive.
        this.refreshFilterBar();
        this.renderMeetings();
    }

    /**
     * Render the status row at the top of the panel. Mirrors the pattern
     * used by other Obsidian plugins: a coloured dot, a short state label,
     * and a Start/Stop button whose affordance matches the current state.
     */
    private renderStatusRow(container: HTMLElement): void {
        const row = container.createDiv({ cls: "recap-status-row" });
        this.statusDotEl = row.createEl("span", { cls: "recap-status-dot recap-status-offline" });
        this.statusLabelEl = row.createEl("span", { cls: "recap-status-label", text: "Connecting…" });

        this.actionBtnEl = row.createEl("button", {
            cls: "recap-action-btn",
            text: "Start recording",
        });
        this.actionBtnEl.disabled = true;
        this.actionBtnEl.addEventListener("click", async () => {
            if (!this.actionBtnEl || this.actionBtnEl.disabled) return;
            // Cache the label we clicked on -- currentState may change while
            // the picker modal is up, but the user's intent was tied to the
            // label they saw.
            const wasRecording = this.currentState === "recording";
            this.actionBtnEl.disabled = true;
            try {
                if (wasRecording) {
                    await this.deps.onStopRecording();
                } else {
                    await this.deps.onStartRecording();
                }
            } finally {
                // If state_change hasn't fired yet, re-enable conservatively so
                // the user isn't stuck. The next state_change will overwrite.
                if (this.actionBtnEl) this.actionBtnEl.disabled = false;
            }
        });
    }

    /** Pull daemon status once at open time so the header isn't stuck on "Connecting…". */
    private async refreshDaemonStateFromClient(): Promise<void> {
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
    updateDaemonState(state: string | null, org?: string): void {
        const wasProcessing = this.currentState === "processing";
        const stillProcessing = state === "processing";
        this.currentState = state;
        this.currentOrg = org;

        // Nudge a reload when the pipeline just finished: vault events
        // usually catch the new meeting note, but Obsidian's filesystem
        // watcher can lag on Windows. Belt-and-suspenders -- debounce
        // coalesces this with the vault create event if both fire.
        if (wasProcessing && !stillProcessing) {
            this.scheduleReload();
        }

        if (!this.statusDotEl || !this.statusLabelEl || !this.actionBtnEl) return;

        this.statusDotEl.removeClass(
            "recap-status-ok",
            "recap-status-recording",
            "recap-status-processing",
            "recap-status-offline",
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
                this.statusLabelEl.setText("Processing…");
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
            default: // "idle" and any unknown future state
                this.statusDotEl.addClass("recap-status-ok");
                this.statusLabelEl.setText("Idle");
                this.actionBtnEl.setText("Start recording");
                this.actionBtnEl.disabled = false;
        }
    }

    private async loadMeetings(): Promise<void> {
        this.meetings = [];

        // Ask the daemon which subfolders are actually configured for
        // org meetings; without this we'd have to scan every markdown
        // file in the vault. On failure, degrade to the whole-vault
        // walk with a Notice so the user knows why it's slow.
        let subfolders: string[] = [];
        const client = this.deps.getClient();
        if (client) {
            try {
                const cfg = await client.getConfig();
                subfolders = cfg.orgs
                    .map(o => o.subfolder)
                    .filter((s): s is string => !!s && s.length > 0);
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                new Notice(
                    `Recap: could not load org config \u2014 scanning whole vault. ${msg}`,
                );
                console.error("Recap:", e);
            }
        }

        // Cache the resolved prefixes so vault event handlers can cheaply
        // filter out changes outside the meeting scope.
        this.meetingPathPrefixes = subfolders;

        const allFiles = this.app.vault.getMarkdownFiles();
        const scopedFiles = subfolders.length === 0
            ? allFiles
            : allFiles.filter(f =>
                subfolders.some(
                    sub => f.path.startsWith(sub + "/") || f.path === sub,
                ),
            );

        for (const file of scopedFiles) {
            // Only look at Meetings/ notes inside the scoped folders.
            if (!file.path.includes("/Meetings/")) continue;

            try {
                const cache = this.app.metadataCache.getFileCache(file);
                const frontmatter = cache?.frontmatter;
                if (!frontmatter) continue;

                const eventId = frontmatter["event-id"];
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
                    platform: frontmatter.platform || "",
                    eventId: typeof eventId === "string" ? eventId : undefined,
                });
            } catch (e) {
                console.error(
                    "Recap: could not read meeting frontmatter for",
                    file.path, ":", e,
                );
            }
        }

        // Sorting is now the responsibility of each derive* function in
        // deriveMeetings.ts -- different tabs need different orderings
        // (today chronological, upcoming ascending, past descending).
    }

    private parseParticipants(raw: unknown): string[] {
        if (!Array.isArray(raw)) return [];
        return raw.map((p: string) => p.replace(/\[\[|\]\]/g, ""));
    }

    private refreshFilterBar(): void {
        const orgs = [...new Set(this.meetings.map(m => m.org).filter(Boolean))];
        const companies = [...new Set(
            this.meetings.flatMap(m => m.companies).filter(Boolean),
        )].sort();
        const state = this.filterStates[this.activeTab];
        if (this.filterSlot === null) return;
        this.filterSlot.empty();
        new FilterBar(
            this.filterSlot, this.activeTab, orgs, companies, state,
            (next) => {
                this.filterStates[this.activeTab] = next;
                this.renderMeetings();
            },
        );
    }

    private openMeeting(path: string): void {
        const file = this.app.vault.getAbstractFileByPath(path);
        if (file instanceof TFile) {
            this.app.workspace.getLeaf(false).openFile(file);
        }
    }

    private renderMeetings(): void {
        if (!this.listContainer) return;
        this.listContainer.empty();
        const now = new Date();
        const state = this.filterStates[this.activeTab];

        if (this.activeTab === "today") {
            const { rows, nowDividerIndex } = deriveTodayMeetings(
                this.meetings, now, state,
            );
            this.renderRowsWithDivider(rows, nowDividerIndex, now);
            return;
        }
        const rows = this.activeTab === "upcoming"
            ? deriveUpcomingMeetings(this.meetings, now, state)
            : derivePastMeetings(this.meetings, now, state);
        this.renderRows(rows);
    }

    private renderRows(rows: DecoratedRow[]): void {
        if (!this.listContainer) return;
        if (rows.length === 0) {
            this.listContainer.createDiv({
                text: "No meetings found",
                cls: "recap-empty-state",
            });
            return;
        }
        for (const row of rows) {
            const rowEl = renderMeetingRow(
                this.listContainer, row,
                (path) => this.openMeeting(path),
                { isPast: row.isPast },
            );
            this.attachContextMenu(rowEl, row);
        }
    }

    private renderRowsWithDivider(
        rows: DecoratedRow[],
        nowDividerIndex: number | null,
        now: Date,
    ): void {
        if (!this.listContainer) return;
        if (rows.length === 0) {
            this.listContainer.createDiv({
                text: "No meetings today",
                cls: "recap-empty-state",
            });
            return;
        }
        rows.forEach((row, i) => {
            if (nowDividerIndex !== null && i === nowDividerIndex) {
                renderNowDivider(this.listContainer!, now);
            }
            const rowEl = renderMeetingRow(
                this.listContainer!, row,
                (path) => this.openMeeting(path),
                { isPast: row.isPast },
            );
            this.attachContextMenu(rowEl, row);
        });
    }

    private attachContextMenu(rowEl: HTMLElement, meeting: MeetingData): void {
        if (!meeting.eventId?.startsWith("unscheduled:")) return;
        rowEl.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            const file = this.app.vault.getAbstractFileByPath(meeting.path);
            if (!(file instanceof TFile)) return;
            const menu = new Menu();
            menu.addItem((item) =>
                item.setTitle("Link to calendar event")
                    .setIcon("link")
                    .onClick(() => this.deps.onLinkToCalendar(file)),
            );
            menu.showAtMouseEvent(e);
        });
    }

    async onClose(): Promise<void> {
        this.listContainer = null;
    }
}
