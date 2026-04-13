/**
 * Status bar component showing daemon connection state and recording status.
 */
export class RecapStatusBar {
    private el: HTMLElement;

    constructor(statusBarEl: HTMLElement) {
        this.el = statusBarEl;
        this.el.addClass("recap-status-bar");
    }

    updateState(state: string, org?: string): void {
        this.el.empty();
        switch (state) {
            case "recording":
                this.el.setText(`⏺ Recording (${org || ""})`);
                this.el.addClass("recap-recording");
                this.el.removeClass("recap-offline", "recap-processing");
                break;
            case "processing":
                this.el.setText("⚙ Processing...");
                this.el.addClass("recap-processing");
                this.el.removeClass("recap-recording", "recap-offline");
                break;
            case "armed":
                this.el.setText("◉ Armed");
                this.el.removeClass("recap-recording", "recap-offline", "recap-processing");
                break;
            default:
                this.el.setText("");
                this.el.removeClass("recap-recording", "recap-offline", "recap-processing");
        }
    }

    setOffline(): void {
        this.el.setText("⚠ Daemon offline");
        this.el.addClass("recap-offline");
        this.el.removeClass("recap-recording", "recap-processing");
    }

    setConnected(): void {
        // Only clear offline state, don't change recording state
        if (this.el.hasClass("recap-offline")) {
            this.el.setText("");
            this.el.removeClass("recap-offline");
        }
    }
}
