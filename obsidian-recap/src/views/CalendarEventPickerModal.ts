import { App, SuggestModal } from "obsidian";

export interface CalendarEventCandidate {
    event_id: string;
    title: string;
    date: string;
    time: string;
    calendar_source: string;
    note_path: string;
}

export class CalendarEventPickerModal extends SuggestModal<CalendarEventCandidate> {
    constructor(
        app: App,
        private candidates: CalendarEventCandidate[],
        private onPick: (picked: CalendarEventCandidate) => void | Promise<void>,
    ) {
        super(app);
        this.setPlaceholder("Type to filter calendar events...");
    }

    getSuggestions(query: string): CalendarEventCandidate[] {
        const q = query.toLowerCase();
        if (!q) return this.candidates;
        return this.candidates.filter(c =>
            c.title.toLowerCase().includes(q)
            || c.date.includes(q)
            || c.calendar_source.toLowerCase().includes(q),
        );
    }

    renderSuggestion(c: CalendarEventCandidate, el: HTMLElement): void {
        const parts = [c.title, c.date, c.time, c.calendar_source]
            .filter(Boolean)
            .join(" -- ");
        el.createEl("div", { text: parts });
    }

    onChooseSuggestion(c: CalendarEventCandidate): void {
        void this.onPick(c);
    }
}
