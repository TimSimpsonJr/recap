import { writable, get, derived } from "svelte/store";
import { listen } from "@tauri-apps/api/event";
import { settings } from "./settings";
import {
  listMeetings,
  searchMeetings,
  getFilterOptions,
  type MeetingSummary,
  type FilterOptions,
} from "../tauri";

export interface MeetingsState {
  items: MeetingSummary[];
  nextCursor: string | null;
  loading: boolean;
  error: string | null;
  searchQuery: string;
}

const initial: MeetingsState = {
  items: [],
  nextCursor: null,
  loading: false,
  error: null,
  searchQuery: "",
};

export const meetings = writable<MeetingsState>({ ...initial });

// ---------------------------------------------------------------------------
// Filter state
// ---------------------------------------------------------------------------

export interface ActiveFilters {
  companies: string[];
  participants: string[];
  platforms: string[];
}

const initialFilters: ActiveFilters = {
  companies: [],
  participants: [],
  platforms: [],
};

export const activeFilters = writable<ActiveFilters>({ ...initialFilters });
export const filterOptions = writable<FilterOptions>({
  companies: [],
  participants: [],
  platforms: [],
});

export async function loadFilterOptions(): Promise<void> {
  // In dummy mode, filter options are set by loadMeetings()
  if (DUMMY_DATA) return;

  const s = get(settings);
  const recordingsDir = s.recordingsFolder;
  if (!recordingsDir) return;

  try {
    const options = await getFilterOptions(recordingsDir);
    filterOptions.set(options);
  } catch (e) {
    console.error("Failed to load filter options:", e);
  }
}

export function clearAllFilters(): void {
  activeFilters.set({ ...initialFilters });
}

export function toggleFilter(
  category: keyof ActiveFilters,
  value: string
): void {
  activeFilters.update((f) => {
    const current = f[category];
    const idx = current.indexOf(value);
    if (idx >= 0) {
      return { ...f, [category]: current.filter((v) => v !== value) };
    } else {
      return { ...f, [category]: [...current, value] };
    }
  });
}

/** Apply active filters to a list of meetings (client-side). */
export function applyFilters(
  items: MeetingSummary[],
  filters: ActiveFilters
): MeetingSummary[] {
  return items.filter((m) => {
    if (
      filters.platforms.length > 0 &&
      !filters.platforms.includes(m.platform)
    ) {
      return false;
    }
    if (
      filters.participants.length > 0 &&
      !m.participants.some((p) => filters.participants.includes(p))
    ) {
      return false;
    }
    // Company filter: we don't have company on MeetingSummary, so skip for now.
    // In future, if company is added to MeetingSummary, filter here.
    return true;
  });
}

/** Derived store that applies active filters to the meetings list. */
export const filteredMeetings = derived(
  [meetings, activeFilters],
  ([$meetings, $activeFilters]) => {
    const hasFilters =
      $activeFilters.companies.length > 0 ||
      $activeFilters.participants.length > 0 ||
      $activeFilters.platforms.length > 0;

    if (!hasFilters) {
      return $meetings;
    }

    return {
      ...$meetings,
      items: applyFilters($meetings.items, $activeFilters),
    };
  }
);

// ---------------------------------------------------------------------------

function getPaths(): { recordingsDir: string; vaultMeetingsDir: string | undefined } {
  const s = get(settings);
  const recordingsDir = s.recordingsFolder;
  const vaultMeetingsDir =
    s.vaultPath && s.meetingsFolder
      ? `${s.vaultPath}/${s.meetingsFolder}`
      : undefined;
  return { recordingsDir, vaultMeetingsDir };
}

// ── DUMMY DATA (remove before PR) ──────────────────────────────────────────
const DUMMY_DATA = true; // flip to false to use real IPC

