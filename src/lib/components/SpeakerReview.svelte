<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { settings } from "../stores/settings";
  import { getKnownParticipants, updateSpeakerLabels, retryProcessing } from "../tauri";

  interface Props {
    speakerLabels: Record<string, number>;  // SPEAKER_XX -> utterance count
    calendarParticipants?: string[];
    recordingPath: string;
    onResumed?: () => void;
  }

  let { speakerLabels, calendarParticipants = [], recordingPath, onResumed }: Props = $props();

  let corrections: Record<string, string> = $state({});
  let knownParticipants: string[] = $state([]);
  let loading = $state(false);
  let error: string | null = $state(null);

  // Sort speakers by utterance count descending
  let sortedSpeakers = $derived(
    Object.entries(speakerLabels)
      .sort(([, a], [, b]) => b - a)
      .map(([speaker]) => speaker)
  );

  let speakerCount = $derived(Object.keys(speakerLabels).length);

  // Combined suggestions: calendar first, then known (deduplicated)
  let allSuggestions = $derived.by(() => {
    const seen = new Set<string>();
    const result: { name: string; source: "calendar" | "known" }[] = [];
    for (const name of calendarParticipants) {
      if (!seen.has(name.toLowerCase())) {
        seen.add(name.toLowerCase());
        result.push({ name, source: "calendar" });
      }
    }
    for (const name of knownParticipants) {
      if (!seen.has(name.toLowerCase())) {
        seen.add(name.toLowerCase());
        result.push({ name, source: "known" });
      }
    }
    return result;
  });

  function getRecordingDir(filePath: string): string {
    const lastSep = Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\'));
    return lastSep > 0 ? filePath.substring(0, lastSep) : filePath;
  }

  onMount(async () => {
    try {
      const s = get(settings);
      if (s.recordingsFolder) {
        knownParticipants = await getKnownParticipants(s.recordingsFolder);
      }
    } catch (e) {
      console.error("Failed to load known participants:", e);
    }
  });

  async function applyAndResume() {
    if (loading) return;
    loading = true;
    error = null;
    try {
      const recordingDir = getRecordingDir(recordingPath);
      // Only send non-empty corrections
      const filtered: Record<string, string> = {};
      for (const [speaker, name] of Object.entries(corrections)) {
        if (name.trim()) {
          filtered[speaker] = name.trim();
        }
      }
      if (Object.keys(filtered).length > 0) {
        await updateSpeakerLabels(recordingDir, filtered);
      }
      await retryProcessing(recordingDir, "analyze");
      onResumed?.();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function skipAndResume() {
    if (loading) return;
    loading = true;
    error = null;
    try {
      const recordingDir = getRecordingDir(recordingPath);
      await retryProcessing(recordingDir, "analyze");
      onResumed?.();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
</script>

<div class="speaker-review">
  <!-- Warning banner -->
  <div class="warning-banner">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
    <span>
      {speakerCount} speaker{speakerCount !== 1 ? 's' : ''} could not be identified. Assign names below, or skip to use generic labels.
    </span>
  </div>

  <!-- Speaker mapping rows -->
  <div class="speaker-rows">
    {#each sortedSpeakers as speaker, i (speaker)}
      <div class="speaker-row">
        <span class="speaker-label">{speaker}</span>
        <svg class="arrow" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 8h10M9 4l4 4-4 4" />
        </svg>
        <input
          type="text"
          class="speaker-input"
          list="speaker-suggestions-{i}"
          placeholder="Type or select a name..."
          value={corrections[speaker] ?? ""}
          oninput={(e) => { corrections[speaker] = (e.target as HTMLInputElement).value; }}
        />
        <datalist id="speaker-suggestions-{i}">
          {#if calendarParticipants.length > 0}
            {#each calendarParticipants as name}
              <option value={name} label="{name} (calendar)" />
            {/each}
          {/if}
          {#each knownParticipants as name}
            <option value={name} label="{name} (known)" />
          {/each}
        </datalist>
        <span class="utterance-count">{speakerLabels[speaker]} utterance{speakerLabels[speaker] !== 1 ? 's' : ''}</span>
      </div>
    {/each}
  </div>

  {#if error}
    <div class="error-msg">{error}</div>
  {/if}

  <!-- Action buttons -->
  <div class="action-buttons">
    <button
      class="btn-primary"
      onclick={applyAndResume}
      disabled={loading}
    >
      {loading ? "Applying..." : "Apply & Resume Pipeline"}
    </button>
    <button
      class="btn-secondary"
      onclick={skipAndResume}
      disabled={loading}
    >
      {loading ? "Skipping..." : "Skip \u2014 Use Generic Labels"}
    </button>
  </div>
</div>

<style>
  .speaker-review {
    display: flex;
    flex-direction: column;
    gap: 16px;
    font-family: 'DM Sans', sans-serif;
  }

  .warning-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    border-radius: 8px;
    background: rgba(196, 168, 77, 0.10);
    color: var(--warning);
    font-size: 14px;
    line-height: 1.4;
  }

  .warning-banner svg {
    flex-shrink: 0;
  }

  .speaker-rows {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .speaker-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-radius: 6px;
    background: var(--surface);
  }

  .speaker-label {
    font-size: 13.5px;
    font-weight: 600;
    color: var(--gold);
    white-space: nowrap;
    min-width: 110px;
  }

  .arrow {
    flex-shrink: 0;
    color: var(--text-faint);
  }

  .speaker-input {
    flex: 1;
    min-width: 0;
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    font-size: 13.5px;
    outline: none;
    transition: border-color 120ms ease;
  }

  .speaker-input::placeholder {
    color: var(--text-faint);
  }

  .speaker-input:focus {
    border-color: var(--gold);
  }

  .utterance-count {
    font-size: 12.5px;
    color: var(--text-muted);
    white-space: nowrap;
  }

  .error-msg {
    padding: 8px 12px;
    border-radius: 6px;
    background: rgba(200, 80, 60, 0.10);
    color: var(--red);
    font-size: 13.5px;
  }

  .action-buttons {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }

  .btn-primary {
    padding: 8px 18px;
    border-radius: 6px;
    border: none;
    background: var(--gold);
    color: var(--bg);
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: background 120ms ease;
  }

  .btn-primary:hover:not(:disabled) {
    background: var(--gold-hover);
  }

  .btn-primary:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .btn-secondary {
    padding: 8px 18px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-muted);
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
  }

  .btn-secondary:hover:not(:disabled) {
    background: var(--surface);
    color: var(--text);
    border-color: var(--border-bright);
  }

  .btn-secondary:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
</style>
