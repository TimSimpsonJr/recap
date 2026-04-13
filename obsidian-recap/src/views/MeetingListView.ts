import { ItemView, WorkspaceLeaf, TFile } from "obsidian";
import { FilterBar, FilterState } from "../components/FilterBar";
import { MeetingData, renderMeetingRow } from "../components/MeetingRow";

export const VIEW_MEETING_LIST = "recap-meeting-list";

export class MeetingListView extends ItemView {
    private meetings: MeetingData[] = [];
    private filteredMeetings: MeetingData[] = [];
    private listContainer: HTMLElement | null = null;

    constructor(leaf: WorkspaceLeaf) {
        super(leaf);
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
        const files = this.app.vault.getMarkdownFiles();

        for (const file of files) {
            // Only look in _Recap/*/Meetings/ folders
            if (!file.path.startsWith("_Recap/") || !file.path.includes("/Meetings/")) continue;

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
            } catch {
                // Skip files we can't parse
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
