export function renderPipelineStatus(container: HTMLElement, status: string): void {
    const dot = container.createSpan({ cls: "recap-pipeline-dot" });
    if (status === "complete") {
        dot.addClass("recap-status-complete");
        dot.setAttribute("aria-label", "Complete");
    } else if (status === "pending") {
        dot.addClass("recap-status-pending");
        dot.setAttribute("aria-label", "Pending");
    } else if (status?.startsWith("failed")) {
        dot.addClass("recap-status-failed");
        dot.setAttribute("aria-label", `Failed: ${status}`);
    } else {
        dot.addClass("recap-status-processing");
        dot.setAttribute("aria-label", status || "Processing");
    }
}
