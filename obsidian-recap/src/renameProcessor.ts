import { App, TFile } from "obsidian";

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
        try {
            const content = await this.app.vault.adapter.read(this.queuePath);
            const entries: RenameEntry[] = JSON.parse(content);

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
                    console.error(`Recap rename failed: ${entry.old_path} → ${entry.new_path}:`, e);
                    remaining.push(entry); // Keep for retry
                }
            }

            // Write back remaining entries (or delete file if empty)
            if (remaining.length > 0) {
                await this.app.vault.adapter.write(this.queuePath, JSON.stringify(remaining, null, 2));
            } else {
                // Try to remove the queue file
                try {
                    await this.app.vault.adapter.remove(this.queuePath);
                } catch {
                    // File might not exist, that's fine
                }
            }
        } catch {
            // Queue file doesn't exist or can't be read — nothing to process
        }
    }
}
