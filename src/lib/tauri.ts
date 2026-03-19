import { invoke } from "@tauri-apps/api/core";

// OAuth
export async function startOAuth(
  provider: string,
  clientId: string,
  clientSecret: string,
  zohoRegion?: string
): Promise<void> {
  return invoke("start_oauth", { provider, clientId, clientSecret, zohoRegion });
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string | null;
  expires_in: number | null;
  token_type: string | null;
}

export async function exchangeOAuthCode(
  provider: string,
  code: string,
  clientId: string,
  clientSecret: string,
  zohoRegion?: string
): Promise<TokenResponse> {
  return invoke("exchange_oauth_code", { provider, code, clientId, clientSecret, zohoRegion });
}

// Sidecar
export interface SidecarResult {
  success: boolean;
  stdout: string;
  stderr: string;
}

export async function runPipeline(
  configPath: string,
  recordingPath: string,
  metadataPath?: string,
  fromStage?: string
): Promise<SidecarResult> {
  return invoke("run_pipeline", { configPath, recordingPath, metadataPath, fromStage });
}

export async function checkSidecarStatus(): Promise<boolean> {
  return invoke("check_sidecar_status");
}

// Diagnostics
export async function checkNvenc(): Promise<string> {
  return invoke("check_nvenc");
}

export async function checkFfmpeg(): Promise<boolean> {
  return invoke("check_ffmpeg");
}

// Pipeline stage status (matches Rust StageStatus)
export interface PipelineStageStatus {
  completed: boolean;
  timestamp: string | null;
  error: string | null;
  waiting: string | null;
}

// Full pipeline status (matches Rust PipelineStatus)
export interface PipelineStatus {
  merge: PipelineStageStatus;
  frames: PipelineStageStatus;
  transcribe: PipelineStageStatus;
  diarize: PipelineStageStatus;
  analyze: PipelineStageStatus;
  export: PipelineStageStatus;
}

// Meeting summary for list view (matches Rust MeetingSummary)
export interface MeetingSummary {
  id: string;
  title: string;
  date: string;
  platform: string;
  participants: string[];
  company: string | null;
  duration_seconds: number | null;
  pipeline_status: PipelineStatus;
  has_note: boolean;
  has_transcript: boolean;
  has_video: boolean;
  recording_path: string | null;
  note_path: string | null;
}

// A single transcript utterance (matches Rust Utterance)
export interface Utterance {
  speaker: string;
  start: number;
  end: number;
  text: string;
}

// A screenshot with optional caption (matches Rust Screenshot)
export interface Screenshot {
  path: string;
  caption: string | null;
}

// Full meeting detail (matches Rust MeetingDetail)
export interface MeetingDetail {
  summary: MeetingSummary;
  note_content: string | null;
  transcript: Utterance[] | null;
  screenshots: Screenshot[];
}

// Paginated list response (matches Rust MeetingListResponse)
export interface MeetingListResponse {
  items: MeetingSummary[];
  next_cursor: string | null;
}

// Filter options for the sidebar (matches Rust FilterOptions)
export interface FilterOptions {
  companies: string[];
  participants: string[];
  platforms: string[];
}

// Graph types (matches Rust GraphNode, GraphEdge, GraphData)
export interface GraphNode {
  id: string;
  label: string;
  node_type: string; // "meeting", "person", "company"
}

