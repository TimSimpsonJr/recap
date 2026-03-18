/**
 * Dummy data for development mode.
 * Controlled by VITE_DUMMY_DATA env var (.env.development).
 * Automatically excluded from production builds.
 */
import type {
  MeetingSummary,
  MeetingDetail,
  PipelineStatus,
  FilterOptions,
  Utterance,
  GraphNode,
  GraphEdge,
} from "./tauri";

export const USE_DUMMY_DATA = import.meta.env.VITE_DUMMY_DATA === "true";

// ---------------------------------------------------------------------------
// Pipeline status helpers
// ---------------------------------------------------------------------------

function doneStatus(): PipelineStatus {
  const done = { completed: true, timestamp: "2026-03-17T10:00:00", error: null };
  return { merge: done, frames: done, transcribe: done, diarize: done, analyze: done, export: done };
}

function failedStatus(stage: string): PipelineStatus {
  const done = { completed: true, timestamp: "2026-03-17T10:00:00", error: null };
  const fail = { completed: false, timestamp: null, error: `${stage} failed: CUDA out of memory` };
  const pending = { completed: false, timestamp: null, error: null };
  const s: any = { merge: done, frames: done, transcribe: done, diarize: done, analyze: done, export: done };
  s[stage] = fail;
  const stages = ["merge", "frames", "transcribe", "diarize", "analyze", "export"];
  const idx = stages.indexOf(stage);
  for (let i = idx + 1; i < stages.length; i++) s[stages[i]] = pending;
  return s;
}

function processingStatus(): PipelineStatus {
  const done = { completed: true, timestamp: "2026-03-17T10:00:00", error: null };
  const pending = { completed: false, timestamp: null, error: null };
  return { merge: done, frames: done, transcribe: pending, diarize: pending, analyze: pending, export: pending };
}

// ---------------------------------------------------------------------------
// Meeting list
// ---------------------------------------------------------------------------

export const DUMMY_MEETINGS: MeetingSummary[] = [
  { id: "2026-03-17-project-kickoff-acme", title: "Project Kickoff with Acme Corp", date: "2026-03-17", platform: "zoom", participants: ["Jane Smith", "Bob Jones", "Alice Chen"], company: "Acme Corp", duration_seconds: 2700, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-17-weekly-standup", title: "Weekly Engineering Standup", date: "2026-03-17", platform: "zoom", participants: ["Tim", "Sarah", "Dev Team", "Mike", "Lisa"], company: null, duration_seconds: 1800, pipeline_status: processingStatus(), has_note: false, has_transcript: false, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-16-quarterly-review", title: "Quarterly Business Review", date: "2026-03-16", platform: "zoom", participants: ["Jane Smith", "Bob Jones", "CFO Team", "Tim", "VP Sales", "Director Ops", "Analyst", "Board Rep"], company: "Acme Corp", duration_seconds: 3600, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-16-client-feedback", title: "Client Feedback Session", date: "2026-03-16", platform: "teams", participants: ["Dave Wilson", "Tim"], company: "Globex Inc", duration_seconds: 1500, pipeline_status: failedStatus("transcribe"), has_note: false, has_transcript: false, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-16-design-sprint-retro", title: "Design Sprint Retro", date: "2026-03-16", platform: "google", participants: ["Sarah", "Mike", "Lisa", "Tim"], company: null, duration_seconds: 2400, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-15-investor-update", title: "Investor Update Call", date: "2026-03-15", platform: "zoom", participants: ["Tim", "Jane Smith", "Investor A"], company: null, duration_seconds: 3000, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-15-1on1-sarah", title: "1:1 with Sarah", date: "2026-03-15", platform: "zoom", participants: ["Tim", "Sarah"], company: null, duration_seconds: 1800, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: false, recording_path: null, note_path: null },
  { id: "2026-03-14-product-planning", title: "Product Planning Session", date: "2026-03-14", platform: "zoho", participants: ["Tim", "Mike", "Lisa", "Product Team"], company: null, duration_seconds: 5400, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: true, recording_path: null, note_path: null },
];

export const DUMMY_FILTER_OPTIONS: FilterOptions = {
  companies: ["Acme Corp", "Globex Inc"],
  participants: [...new Set(DUMMY_MEETINGS.flatMap((m) => m.participants))].sort(),
  platforms: [...new Set(DUMMY_MEETINGS.map((m) => m.platform))].sort(),
};

// ---------------------------------------------------------------------------
// Meeting detail
// ---------------------------------------------------------------------------

