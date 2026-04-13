export interface FilterState {
    org: string;       // "all" or specific org name
    status: string;    // "all", "complete", "failed", "pending", "processing"
    search: string;    // free text filter on title/participants
}

export class FilterBar {
    private container: HTMLElement;
    private state: FilterState = { org: "all", status: "all", search: "" };
    private onChange: (state: FilterState) => void;

    constructor(parent: HTMLElement, orgs: string[], onChange: (state: FilterState) => void) {
        this.onChange = onChange;
        this.container = parent.createDiv({ cls: "recap-filter-bar" });
        this.render(orgs);
    }

    private render(orgs: string[]): void {
        // Org dropdown
        const orgSelect = this.container.createEl("select", { cls: "recap-filter-select" });
        orgSelect.createEl("option", { value: "all", text: "All orgs" });
        for (const org of orgs) {
            orgSelect.createEl("option", { value: org, text: org });
        }
        orgSelect.addEventListener("change", () => {
            this.state.org = orgSelect.value;
            this.onChange(this.state);
        });

        // Status dropdown
        const statusSelect = this.container.createEl("select", { cls: "recap-filter-select" });
        for (const [value, label] of [["all", "All status"], ["complete", "Complete"], ["failed", "Failed"], ["pending", "Pending"], ["processing", "Processing"]]) {
            statusSelect.createEl("option", { value, text: label });
        }
        statusSelect.addEventListener("change", () => {
            this.state.status = statusSelect.value;
            this.onChange(this.state);
        });

        // Search input
        const searchInput = this.container.createEl("input", {
            type: "text",
            placeholder: "Search meetings...",
            cls: "recap-filter-search",
        });
        searchInput.addEventListener("input", () => {
            this.state.search = searchInput.value;
            this.onChange(this.state);
        });
    }
}
