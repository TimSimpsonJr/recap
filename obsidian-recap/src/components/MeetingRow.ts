import { renderPipelineStatus } from "./PipelineStatus";
import { formatDate } from "../utils/format";

export interface MeetingData {
    path: string;
    title: string;
    date: string;
    time: string;
    org: string;
    duration: string;
    pipelineStatus: string;
    participants: string[];
    companies: string[];
    platform: string;
    eventId?: string;  // optional: undefined when frontmatter has no event-id
}

export function renderMeetingRow(
    container: HTMLElement,
    meeting: MeetingData,
    onClick: (path: string) => void,
    opts?: { isPast?: boolean },
): HTMLElement {
    const row = container.createDiv({ cls: "recap-meeting-row" });
    if (opts?.isPast) {
        row.addClass("recap-meeting-row-past");
    }
    row.addEventListener("click", () => onClick(meeting.path));

    // The Meetings panel lives in Obsidian's right sidebar, which is
    // typically 250-350 px wide. A single-line row crushes the title to a
    // one-letter ellipsis next to the org badge + duration. Stack instead:
    // title gets its own full-width row, metadata sits below in a small
    // dim row so the scan pattern is "title first, details if needed".
    const titleRow = row.createDiv({ cls: "recap-meeting-title-row" });
    titleRow.createSpan({ text: meeting.title, cls: "recap-meeting-title" });

    const metaRow = row.createDiv({ cls: "recap-meeting-meta-row" });
    renderPipelineStatus(metaRow, meeting.pipelineStatus);
    metaRow.createSpan({ text: formatDate(meeting.date), cls: "recap-meeting-date" });
    metaRow.createSpan({ text: meeting.org, cls: "recap-org-badge" });
    if (meeting.duration) {
        metaRow.createSpan({ text: meeting.duration, cls: "recap-meeting-duration" });
    }
    if (meeting.participants.length > 0) {
        metaRow.createSpan({
            text: `${meeting.participants.length} people`,
            cls: "recap-meeting-participants",
        });
    }

    return row;
}
