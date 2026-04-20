import { Tab } from "../lib/deriveMeetings";

const LABELS: Record<Tab, string> = {
    today: "Today",
    upcoming: "Upcoming",
    past: "Past",
};

const ORDER: Tab[] = ["today", "upcoming", "past"];

export class TabStrip {
    private active: Tab;
    private onChange: (tab: Tab) => void;
    private buttons: Map<Tab, HTMLElement> = new Map();

    constructor(parent: HTMLElement, initial: Tab, onChange: (tab: Tab) => void) {
        this.active = initial;
        this.onChange = onChange;

        const strip = parent.createDiv({ cls: "recap-tab-strip" });
        for (const tab of ORDER) {
            const btn = strip.createDiv({ cls: "recap-tab-button", text: LABELS[tab] });
            if (tab === initial) btn.addClass("is-active");
            btn.addEventListener("click", () => this.setActive(tab));
            this.buttons.set(tab, btn);
        }
    }

    setActive(tab: Tab): void {
        if (tab === this.active) return;
        this.buttons.get(this.active)?.removeClass("is-active");
        this.buttons.get(tab)?.addClass("is-active");
        this.active = tab;
        this.onChange(tab);
    }
}
