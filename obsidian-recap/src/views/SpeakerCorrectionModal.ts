import { Modal, App, Notice } from "obsidian";
import type { DaemonClient } from "../api";

export interface SpeakerInfo {
    label: string;           // "SPEAKER_00"
    sampleClipPath: string;  // path to a short audio clip
}

export class SpeakerCorrectionModal extends Modal {
    private speakers: SpeakerInfo[];
    private peopleNames: string[];
    private knownContacts: string[];
    private recordingPath: string;
    private org: string;
    private client: DaemonClient;
    private mapping: Record<string, string> = {};

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
            text: "The pipeline couldn't match speakers to names. Listen to a sample and assign names:",
            cls: "setting-item-description",
        });

        // All suggestions (people notes + known contacts, deduplicated)
        const allSuggestions = [...new Set([...this.peopleNames, ...this.knownContacts])].sort();

        for (const speaker of this.speakers) {
            const row = contentEl.createDiv({ cls: "recap-speaker-row" });

            // Speaker label
            row.createSpan({ text: speaker.label, cls: "recap-speaker-label" });

            // Play button
            if (speaker.sampleClipPath) {
                const playBtn = row.createEl("button", { text: "\u25b6", cls: "recap-play-btn" });
                let audio: HTMLAudioElement | null = null;
                playBtn.addEventListener("click", () => {
                    if (audio && !audio.paused) {
                        audio.pause();
                        audio.currentTime = 0;
                        playBtn.setText("\u25b6");
                    } else {
                        audio = new Audio(this.app.vault.adapter.getResourcePath(speaker.sampleClipPath));
                        audio.play();
                        playBtn.setText("\u23f9");
                        audio.addEventListener("ended", () => playBtn.setText("\u25b6"));
                    }
                });
            }

            // Name input with datalist autocomplete
            const datalistId = `recap-suggestions-${speaker.label}`;

            const input = row.createEl("input", {
                type: "text",
                placeholder: "Enter name...",
                cls: "recap-speaker-input",
            });
            input.setAttribute("list", datalistId);
            input.addEventListener("input", () => {
                this.mapping[speaker.label] = input.value;
            });

            // Datalist for autocomplete
            const datalist = row.createEl("datalist");
            datalist.id = datalistId;
            for (const name of allSuggestions) {
                datalist.createEl("option", { value: name });
            }
        }

        // Buttons
        const btnRow = contentEl.createDiv({ cls: "recap-modal-buttons" });

        const cancelBtn = btnRow.createEl("button", { text: "Cancel" });
        cancelBtn.addEventListener("click", () => this.close());

        const applyBtn = btnRow.createEl("button", { text: "Apply & Redo", cls: "mod-cta" });
        applyBtn.addEventListener("click", async () => {
            // Filter out empty mappings
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
                new Notice("Speaker corrections submitted \u2014 reprocessing...");
                this.close();
            } catch (e) {
                new Notice(`Failed to submit corrections: ${e}`);
            }
        });
    }

    onClose(): void {
        this.contentEl.empty();
    }
}