function doneStatus(): import("../tauri").PipelineStatus {
  const done = { completed: true, timestamp: "2026-03-17T10:00:00", error: null };
  return { merge: done, frames: done, transcribe: done, diarize: done, analyze: done, export: done };
}
function failedStatus(stage: string): import("../tauri").PipelineStatus {
  const done = { completed: true, timestamp: "2026-03-17T10:00:00", error: null };
  const fail = { completed: false, timestamp: null, error: `${stage} failed: CUDA out of memory` };
  const pending = { completed: false, timestamp: null, error: null };
  const s = { merge: done, frames: done, transcribe: done, diarize: done, analyze: done, export: done };
  (s as any)[stage] = fail;
  // Mark subsequent stages as pending
  const stages = ["merge", "frames", "transcribe", "diarize", "analyze", "export"];
  const idx = stages.indexOf(stage);
  for (let i = idx + 1; i < stages.length; i++) (s as any)[stages[i]] = pending;
  return s;
}
function processingStatus(): import("../tauri").PipelineStatus {
  const done = { completed: true, timestamp: "2026-03-17T10:00:00", error: null };
  const pending = { completed: false, timestamp: null, error: null };
  return { merge: done, frames: done, transcribe: pending, diarize: pending, analyze: pending, export: pending };
}
const DUMMY_MEETINGS: import("../tauri").MeetingSummary[] = [
  { id: "2026-03-17-project-kickoff-acme", title: "Project Kickoff with Acme Corp", date: "2026-03-17", platform: "zoom", participants: ["Jane Smith", "Bob Jones", "Alice Chen"], duration_seconds: 2700, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-17-weekly-standup", title: "Weekly Engineering Standup", date: "2026-03-17", platform: "zoom", participants: ["Tim", "Sarah", "Dev Team", "Mike", "Lisa"], duration_seconds: 1800, pipeline_status: processingStatus(), has_note: false, has_transcript: false, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-16-quarterly-review", title: "Quarterly Business Review", date: "2026-03-16", platform: "zoom", participants: ["Jane Smith", "Bob Jones", "CFO Team", "Tim", "VP Sales", "Director Ops", "Analyst", "Board Rep"], duration_seconds: 3600, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-16-client-feedback", title: "Client Feedback Session", date: "2026-03-16", platform: "teams", participants: ["Dave Wilson", "Tim"], duration_seconds: 1500, pipeline_status: failedStatus("transcribe"), has_note: false, has_transcript: false, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-16-design-sprint-retro", title: "Design Sprint Retro", date: "2026-03-16", platform: "google", participants: ["Sarah", "Mike", "Lisa", "Tim"], duration_seconds: 2400, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-15-investor-update", title: "Investor Update Call", date: "2026-03-15", platform: "zoom", participants: ["Tim", "Jane Smith", "Investor A"], duration_seconds: 3000, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: true, recording_path: null, note_path: null },
  { id: "2026-03-15-1on1-sarah", title: "1:1 with Sarah", date: "2026-03-15", platform: "zoom", participants: ["Tim", "Sarah"], duration_seconds: 1800, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: false, recording_path: null, note_path: null },
  { id: "2026-03-14-product-planning", title: "Product Planning Session", date: "2026-03-14", platform: "zoho", participants: ["Tim", "Mike", "Lisa", "Product Team"], duration_seconds: 5400, pipeline_status: doneStatus(), has_note: true, has_transcript: true, has_video: true, recording_path: null, note_path: null },
];
// ── END DUMMY DATA ─────────────────────────────────────────────────────────

/** Load the first page of meetings, replacing existing state. */
export async function loadMeetings(): Promise<void> {
  // ── DUMMY MODE (remove before PR) ──
  if (DUMMY_DATA) {
    meetings.set({
      items: DUMMY_MEETINGS,
      nextCursor: null,
      loading: false,
      error: null,
      searchQuery: "",
    });
    filterOptions.set({
      companies: ["Acme Corp", "Globex Inc"],
      participants: [...new Set(DUMMY_MEETINGS.flatMap((m) => m.participants))].sort(),
      platforms: [...new Set(DUMMY_MEETINGS.map((m) => m.platform))].sort(),
    });
    return;
  }
  // ── END DUMMY MODE ──

  const { recordingsDir, vaultMeetingsDir } = getPaths();
  if (!recordingsDir) {
    meetings.set({ ...initial, error: "No recordings folder configured" });
    return;
  }

  meetings.update((s) => ({ ...s, loading: true, error: null }));

  try {
    const result = await listMeetings(recordingsDir, vaultMeetingsDir);
    meetings.set({
      items: result.items,
      nextCursor: result.next_cursor,
      loading: false,
      error: null,
      searchQuery: "",
    });
  } catch (e) {
    meetings.update((s) => ({
      ...s,
      loading: false,
      error: e instanceof Error ? e.message : String(e),
    }));
  }
}

/** Load the next page and append to existing items. */
export async function loadMore(): Promise<void> {
  const current = get(meetings);
  if (!current.nextCursor || current.loading) return;

  const { recordingsDir, vaultMeetingsDir } = getPaths();
  if (!recordingsDir) return;

  meetings.update((s) => ({ ...s, loading: true }));

  try {
    const result = await listMeetings(
      recordingsDir,
      vaultMeetingsDir,
      current.nextCursor
    );
    meetings.update((s) => ({
      ...s,
      items: [...s.items, ...result.items],
      nextCursor: result.next_cursor,
      loading: false,
    }));
  } catch (e) {
    meetings.update((s) => ({
      ...s,
      loading: false,
      error: e instanceof Error ? e.message : String(e),
    }));
  }
}

/** Search meetings by query string. */
export async function search(query: string): Promise<void> {
  const { recordingsDir, vaultMeetingsDir } = getPaths();
  if (!recordingsDir) return;

  meetings.update((s) => ({ ...s, loading: true, error: null, searchQuery: query }));

  try {
    const results = await searchMeetings(query, recordingsDir, vaultMeetingsDir);
    meetings.update((s) => ({
      ...s,
      items: results,
      nextCursor: null,
      loading: false,
    }));
  } catch (e) {
    meetings.update((s) => ({
      ...s,
      loading: false,
      error: e instanceof Error ? e.message : String(e),
    }));
  }
}

/** Clear search and reload the full list. */
export async function clearSearch(): Promise<void> {
  await loadMeetings();
}

/** Listen for pipeline-completed events and refresh the list. */
let unlistenPipeline: (() => void) | null = null;

export async function initMeetingsListener(): Promise<void> {
  if (unlistenPipeline) return;
  unlistenPipeline = await listen("pipeline-completed", () => {
    const current = get(meetings);
    if (current.searchQuery) {
      search(current.searchQuery);
    } else {
      loadMeetings();
    }
  });
}

export function destroyMeetingsListener(): void {
  if (unlistenPipeline) {
    unlistenPipeline();
    unlistenPipeline = null;
  }
}
