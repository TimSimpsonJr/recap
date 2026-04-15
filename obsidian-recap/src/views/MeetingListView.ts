import { ItemView, Notice, WorkspaceLeaf, TFile } from "obsidian";
import type { DaemonClient } from "../api";
import { FilterBar, FilterState } from "../components/FilterBar";
import { MeetingData, renderMeetingRow } from "../components/MeetingRow";

export const VIEW_MEETING_LIST = "recap-meeting-list";

export class MeetingListView extends ItemView {
    private meetings: MeetingData[] = [];
    private filteredMeetings: MeetingData[] = [];
    private listContainer: HTMLElement | null = null;
    private getClient: () => DaemonClient | null;

    constructor(
        leaf: WorkspaceLeaf,
        getClient: () => DaemonClient | null = () => null,
    ) {
        super(leaf);
        this.getClient = getClient;
    }

    getViewType(): string { return VIEW_MEETING_LIST; }
    getDisplayText(): string { return "Recap Meetings"; }
    getIcon(): string { return "mic"; }

    async onOpen(): Promise<void> {
        const container = this.containerEl.children[1] as HTMLElement;
        container.empty();
        container.addClass("recap-meeting-list-container");

        // Header
        container.createEl("h4", { text: "Meetings" });

        // Load meetings from vault
        await this.loadMeetings();

        // Get unique org names from meetings
        const orgs = [...new Set(this.meetings.map(m => m.org).filter(Boolean))];

        // Filter bar
        new FilterBar(container, orgs, (state) => {
            this.applyFilters(state);
        });

        // Meeting list
        this.listContainer = container.createDiv({ cls: "recap-meeting-list" });
        this.renderMeetings();
    }

    private async loadMeetings(): Promise<void> {
        this.meetings = [];

        // Ask the daemon which subfolders are actually configured for
        // org meetings; without this we'd have to scan every markdown
        // file in the vault. On failure, degrade to the whole-vault
        // walk with a Notice so the user knows why it's slow.
        let subfolders: string[] = [];
        const client = this.getClient();
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

                this.meetings.push({
                    path: file.path,
                    title: frontmatter.title || file.basename,
                    date: frontmatter.date || "",
                    org: frontmatter.org || "",
                    duration: frontmatter.duration || "",
                    pipelineStatus: frontmatter["pipeline-status"] || "pending",
                    participants: this.parseParticipants(frontmatter.participants || []),
                    platform: frontmatter.platform || "",
                });
            } catch (e) {
                console.error(
                    "Recap: could not read meeting frontmatter for",
                    file.path, ":", e,
                );
            }
        }

        // Sort by date, newest first
        this.meetings.sort((a, b) => b.date.localeCompare(a.date));
        this.filteredMeetings = [...this.meetings];
    }

    private parseParticipants(raw: unknown): string[] {
        if (!Array.isArray(raw)) return [];
        return raw.map((p: string) => p.replace(/\[\[|\]\]/g, ""));
    }

    private applyFilters(state: FilterState): void {
        this.filteredMeetings = this.meetings.filter(m => {
            if (state.org !== "all" && m.org !== state.org) return false;
            if (state.status !== "all") {
                if (state.status === "failed" && !m.pipelineStatus.startsWith("failed")) return false;
                if (state.status !== "failed" && m.pipelineStatus !== state.status) return false;
            }
            if (state.search) {
                const q = state.search.toLowerCase();
                const searchable = `${m.title} ${m.participants.join(" ")}`.toLowerCase();
                if (!searchable.includes(q)) return false;
            }
            return true;
        });
        this.renderMeetings();
    }

    private renderMeetings(): void {
        if (!this.listContainer) return;
        this.listContainer.empty();

        if (this.filteredMeetings.length === 0) {
            this.listContainer.createDiv({
                text: "No meetings found",
                cls: "recap-empty-state",
            });
            return;
        }

        for (const meeting of this.filteredMeetings) {
            renderMeetingRow(this.listContainer, meeting, (path) => {
                // Open the meeting note
                const file = this.app.vault.getAbstractFileByPath(path);
                if (file instanceof TFile) {
                    this.app.workspace.getLeaf(false).openFile(file);
                }
            });
        }
    }

    async onClose(): Promise<void> {
        this.listContainer = null;
    }
}
