# Test: Verify onblur resetMeetings Issue

## Scenario
1. User is in Settings page
2. User clicks on the Recordings Folder input field
3. User doesn't change the value (just clicks, maybe moves cursor around)
4. User clicks away (blur event fires)

## Current Behavior (Bug)
- `onblur` handler fires: `await saveSetting("recordingsFolder", e.currentTarget.value); await resetMeetings();`
- Even though the value didn't change, `saveSetting` stores same value in Tauri store
- `resetMeetings()` **always** executes regardless
- This triggers:
  - `listMeetings()` IPC call (filesystem scan)
  - `getFilterOptions()` IPC call (filesystem scan)
  - UI resets: meetings.items = [], activeFilters = {}, filterOptions = {}
  - User sees list flash/reload unnecessarily

## Evidence in Code

### RecordingSettings.svelte (line 21)
```
onblur={async (e) => { await saveSetting("recordingsFolder", e.currentTarget.value); await resetMeetings(); }}
```

### VaultSettings.svelte (line 25)
```
onblur={async (e) => { await saveSetting("vaultPath", e.currentTarget.value); await resetMeetings(); }}
```

### resetMeetings() in meetings.ts (lines 264-270)
```
export async function resetMeetings(): Promise<void> {
  meetings.set({ ...initial });
  activeFilters.set({ ...initialFilters });
  filterOptions.set({ companies: [], participants: [], platforms: [] });
  await loadMeetings();      // <-- IPC call 1
  await loadFilterOptions(); // <-- IPC call 2
}
```

## Root Cause
No value comparison before calling `resetMeetings()`. The blur handler always calls it, even if:
- Input value hasn't changed (user just clicked and left)
- Input is empty or same as current setting
- browseRecordingsFolder() already called resetMeetings()

## Impact
- Unnecessary IPC calls across the board
- Visual flashing of meeting list every blur
- Poor UX on settings page
