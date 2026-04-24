import { Modal, App, Notice } from "obsidian";
import type { DaemonClient, ApiKnownContact, ContactMutation } from "../api";
import {
    resolve,
    type KnownContact,
    type Participant,
    type ResolutionPlan,
} from "../correction/resolve";
import { normalize } from "../correction/normalize";

/** A single speaker the transcript emitted, as returned by
 * ``/api/meetings/{stem}/speakers``. ``speaker_id`` is the stable
 * diarized identity (``SPEAKER_00`` et al.); ``display`` is the
 * current mutable label the pipeline wrote into the transcript
 * (may be ``SPEAKER_00`` if never relabeled, or e.g. ``Sean Mooney``
 * if auto-resolved). */
export interface DaemonSpeaker {
    speaker_id: string;
    display: string;
}

interface SpeakerRow {
    speaker_id: string;
    display: string;
    typedName: string;
    currentPlan: ResolutionPlan;
    hintEl: HTMLElement;
    inputEl: HTMLInputElement;
}

export class SpeakerCorrectionModal extends Modal {
    private speakers: DaemonSpeaker[];
    private peopleNames: string[];
    private companyNames: string[];
    private knownContacts: ApiKnownContact[];
    private meetingParticipants: Participant[];
    private stem: string;
    private org: string;
    private orgSubfolder: string;
    private client: DaemonClient;
    private rows: SpeakerRow[] = [];
    private objectUrls: string[] = [];
    private saveBtn: HTMLButtonElement | null = null;

    constructor(
        app: App,
        speakers: DaemonSpeaker[],
        peopleNames: string[],
        companyNames: string[],
        knownContacts: ApiKnownContact[],
        meetingParticipants: Participant[],
        stem: string,
        org: string,
        orgSubfolder: string,
        client: DaemonClient,
    ) {
        super(app);
        this.speakers = speakers;
        this.peopleNames = peopleNames;
        this.companyNames = companyNames;
        this.knownContacts = knownContacts;
        this.meetingParticipants = meetingParticipants;
        this.stem = stem;
        this.org = org;
        this.orgSubfolder = orgSubfolder;
        this.client = client;
    }

    onOpen(): void {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.addClass("recap-speaker-modal");

        contentEl.createEl("h2", { text: "Identify Speakers" });
        contentEl.createEl("p", {
            text: "Assign a name to each speaker. The plugin will suggest links " +
                "to existing contacts and flag rows that need attention.",
            cls: "setting-item-description",
        });

        // Shared datalist: People notes + known-contact names/aliases.
        const datalist = contentEl.createEl("datalist");
        datalist.id = "recap-known-contacts";
        this.populateContactsDatalist(datalist);

        for (const speaker of this.speakers) {
            this.renderRow(contentEl, speaker);
        }

        const btnRow = contentEl.createDiv({ cls: "recap-modal-buttons" });
        const cancelBtn = btnRow.createEl("button", { text: "Cancel" });
        cancelBtn.addEventListener("click", () => this.close());

        const saveBtn = btnRow.createEl("button", {
            text: "Save & Reprocess", cls: "mod-cta",
        });
        saveBtn.addEventListener("click", () => void this.onSubmit());
        this.saveBtn = saveBtn;
        this.refreshSaveButton();
    }

    private renderRow(parent: HTMLElement, speaker: DaemonSpeaker): void {
        const row = parent.createDiv({ cls: "recap-speaker-row" });

        row.createSpan({
            text: speaker.speaker_id, cls: "recap-speaker-label",
        });

        const audioEl = row.createEl("audio");
        audioEl.controls = true;
        audioEl.preload = "none";
        audioEl.addClass("recap-speaker-audio");
        void this.loadClipInto(audioEl, speaker.speaker_id, row);

        // Seed the input with whatever the pipeline currently shows —
        // a named speaker keeps its name, an unresolved ``SPEAKER_00``
        // arrives blank so the user sees the empty field.
        const initialTyped = /^SPEAKER_\d+$/.test(speaker.display)
            ? "" : speaker.display;
        const input = row.createEl("input", {
            type: "text",
            placeholder: "Enter name...",
            cls: "recap-speaker-input",
            value: initialTyped,
        });
        input.setAttribute("list", "recap-known-contacts");

        const hintEl = row.createDiv({ cls: "recap-speaker-hint" });

        const rowState: SpeakerRow = {
            speaker_id: speaker.speaker_id,
            display: speaker.display,
            typedName: initialTyped,
            currentPlan: this.computePlan(initialTyped),
            hintEl,
            inputEl: input,
        };
        this.rows.push(rowState);

        const rerunPlan = () => {
            rowState.typedName = input.value;
            rowState.currentPlan = this.computePlan(input.value);
            this.renderHint(rowState);
            this.refreshSaveButton();
        };
        input.addEventListener("input", rerunPlan);
        input.addEventListener("blur", rerunPlan);

        this.renderHint(rowState);
    }

    private computePlan(
        typed: string,
        options?: {skipNearMatch?: boolean},
    ): ResolutionPlan {
        // Empty input = nothing to resolve; render as "empty" ineligibility
        // so the save button stays disabled until the user types something.
        if (!typed.trim()) {
            return {kind: "ineligible", reason: "empty", typed};
        }
        const knownContactsForResolve: KnownContact[] =
            this.knownContacts.map(c => ({
                name: c.name,
                display_name: c.display_name ?? c.name,
                aliases: c.aliases,
                email: c.email,
            }));
        return resolve(typed, {
            knownContacts: knownContactsForResolve,
            peopleNames: this.peopleNames,
            companyNames: this.companyNames,
            meetingParticipants: this.meetingParticipants,
        }, options);
    }

