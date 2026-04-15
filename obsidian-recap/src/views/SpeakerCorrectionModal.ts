import { Modal, App, Notice } from "obsidian";
import type { DaemonClient } from "../api";

export interface SpeakerInfo {
    label: string;           // "SPEAKER_00"
    sampleClipPath: string;  // path to a short audio clip (legacy; unused)
}

function stemFromRecordingPath(recordingPath: string): string {
    const basename = recordingPath.split(/[/\\]/).pop() || recordingPath;
    return basename.replace(/\.flac$/i, "");
}

export class SpeakerCorrectionModal extends Modal {
    private speakers: SpeakerInfo[];
    private peopleNames: string[];
    private knownContacts: string[];
    private recordingPath: string;
    private org: string;
    private client: DaemonClient;
    private mapping: Record<string, string> = {};
    private objectUrls: string[] = [];

    constructor(
        app: App,
        speakers: SpeakerInfo[],
        peopleNames: string[],
        knownContacts: string[],
        recordingPath: string,
        org: string,
        client: DaemonClient,
    ) {
        super(app);
        this.speakers = speakers;
        this.peopleNames = peopleNames;
        this.knownContacts = knownContacts;
        this.recordingPath = recordingPath;
        this.org = org;
        this.client = client;
    }

    onOpen(): void {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.addClass("recap-speaker-modal");

        contentEl.createEl("h2", { text: "Identify Speakers" });
        contentEl.createEl("p", {
            text: "The pipeline couldn't match speakers to names. Assign a name to each speaker label:",
            cls: "setting-item-description",
        });

        const stem = stemFromRecordingPath(this.recordingPath);

        // Single shared datalist so every row autocompletes against the
        // same name pool (people notes + known contacts, deduplicated).
        const datalist = contentEl.createEl("datalist");
        datalist.id = "recap-known-contacts";
        this.populateContactsDatalist(datalist);

        for (const speaker of this.speakers) {
            const row = contentEl.createDiv({ cls: "recap-speaker-row" });

            row.createSpan({
                text: speaker.label, cls: "recap-speaker-label",
            });

            const audioEl = row.createEl("audio");
            audioEl.controls = true;
            audioEl.preload = "none";
            audioEl.addClass("recap-speaker-audio");
            void this.loadClipInto(audioEl, stem, speaker.label, row);

            const input = row.createEl("input", {
                type: "text",
                placeholder: "Enter name...",
                cls: "recap-speaker-input",
            });
            input.setAttribute("list", "recap-known-contacts");
            input.addEventListener("input", () => {
                this.mapping[speaker.label] = input.value;
            });
        }

        // Buttons
        const btnRow = contentEl.createDiv({ cls: "recap-modal-buttons" });

        const cancelBtn = btnRow.createEl("button", { text: "Cancel" });
        cancelBtn.addEventListener("click", () => this.close());

        const applyBtn = btnRow.createEl("button", {
            text: "Apply & Redo", cls: "mod-cta",
        });
        applyBtn.addEventListener("click", async () => {
            const validMapping: Record<string, string> = {};
            for (const [label, name] of Object.entries(this.mapping)) {
                if (name.trim()) {
                    validMapping[label] = name.trim();
                }
            }

            if (Object.keys(validMapping).length === 0) {
                new Notice("No speakers assigned");
                return;
            }

            try {
                await this.client.submitSpeakerCorrections(
                    this.recordingPath,
                    validMapping,
                    this.org,
                );
                new Notice(
                    "Speaker corrections submitted \u2014 reprocessing...",
                );
                this.close();
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                new Notice(`Recap: submit corrections failed \u2014 ${msg}`);
                console.error("Recap:", e);
            }
        });
    }

    private async populateContactsDatalist(
        datalist: HTMLDataListElement,
    ): Promise<void> {
        // Seed with the props-provided fallback so the datalist has
        // something immediately, even if the /api/config fetch fails
        // or is slow.
        const fallback = [
            ...new Set([...this.peopleNames, ...this.knownContacts]),
        ].sort();
        for (const name of fallback) {
            datalist.createEl("option", { value: name });
        }

        try {
            const cfg = await this.client.getConfig();
            datalist.empty();
            const combined = new Set<string>([
                ...this.peopleNames,
                ...this.knownContacts,
            ]);
            for (const contact of cfg.known_contacts) {
                if (contact.name) combined.add(contact.name);
                if (contact.display_name) combined.add(contact.display_name);
            }
            for (const name of [...combined].sort()) {
                datalist.createEl("option", { value: name });
            }
        } catch (e) {
            // Non-fatal: the fallback list already populated the datalist.
            console.error(
                "Recap: could not load known contacts for autocomplete:", e,
            );
        }
    }

    private async loadClipInto(
        audioEl: HTMLAudioElement,
        stem: string,
        speaker: string,
        row: HTMLElement,
    ): Promise<void> {
        try {
            const blob = await this.client.fetchSpeakerClip(
                stem, speaker, 5,
            );
            const url = URL.createObjectURL(blob);
            this.objectUrls.push(url);
            audioEl.src = url;
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            audioEl.remove();
            row.createSpan({
                text: `(clip unavailable: ${msg})`,
                cls: "recap-speaker-clip-error",
                attr: { style: "opacity: 0.6; font-style: italic;" },
            });
            console.error(
                "Recap: fetch clip failed for", speaker, ":", e,
            );
        }
    }

    onClose(): void {
        for (const url of this.objectUrls) {
            try {
                URL.revokeObjectURL(url);
            } catch (e) {
                console.error("Recap: URL.revokeObjectURL failed:", e);
            }
        }
        this.objectUrls = [];
        this.contentEl.empty();
    }
}
