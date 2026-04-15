import { Modal, App, Notice } from "obsidian";
import { DaemonClient, JournalEntry } from "./api";

export interface RecapNotification {
    timestamp: string;
    type: "info" | "warning" | "error";
    title: string;
    message: string;
}

function entryToNotification(entry: JournalEntry): RecapNotification {
    const payload = entry.payload as { title?: string } | undefined;
    const title = payload?.title ?? entry.event.replace(/_/g, " ");
    return { timestamp: entry.ts, type: entry.level, title, message: entry.message };
}

export class NotificationHistory {
    private client: DaemonClient | null = null;
    private cache: RecapNotification[] = [];
    private unsubscribe: (() => void) | null = null;
    private readonly maxSize = 100;
    private listeners: Array<() => void> = [];

    setClient(client: DaemonClient | null): void {
        if (this.unsubscribe) { this.unsubscribe(); this.unsubscribe = null; }
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

    async load(): Promise<void> {
        const client = this.client;
        if (!client) return;
        try {
            const entries = await client.tailEvents(undefined, this.maxSize);
            if (this.client !== client) return; // torn down or swapped; abort
            this.cache = entries.map(entryToNotification);
            this.notifyListeners();
        } catch (e) {
            if (this.client !== client) return; // don't surface errors from stale loads
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: notification history backfill failed — ${msg}`);
            console.error("Recap:", e);
        }
    }

    getAll(): RecapNotification[] { return [...this.cache]; }

    subscribe(callback: () => void): () => void {
        this.listeners.push(callback);
        return () => {
            const idx = this.listeners.indexOf(callback);
            if (idx >= 0) this.listeners.splice(idx, 1);
        };
    }

    detach(): void {
        if (this.unsubscribe) { this.unsubscribe(); this.unsubscribe = null; }
        this.client = null;
        this.cache = [];
        this.notifyListeners();
    }

    private notifyListeners(): void {
        for (const cb of this.listeners) {
            try {
                cb();
            } catch (e) {
                console.error("Recap: notification history listener threw:", e);
            }
        }
    }
}

export class NotificationHistoryModal extends Modal {
    constructor(app: App, private history: NotificationHistory) { super(app); }

    onOpen(): void {
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

    onClose(): void { this.contentEl.empty(); }
}
