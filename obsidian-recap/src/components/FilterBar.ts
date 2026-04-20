import type { Tab } from "../lib/deriveMeetings";

export interface FilterState {
    org: string;       // "all" or specific org name
    status: string;    // "all", "complete", "failed", "pending", "processing"
    company: string;   // "all" or specific company name
    search: string;    // free text filter on title/participants
}

export const EMPTY_FILTER_STATE: FilterState = {
    org: "all",
    status: "all",
    company: "all",
    search: "",
};

export class FilterBar {
    private container: HTMLElement;
    private tabMode: Tab;
    private orgs: string[];
    private companies: string[];
    private state: FilterState;
    private onChange: (state: FilterState) => void;

    constructor(
        parent: HTMLElement,
        tabMode: Tab,
        orgs: string[],
        companies: string[],
        initialState: FilterState,
        onChange: (state: FilterState) => void,
    ) {
        this.container = parent.createDiv({ cls: "recap-filter-bar" });
        this.tabMode = tabMode;
        this.orgs = orgs;
        this.companies = companies;
        this.state = { ...initialState };
        this.onChange = onChange;
        this.render();
    }

    public setTabMode(
        tab: Tab,
        state: FilterState,
        orgs: string[],
        companies: string[],
    ): void {
        this.tabMode = tab;
        this.state = { ...state };
        this.orgs = orgs;
        this.companies = companies;
        this.render();
    }

    private render(): void {
        this.container.empty();

        if (this.tabMode === "upcoming" || this.tabMode === "past") {
            this.renderOrgSelect();
        }

        if (this.tabMode === "past") {
            this.renderCompanySelect();
            this.renderStatusSelect();
        }

        this.renderSearchInput();
    }

    private renderOrgSelect(): void {
        const orgSelect = this.container.createEl("select", { cls: "recap-filter-select" });
        orgSelect.createEl("option", { value: "all", text: "All orgs" });
        for (const org of this.orgs) {
            orgSelect.createEl("option", { value: org, text: org });
        }
        orgSelect.value = this.state.org;
        orgSelect.addEventListener("change", () => {
            this.state.org = orgSelect.value;
            this.onChange(this.state);
        });
    }

    private renderCompanySelect(): void {
        const companySelect = this.container.createEl("select", { cls: "recap-filter-select" });
        companySelect.createEl("option", { value: "all", text: "All companies" });
        for (const company of this.companies) {
            companySelect.createEl("option", { value: company, text: company });
        }
        companySelect.value = this.state.company;
        companySelect.addEventListener("change", () => {
            this.state.company = companySelect.value;
            this.onChange(this.state);
        });
    }

    private renderStatusSelect(): void {
        const statusSelect = this.container.createEl("select", { cls: "recap-filter-select" });
        const options: Array<[string, string]> = [
            ["all", "All status"],
            ["complete", "Complete"],
            ["failed", "Failed"],
            ["pending", "Pending"],
            ["processing", "Processing"],
        ];
        for (const [value, label] of options) {
            statusSelect.createEl("option", { value, text: label });
        }
        statusSelect.value = this.state.status;
        statusSelect.addEventListener("change", () => {
            this.state.status = statusSelect.value;
            this.onChange(this.state);
        });
    }

    private renderSearchInput(): void {
        const searchInput = this.container.createEl("input", {
            type: "text",
            placeholder: "Search meetings...",
            cls: "recap-filter-search",
        });
        searchInput.value = this.state.search;
        searchInput.addEventListener("input", () => {
            this.state.search = searchInput.value;
            this.onChange(this.state);
        });
    }
}
