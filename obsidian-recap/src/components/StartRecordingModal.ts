import { App, Modal, Setting } from "obsidian";

export interface OrgChoice {
    name: string;
    default_backend: string;
}

export interface StartRecordingSelection {
    org: string;
    backend: string;
}

/**
 * Modal shown from the Meetings panel's "Start recording" button. Lets
 * the user pick both the org (destination subfolder) and the analysis
 * backend (Claude vs Ollama) before recording begins. The backend
 * dropdown initialises from the currently-selected org's configured
 * ``default_backend`` so the common case is one click; the user can
 * override per-recording without editing config.
 *
 * Replaces the earlier ``OrgPickerModal`` SuggestModal which only asked
 * for an org. Backend selection previously required going through the
 * Signal popup detection path (see Scenario 2).
 */
export class StartRecordingModal extends Modal {
    private orgs: OrgChoice[];
    private backends: string[];
    private onSubmit: (selection: StartRecordingSelection) => void;
    private selectedOrg: string;
    private selectedBackend: string;
    private backendDropdownEl: HTMLSelectElement | null = null;

    constructor(
        app: App,
        orgs: OrgChoice[],
        backends: string[],
        onSubmit: (selection: StartRecordingSelection) => void,
    ) {
        super(app);
        // Guard against an empty list so opening the modal never throws;
        // fallback mirrors the daemon's /api/config/orgs empty-config
        // behaviour.
        this.orgs = orgs.length > 0
            ? orgs
            : [{ name: "default", default_backend: "claude" }];
        this.backends = backends.length > 0 ? backends : ["claude"];
        this.onSubmit = onSubmit;
        this.selectedOrg = this.orgs[0].name;
        this.selectedBackend = this.orgs[0].default_backend;
    }

    onOpen(): void {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.createEl("h3", { text: "Start recording" });

        new Setting(contentEl)
            .setName("Organization")
            .setDesc("Which org this meeting belongs to.")
            .addDropdown((d) => {
                for (const o of this.orgs) d.addOption(o.name, o.name);
                d.setValue(this.selectedOrg);
                d.onChange((v) => {
                    this.selectedOrg = v;
                    // When the org changes, snap backend to that org's
                    // configured default so switching between orgs doesn't
                    // leave a stale backend selection behind.
                    const match = this.orgs.find((o) => o.name === v);
                    if (match) {
                        this.selectedBackend = match.default_backend;
                        if (this.backendDropdownEl) {
                            this.backendDropdownEl.value = this.selectedBackend;
                        }
                    }
                });
            });

        new Setting(contentEl)
            .setName("Analysis backend")
            .setDesc("Which LLM processes the transcript after recording.")
            .addDropdown((d) => {
                for (const b of this.backends) d.addOption(b, this._label(b));
                d.setValue(this.selectedBackend);
                d.onChange((v) => { this.selectedBackend = v; });
                this.backendDropdownEl = d.selectEl;
            });

        new Setting(contentEl)
            .addButton((b) =>
                b
                    .setButtonText("Start recording")
                    .setCta()
                    .onClick(() => {
                        this.close();
                        this.onSubmit({
                            org: this.selectedOrg,
                            backend: this.selectedBackend,
                        });
                    }),
            )
            .addButton((b) =>
                b.setButtonText("Cancel").onClick(() => this.close()),
            );
    }

    onClose(): void {
        this.contentEl.empty();
    }

    private _label(backend: string): string {
        switch (backend) {
            case "claude": return "Claude";
            case "ollama": return "Ollama";
            default: return backend;
        }
    }
}