const DUMMY_NOTE = `---
date: 2026-03-17
participants:
  - "[[Jane Smith]]"
  - "[[Bob Jones]]"
  - "[[Alice Chen]]"
company: "[[Acme Corp]]"
platform: zoom
duration: 45m
type: client-call
---

## Summary

Kicked off the Q2 infrastructure modernization project with the Acme Corp team. Agreed on a phased approach starting with CI/CD pipeline improvements, followed by container orchestration migration. Budget approved for Phase 1.

## Key Points

- **CI/CD Pipeline:** Current Jenkins setup is causing 40-minute build times. Moving to GitHub Actions with NVENC-accelerated test runners.
- **Container Migration:** Targeting Kubernetes on AWS EKS. [[Jane Smith]] has prior experience from Globex migration.
- **Timeline:** Phase 1 (CI/CD) starts next week, target completion by end of April. Phase 2 (containers) begins May.
- **Budget:** $45K approved for Phase 1 tooling and infrastructure. Phase 2 budget TBD pending Phase 1 results.

## Decisions Made

- GitHub Actions over CircleCI (team familiarity + cost)
- EKS over self-managed K8s (operational overhead concern)
- [[Bob Jones]] will lead the CI/CD migration technical work

## Action Items

- [ ] Tim: Send Phase 1 proposal with detailed timeline by Friday
- [ ] [[Jane Smith]]: Review and share Globex migration runbook
- [ ] [[Bob Jones]]: Set up GitHub Actions proof-of-concept repo
- [ ] [[Alice Chen]]: Compile current build time metrics for baseline

## Follow-up Required

- Need to schedule follow-up with Acme Corp DevOps team for Jenkins audit
- Awaiting AWS account access from Acme IT department

## Relationship Notes

Jane is the key technical decision-maker. Bob defers to her on architecture choices. Alice is new to the team (joined 2 weeks ago) and is ramping up quickly.`;

const DUMMY_TRANSCRIPT: Utterance[] = [
  { speaker: "Tim", start: 0, end: 15, text: "Alright, thanks everyone for joining. Let's kick off the Q2 infrastructure discussion." },
  { speaker: "Jane Smith", start: 16, end: 35, text: "Thanks Tim. We've been looking forward to this. The build times have been killing our velocity." },
  { speaker: "Bob Jones", start: 36, end: 58, text: "Yeah, we're seeing 40-minute builds on average. Some of the integration test suites take even longer. It's really impacting our release cadence." },
  { speaker: "Tim", start: 59, end: 82, text: "That's exactly what we want to address. I've been looking at two options: GitHub Actions and CircleCI. Both support parallel test execution and have good caching." },
  { speaker: "Jane Smith", start: 83, end: 115, text: "I'd vote for GitHub Actions. When I was at Globex, we migrated from Jenkins to Actions and cut our build times by 60%. The team is already familiar with it since our repos are on GitHub." },
  { speaker: "Alice Chen", start: 116, end: 140, text: "I can pull together the current build time metrics so we have a baseline to measure against. I've been looking at our Jenkins dashboards and there's a lot of data there." },
  { speaker: "Tim", start: 141, end: 168, text: "That would be great, Alice. On the container side, we're looking at moving to Kubernetes. Jane, you mentioned you have experience with EKS from the Globex migration?" },
  { speaker: "Jane Smith", start: 169, end: 205, text: "Yes, we ran EKS in production for about two years. I can share our migration runbook. The biggest lesson learned was to invest in proper observability from day one." },
  { speaker: "Bob Jones", start: 206, end: 235, text: "I can set up a proof-of-concept repo for GitHub Actions this week. We should probably start with one of our smaller services to validate the approach." },
  { speaker: "Tim", start: 236, end: 270, text: "Perfect. Let's do Phase 1 on CI/CD first, then tackle containers in Phase 2. I'll send over a detailed proposal with timeline by Friday. Budget-wise, we're looking at about 45K for Phase 1 tooling." },
  { speaker: "Jane Smith", start: 271, end: 295, text: "That sounds reasonable. We'll need to loop in our DevOps team for the Jenkins audit. Can we schedule that for next week?" },
  { speaker: "Tim", start: 296, end: 315, text: "Absolutely. I'll coordinate with your IT department on AWS account access too. Any other questions before we wrap up?" },
  { speaker: "Alice Chen", start: 316, end: 335, text: "Just to confirm, the baseline metrics you want are build times, test suite duration, and deployment frequency?" },
  { speaker: "Tim", start: 336, end: 350, text: "Exactly. And if you can break it down by service, that would be even better. Alright, great meeting everyone. Talk soon." },
];

export function getDummyDetail(id: string): MeetingDetail {
  const titles: Record<string, string> = {
    "2026-03-17-project-kickoff-acme": "Project Kickoff with Acme Corp",
    "2026-03-17-weekly-standup": "Weekly Engineering Standup",
    "2026-03-16-quarterly-review": "Quarterly Business Review",
    "2026-03-16-client-feedback": "Client Feedback Session",
    "2026-03-16-design-sprint-retro": "Design Sprint Retro",
    "2026-03-15-investor-update": "Investor Update Call",
    "2026-03-15-1on1-sarah": "1:1 with Sarah",
    "2026-03-14-product-planning": "Product Planning Session",
  };
  const title = titles[id] || "Meeting";
  const date = id.substring(0, 10);

  return {
    summary: {
      id,
      title,
      date,
      platform: "zoom",
      participants: ["Jane Smith", "Bob Jones", "Alice Chen"],
      company: "Acme Corp",
      duration_seconds: 2700,
      pipeline_status: doneStatus(),
      has_note: true,
      has_transcript: true,
      has_video: false,
      recording_path: null,
      note_path: null,
    },
    note_content: DUMMY_NOTE,
    transcript: DUMMY_TRANSCRIPT,
    screenshots: [],
  };
}

