import { writable, get } from "svelte/store";
import { listen } from "@tauri-apps/api/event";
import { settings } from "./settings";
import {
  listMeetings,
  searchMeetings,
  type MeetingSummary,
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

function getPaths(): { recordingsDir: string; vaultMeetingsDir: string | undefined } {
  const s = get(settings);
  const recordingsDir = s.recordingsFolder;
  const vaultMeetingsDir =
    s.vaultPath && s.meetingsFolder
      ? `${s.vaultPath}/${s.meetingsFolder}`
      : undefined;
  return { recordingsDir, vaultMeetingsDir };
}

/** Load the first page of meetings, replacing existing state. */
export async function loadMeetings(): Promise<void> {
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
