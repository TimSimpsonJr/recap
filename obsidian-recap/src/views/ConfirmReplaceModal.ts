import { App, Modal } from "obsidian";

export class ConfirmReplaceModal extends Modal {
    private resolvePromise?: (confirmed: boolean) => void;

    constructor(
        app: App,
        private existingRecording: string,
        private newRecording: string,
    ) {
        super(app);
    }

    prompt(): Promise<boolean> {
        return new Promise<boolean>((resolve) => {
            this.resolvePromise = resolve;
            this.open();
        });
    }

    onOpen(): void {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.createEl("h2", { text: "Replace existing recording?" });
        contentEl.createEl("p", {
            text: `Event already has recording "${this.existingRecording}" attached.`,
        });
        contentEl.createEl("p", {
            text: `Replacing will overwrite its note content with pipeline output from "${this.newRecording}". Old recording artifacts on disk are not deleted.`,
        });

        const btnContainer = contentEl.createEl("div", {
            attr: { style: "display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px;" },
        });
        const replaceBtn = btnContainer.createEl("button", {
            text: "Replace",
            cls: "mod-warning",
        });
        const cancelBtn = btnContainer.createEl("button", { text: "Cancel" });

        replaceBtn.onclick = () => {
            this.resolvePromise?.(true);
            this.close();
        };
        cancelBtn.onclick = () => {
            this.resolvePromise?.(false);
            this.close();
        };
    }

    onClose(): void {
        // If closed without a button click, treat as cancel.
        this.resolvePromise?.(false);
        this.resolvePromise = undefined;
        this.contentEl.empty();
    }
}