// ---------------------------------------------------------------------------
// Graph data
// ---------------------------------------------------------------------------

export const DUMMY_GRAPH_DATA = {
  nodes: [
    { id: "meeting:2026-03-17-project-kickoff-acme", label: "Project Kickoff", node_type: "meeting" },
    { id: "meeting:2026-03-17-weekly-standup", label: "Weekly Standup", node_type: "meeting" },
    { id: "meeting:2026-03-16-quarterly-review", label: "Q1 Review", node_type: "meeting" },
    { id: "meeting:2026-03-16-design-sprint-retro", label: "Design Retro", node_type: "meeting" },
    { id: "meeting:2026-03-15-investor-update", label: "Investor Update", node_type: "meeting" },
    { id: "meeting:2026-03-15-1on1-sarah", label: "1:1 Sarah", node_type: "meeting" },
    { id: "meeting:2026-03-14-product-planning", label: "Product Planning", node_type: "meeting" },
    { id: "person:jane-smith", label: "Jane Smith", node_type: "person" },
    { id: "person:bob-jones", label: "Bob Jones", node_type: "person" },
    { id: "person:alice-chen", label: "Alice Chen", node_type: "person" },
    { id: "person:tim", label: "Tim", node_type: "person" },
    { id: "person:sarah", label: "Sarah", node_type: "person" },
    { id: "person:mike", label: "Mike", node_type: "person" },
    { id: "person:lisa", label: "Lisa", node_type: "person" },
    { id: "person:dave-wilson", label: "Dave Wilson", node_type: "person" },
    { id: "company:acme", label: "Acme Corp", node_type: "company" },
    { id: "company:globex", label: "Globex Inc", node_type: "company" },
    { id: "company:initech", label: "Initech", node_type: "company" },
  ] as GraphNode[],
  edges: [
    { source: "person:jane-smith", target: "meeting:2026-03-17-project-kickoff-acme", edge_type: "attended" },
    { source: "person:bob-jones", target: "meeting:2026-03-17-project-kickoff-acme", edge_type: "attended" },
    { source: "person:alice-chen", target: "meeting:2026-03-17-project-kickoff-acme", edge_type: "attended" },
    { source: "person:tim", target: "meeting:2026-03-17-weekly-standup", edge_type: "attended" },
    { source: "person:sarah", target: "meeting:2026-03-17-weekly-standup", edge_type: "attended" },
    { source: "person:mike", target: "meeting:2026-03-17-weekly-standup", edge_type: "attended" },
    { source: "person:lisa", target: "meeting:2026-03-17-weekly-standup", edge_type: "attended" },
    { source: "person:jane-smith", target: "meeting:2026-03-16-quarterly-review", edge_type: "attended" },
    { source: "person:bob-jones", target: "meeting:2026-03-16-quarterly-review", edge_type: "attended" },
    { source: "person:tim", target: "meeting:2026-03-16-quarterly-review", edge_type: "attended" },
    { source: "person:sarah", target: "meeting:2026-03-16-design-sprint-retro", edge_type: "attended" },
    { source: "person:mike", target: "meeting:2026-03-16-design-sprint-retro", edge_type: "attended" },
    { source: "person:lisa", target: "meeting:2026-03-16-design-sprint-retro", edge_type: "attended" },
    { source: "person:tim", target: "meeting:2026-03-16-design-sprint-retro", edge_type: "attended" },
    { source: "person:tim", target: "meeting:2026-03-15-investor-update", edge_type: "attended" },
    { source: "person:jane-smith", target: "meeting:2026-03-15-investor-update", edge_type: "attended" },
    { source: "person:dave-wilson", target: "meeting:2026-03-15-investor-update", edge_type: "attended" },
    { source: "person:tim", target: "meeting:2026-03-15-1on1-sarah", edge_type: "attended" },
    { source: "person:sarah", target: "meeting:2026-03-15-1on1-sarah", edge_type: "attended" },
    { source: "person:tim", target: "meeting:2026-03-14-product-planning", edge_type: "attended" },
    { source: "person:mike", target: "meeting:2026-03-14-product-planning", edge_type: "attended" },
    { source: "person:lisa", target: "meeting:2026-03-14-product-planning", edge_type: "attended" },
    { source: "person:jane-smith", target: "company:acme", edge_type: "works_at" },
    { source: "person:bob-jones", target: "company:acme", edge_type: "works_at" },
    { source: "person:alice-chen", target: "company:acme", edge_type: "works_at" },
    { source: "person:dave-wilson", target: "company:globex", edge_type: "works_at" },
    { source: "person:mike", target: "company:initech", edge_type: "works_at" },
  ] as GraphEdge[],
};
