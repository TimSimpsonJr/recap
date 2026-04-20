// Renders a "Now · HH:MM" divider row used to separate past meetings from
// upcoming ones in the Meetings list. The time is zero-padded local time.
export function renderNowDivider(container: HTMLElement, now: Date = new Date()): HTMLElement {
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    return container.createDiv({
        cls: "recap-now-divider",
        text: `Now · ${hh}:${mm}`,
    });
}