    private renderHint(row: SpeakerRow): void {
        row.hintEl.empty();
        row.hintEl.removeClass(
            "recap-speaker-hint-ok",
            "recap-speaker-hint-warn",
            "recap-speaker-hint-error",
        );

        const plan = row.currentPlan;
        switch (plan.kind) {
            case "link_to_existing": {
                row.hintEl.addClass("recap-speaker-hint-ok");
                const suffix = plan.requires_contact_create
                    ? " (will also add contact)"
                    : "";
                row.hintEl.createSpan({
                    text: `Links to ${plan.canonical_name}${suffix}`,
                });
                break;
            }
            case "create_new_contact": {
                row.hintEl.addClass("recap-speaker-hint-ok");
                row.hintEl.createSpan({
                    text: "Will create new contact and People note",
                });
                break;
            }
            case "near_match_ambiguous": {
                row.hintEl.addClass("recap-speaker-hint-warn");
                row.hintEl.createSpan({
                    text: `Did you mean ${plan.suggestion}? `,
                });
                const useBtn = row.hintEl.createEl("button", {
                    text: "Use existing",
                    cls: "recap-hint-btn",
                });
                useBtn.addEventListener("click", () => {
                    row.currentPlan = {
                        kind: "link_to_existing",
                        canonical_name: plan.suggestion,
                        requires_contact_create: false,
                    };
                    // Leave the typed name alone; onSubmit will decide
                    // whether to emit an add_alias mutation based on
                    // typedName vs canonical_name.
                    this.renderHint(row);
                    this.refreshSaveButton();
                });
                const newBtn = row.hintEl.createEl("button", {
                    text: "Create new anyway",
                    cls: "recap-hint-btn",
                });
                newBtn.addEventListener("click", () => {
                    // The user explicitly declined the near-match suggestion.
                    // Re-run resolution with near-match skipped so we still
                    // honor ineligibility guards (company collision,
                    // multi-person form, etc.). The returned plan may be
                    // create_new_contact (accept) or ineligible (surface the
                    // reason inline so the user can correct the typed name).
                    row.currentPlan = this.computePlan(
                        row.typedName, {skipNearMatch: true},
                    );
                    this.renderHint(row);
                    this.refreshSaveButton();
                });
                break;
            }
            case "ineligible": {
                row.hintEl.addClass("recap-speaker-hint-error");
                const label = plan.reason === "empty"
                    ? "Enter a name to continue"
                    : `Rename required: ${plan.reason}`;
                row.hintEl.createSpan({ text: label });
                break;
            }
        }
    }

    private refreshSaveButton(): void {
        if (!this.saveBtn) return;
        const blocked = this.rows.some(r =>
            r.currentPlan.kind === "ineligible"
            || r.currentPlan.kind === "near_match_ambiguous",
        );
        this.saveBtn.disabled = blocked;
    }

    private async onSubmit(): Promise<void> {
        const mapping: Record<string, string> = {};
        const contact_mutations: ContactMutation[] = [];
        for (const row of this.rows) {
            const plan = row.currentPlan;
            if (plan.kind === "link_to_existing") {
                mapping[row.speaker_id] = plan.canonical_name;
                if (plan.requires_contact_create) {
                    const mutation: ContactMutation = {
                        action: "create",
                        name: plan.canonical_name,
                        display_name: plan.canonical_name,
                    };
                    if (plan.email) mutation.email = plan.email;
                    contact_mutations.push(mutation);
                } else if (
                    normalize(row.typedName) !== normalize(plan.canonical_name)
                ) {
                    contact_mutations.push({
                        action: "add_alias",
                        name: plan.canonical_name,
                        alias: row.typedName,
                    });
                }
            } else if (plan.kind === "create_new_contact") {
                mapping[row.speaker_id] = plan.name;
                const mutation: ContactMutation = {
                    action: "create",
                    name: plan.name,
                    display_name: plan.name,
                };
                if (plan.email) mutation.email = plan.email;
                contact_mutations.push(mutation);
            }
            // ineligible / near_match_ambiguous blocked above; never reach here.
        }

        if (Object.keys(mapping).length === 0) {
            new Notice("No speakers assigned");
            return;
        }

        try {
            await this.client.saveSpeakerCorrections({
                stem: this.stem,
                mapping,
                contact_mutations,
                org: this.org,
            });
            new Notice(
                "Speaker corrections submitted \u2014 reprocessing...",
            );
            this.close();
        } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            new Notice(`Recap: submit corrections failed \u2014 ${msg}`);
            console.error("Recap:", e);
        }
    }

    private async populateContactsDatalist(
        datalist: HTMLDataListElement,
    ): Promise<void> {
        const combined = new Set<string>([
            ...this.peopleNames,
        ]);
        for (const c of this.knownContacts) {
            if (c.name) combined.add(c.name);
            if (c.display_name) combined.add(c.display_name);
            for (const alias of c.aliases || []) {
                if (alias) combined.add(alias);
            }
        }
        for (const name of [...combined].sort()) {
            datalist.createEl("option", { value: name });
        }
    }

    private async loadClipInto(
        audioEl: HTMLAudioElement,
        speakerId: string,
        row: HTMLElement,
    ): Promise<void> {
        try {
            const blob = await this.client.fetchSpeakerClip(
                this.stem, speakerId, 5,
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
                "Recap: fetch clip failed for", speakerId, ":", e,
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
        this.rows = [];
        this.saveBtn = null;
        this.contentEl.empty();
    }
}
