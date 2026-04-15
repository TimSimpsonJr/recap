import { App, Notice, TFile } from "obsidian";

interface RenameEntry {
    old_path: string;
    new_path: string;
}

export class RenameProcessor {
    private app: App;
    private queuePath: string;

    constructor(app: App, queuePath: string) {
        this.app = app;
        this.queuePath = queuePath;
    }

    async processQueue(): Promise<void> {
        const queueExists = await this.app.vault.adapter.exists(this.queuePath);
        if (!queueExists) return;

        let entries: RenameEntry[];
        try {
            const content = await this.app.vault.adapter.read(this.queuePath);
            entries = JSON.parse(content);
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: rename queue read failed — ${msg}`);
            console.error("Recap:", e);
            return;
        }

        if (!Array.isArray(entries) || entries.length === 0) return;

        const remaining: RenameEntry[] = [];

        for (const entry of entries) {
            try {
                const file = this.app.vault.getAbstractFileByPath(entry.old_path);
                if (file instanceof TFile) {
                    await this.app.fileManager.renameFile(file, entry.new_path);
                    // fileManager.renameFile updates all wikilinks automatically
                } else {
                    // File not found — maybe already renamed or deleted
                    console.warn(`Recap rename: file not found: ${entry.old_path}`);
                }
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                new Notice(
                    `Recap: rename ${entry.old_path} \u2192 ${entry.new_path} failed \u2014 ${msg}`,
                );
                console.error("Recap:", e);
                remaining.push(entry); // Keep for retry
            }
        }

        // Write back remaining entries (or delete file if empty)
        if (remaining.length > 0) {
            try {
                await this.app.vault.adapter.write(
                    this.queuePath,
                    JSON.stringify(remaining, null, 2),
                );
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                new Notice(`Recap: could not persist rename queue retries \u2014 ${msg}`);
                console.error("Recap:", e);
            }
        } else {
            try {
                await this.app.vault.adapter.remove(this.queuePath);
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                new Notice(`Recap: could not remove empty rename queue \u2014 ${msg}`);
                console.error("Recap:", e);
            }
        }
    }
}
