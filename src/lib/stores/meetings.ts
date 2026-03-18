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
