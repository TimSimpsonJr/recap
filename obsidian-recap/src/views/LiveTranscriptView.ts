import { ItemView, WorkspaceLeaf } from "obsidian";

export const VIEW_LIVE_TRANSCRIPT = "recap-live-transcript";

export class LiveTranscriptView extends ItemView {
    private transcriptEl: HTMLElement | null = null;
    private statusEl: HTMLElement | null = null;
    private getStatus: (() => Promise<string | null>) | null;

    constructor(leaf: WorkspaceLeaf, getStatus?: () => Promise<string | null>) {
        super(leaf);
        this.getStatus = getStatus ?? null;
    }

    getViewType(): string { return VIEW_LIVE_TRANSCRIPT; }
    getDisplayText(): string { return "Live Transcript"; }
    getIcon(): string { return "scroll-text"; }

    async onOpen(): Promise<void> {
        const container = this.containerEl.children[1] as HTMLElement;
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

    updateStatus(state: string): void {
        if (!this.statusEl) return;
        this.statusEl.empty();
        switch (state) {
            case "recording":
                this.statusEl.setText("⏺ Recording — transcript will appear in the meeting note after the pipeline completes.");
                this.statusEl.addClass("recap-recording");
                break;
            default:
                this.statusEl.setText("Live transcript is not available in this version. Recorded meetings will show the full transcript in the note after the pipeline completes.");
                this.statusEl.removeClass("recap-recording");
        }
    }

    appendUtterance(speaker: string, text: string): void {
        if (!this.transcriptEl) return;
        const line = this.transcriptEl.createDiv({ cls: "recap-utterance" });
        line.createSpan({ text: `${speaker}: `, cls: "recap-utterance-speaker" });
        line.createSpan({ text });
        // Auto-scroll to bottom
        this.transcriptEl.scrollTop = this.transcriptEl.scrollHeight;
    }

    clear(): void {
        if (this.transcriptEl) {
            this.transcriptEl.empty();
        }
    }

    async onClose(): Promise<void> {
        this.transcriptEl = null;
        this.statusEl = null;
    }
}
