import { Modal, App } from "obsidian";

export interface RecapNotification {
    timestamp: string;
    type: "info" | "warning" | "error";
    title: string;
    message: string;
}

export class NotificationHistory {
    private notifications: RecapNotification[] = [];
    private maxSize = 100;

    add(type: RecapNotification["type"], title: string, message: string): void {
        this.notifications.unshift({
            timestamp: new Date().toISOString(),
            type,
            title,
            message,
        });
        if (this.notifications.length > this.maxSize) {
            this.notifications.pop();
        }
    }

    getAll(): RecapNotification[] {
        return [...this.notifications];
    }

    clear(): void {
        this.notifications = [];
    }

    get count(): number {
        return this.notifications.length;
    }
}

export class NotificationHistoryModal extends Modal {
    private history: NotificationHistory;

    constructor(app: App, history: NotificationHistory) {
        super(app);
        this.history = history;
    }

    onOpen(): void {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.addClass("recap-notification-modal");

        contentEl.createEl("h2", { text: "Notification History" });

        const notifications = this.history.getAll();

        if (notifications.length === 0) {
            contentEl.createEl("p", { text: "No notifications yet.", cls: "recap-empty-state" });
            return;
        }

        const list = contentEl.createDiv({ cls: "recap-notification-list" });

        for (const n of notifications) {
            const row = list.createDiv({ cls: `recap-notification-row recap-notification-${n.type}` });
            const header = row.createDiv({ cls: "recap-notification-header" });

            // Type icon
            const icon = n.type === "error" ? "✕" : n.type === "warning" ? "⚠" : "ℹ";
            header.createSpan({ text: icon, cls: "recap-notification-icon" });
            header.createSpan({ text: n.title, cls: "recap-notification-title" });
            header.createSpan({
                text: new Date(n.timestamp).toLocaleString(),
                cls: "recap-notification-time",
            });

            row.createDiv({ text: n.message, cls: "recap-notification-message" });
        }

        // Clear button
        const footer = contentEl.createDiv({ cls: "recap-modal-buttons" });
        const clearBtn = footer.createEl("button", { text: "Clear All" });
        clearBtn.addEventListener("click", () => {
            this.history.clear();
            this.onOpen(); // Re-render
        });
    }

    onClose(): void {
        this.contentEl.empty();
    }
}
