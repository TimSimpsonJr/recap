import { renderPipelineStatus } from "./PipelineStatus";
import { formatDate } from "../utils/format";

export interface MeetingData {
    path: string;
    title: string;
    date: string;
    org: string;
    duration: string;
    pipelineStatus: string;
    participants: string[];
    platform: string;
}

export function renderMeetingRow(container: HTMLElement, meeting: MeetingData, onClick: (path: string) => void): HTMLElement {
    const row = container.createDiv({ cls: "recap-meeting-row" });
    row.addEventListener("click", () => onClick(meeting.path));

    // Left: pipeline status dot + date + title
    const left = row.createDiv({ cls: "recap-meeting-left" });
    renderPipelineStatus(left, meeting.pipelineStatus);
    left.createSpan({ text: formatDate(meeting.date), cls: "recap-meeting-date" });
    left.createSpan({ text: meeting.title, cls: "recap-meeting-title" });

    // Right: org badge + duration + participant count
    const right = row.createDiv({ cls: "recap-meeting-right" });
    right.createSpan({ text: meeting.org, cls: "recap-org-badge" });
    if (meeting.duration) {
        right.createSpan({ text: meeting.duration, cls: "recap-meeting-duration" });
    }
    if (meeting.participants.length > 0) {
        right.createSpan({ text: `${meeting.participants.length} people`, cls: "recap-meeting-participants" });
    }

    return row;
}