export interface GraphEdge {
  source: string;
  target: string;
  edge_type: string; // "attended", "works_at"
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// Recorder state — discriminated union matching Rust RecorderState
export type RecorderState =
  | "idle"
  | { detected: { process_name: string; pid: number } }
  | "recording"
  | "processing"
  | "declined";

// Meetings IPC
export async function listMeetings(
  recordingsDir: string,
  vaultMeetingsDir?: string,
  cursor?: string,
  limit?: number
): Promise<MeetingListResponse> {
  return invoke("list_meetings", {
    recordingsDir,
    vaultMeetingsDir: vaultMeetingsDir ?? null,
    cursor: cursor ?? null,
    limit: limit ?? null,
  });
}

export async function getMeetingDetail(
  meetingId: string,
  recordingsDir: string,
  vaultMeetingsDir?: string,
  framesDir?: string
): Promise<MeetingDetail> {
  return invoke("get_meeting_detail", {
    meetingId,
    recordingsDir,
    vaultMeetingsDir: vaultMeetingsDir ?? null,
    framesDir: framesDir ?? null,
  });
}

export async function searchMeetings(
  query: string,
  recordingsDir: string,
  vaultMeetingsDir?: string,
  limit?: number
): Promise<MeetingSummary[]> {
  return invoke("search_meetings", {
    query,
    recordingsDir,
    vaultMeetingsDir: vaultMeetingsDir ?? null,
    limit: limit ?? null,
  });
}

// Recorder IPC
export async function getRecorderState(): Promise<RecorderState> {
  return invoke("get_recorder_state");
}

export async function startRecording(): Promise<void> {
  return invoke("start_recording");
}

export async function stopRecording(): Promise<void> {
  return invoke("stop_recording");
}

export async function cancelRecording(): Promise<void> {
  return invoke("cancel_recording");
}

export async function retryProcessing(
  recordingDir: string,
  fromStage?: string
): Promise<void> {
  return invoke("retry_processing", {
    recordingDir,
    fromStage: fromStage ?? null,
  });
}

// Speaker label correction IPC
export async function getKnownParticipants(recordingsDir: string): Promise<string[]> {
  return invoke('get_known_participants', { recordingsDir });
}

export async function updateSpeakerLabels(
  recordingDir: string,
  corrections: Record<string, string>
): Promise<void> {
  return invoke('update_speaker_labels', { recordingDir, corrections });
}

// Filter options IPC
export async function getFilterOptions(
  recordingsDir: string
): Promise<FilterOptions> {
  return invoke("get_filter_options", { recordingsDir });
}

// Graph data IPC
export async function getGraphData(
  recordingsDir: string
): Promise<GraphData> {
  return invoke("get_graph_data", { recordingsDir });
}

// Calendar types (matches Rust CalendarEvent, CalendarParticipant, CalendarCache)
export interface CalendarParticipant {
  name: string;
  email: string | null;
}

export interface CalendarEvent {
  id: string;
  title: string;
  description: string | null;
  start: string;
  end: string;
  participants: CalendarParticipant[];
  location: string | null;
}

export interface CalendarCache {
  events: CalendarEvent[];
  last_synced: string;
}

// Calendar IPC
export async function fetchCalendarEvents(
  startDate: string,
  endDate: string
): Promise<CalendarEvent[]> {
  return invoke("fetch_calendar_events", { startDate, endDate });
}

export async function getUpcomingMeetings(
  hoursAhead: number
): Promise<CalendarEvent[]> {
  return invoke("get_upcoming_meetings", { hoursAhead });
}

export async function syncCalendar(): Promise<CalendarCache> {
  return invoke("sync_calendar");
}

export async function getCalendarLastSynced(): Promise<string | null> {
  return invoke("get_calendar_last_synced");
}

export async function getCalendarMatches(
  recordingsDir: string
): Promise<Record<string, string>> {
  return invoke("get_calendar_matches", { recordingsDir });
}

// Briefing types (matches Rust Briefing, BriefingActionItem)
export interface BriefingActionItem {
  assignee: string;
  description: string;
  from_meeting: string;
}

export interface Briefing {
  topics: string[];
  action_items: BriefingActionItem[];
  context: string;
  relationship_summary: string;
  first_meeting: boolean;
}

// Briefing IPC
export async function generateBriefing(
  eventId: string,
  title: string,
  participants: string[],
  time: string,
  recordingsDir: string,
  vaultMeetingsDir?: string,
  eventDescription?: string
): Promise<Briefing> {
  return invoke("generate_briefing", {
    eventId,
    title,
    participants,
    time,
    recordingsDir,
    vaultMeetingsDir: vaultMeetingsDir ?? null,
    eventDescription: eventDescription ?? null,
  });
}

export async function invalidateBriefingCache(
  participantNames: string[]
): Promise<void> {
  return invoke("invalidate_briefing_cache", { participantNames });
}

// Shared utilities

export function getRecordingDir(filePath: string): string {
  const lastSep = Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\'));
  return lastSep > 0 ? filePath.substring(0, lastSep) : filePath;
}
