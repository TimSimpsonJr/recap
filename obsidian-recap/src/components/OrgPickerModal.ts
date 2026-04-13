import { SuggestModal, App } from "obsidian";

export class OrgPickerModal extends SuggestModal<string> {
    private orgs: string[];
    private onSelect: (org: string) => void;

    constructor(app: App, orgs: string[], onSelect: (org: string) => void) {
        super(app);
        this.orgs = orgs;
        this.onSelect = onSelect;
        this.setPlaceholder("Select organization...");
    }

    getSuggestions(query: string): string[] {
        return this.orgs.filter(org =>
            org.toLowerCase().includes(query.toLowerCase())
        );
    }

    renderSuggestion(org: string, el: HTMLElement): void {
        el.createEl("div", { text: org });
    }

    onChooseSuggestion(org: string): void {
        this.onSelect(org);
    }
}
