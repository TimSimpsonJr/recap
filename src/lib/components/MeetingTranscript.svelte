<script lang="ts">
  import type { Utterance } from "../tauri";

  interface Props {
    utterances: Utterance[] | null;
    onSeek?: (time: number) => void;
  }

  let { utterances, onSeek }: Props = $props();

  const speakerColors = [
    "#C4A84D", "#5e9e96", "#8e6e9e", "#9e826e",
    "#6e829e", "#9e6e7e", "#7e9e6e", "#9e9e6e",
  ];

  function getSpeakerColor(speaker: string, allSpeakers: string[]): string {
    const idx = allSpeakers.indexOf(speaker);
    return speakerColors[idx >= 0 ? idx % speakerColors.length : 0];
  }

  function formatTime(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  let speakers = $derived(
    utterances
      ? [...new Set(utterances.map((u) => u.speaker))]
      : []
  );
</script>

{#if utterances && utterances.length > 0}
  <div
    class="flex flex-col gap-1 py-2"
    style="
      font-family: 'DM Sans', sans-serif;
      font-size: 15px;
    "
  >
    {#each utterances as u}
      {@const color = getSpeakerColor(u.speaker, speakers)}
      <div class="flex gap-3 py-2 px-2 rounded-md utterance-row">
        <button
          class="shrink-0"
          onclick={() => onSeek?.(u.start)}
          title="Jump to {formatTime(u.start)}"
          style="
            background: none;
            border: none;
            padding: 0;
            cursor: pointer;
            font-family: 'DM Sans', sans-serif;
            font-size: 12.5px;
            color: var(--text-faint);
            min-width: 42px;
            text-align: right;
            line-height: 1.5;
          "
        >
          {formatTime(u.start)}
        </button>
        <div class="flex-1 min-w-0">
          <span
            style="
              font-size: 12.5px;
              font-weight: 600;
              color: {color};
              margin-right: 6px;
            "
          >
            {u.speaker}
          </span>
          <span style="color: var(--text-secondary); line-height: 1.5;">
            {u.text}
          </span>
        </div>
      </div>
    {/each}
  </div>
{:else}
  <div
    class="flex items-center justify-center py-16"
    style="
      font-family: 'DM Sans', sans-serif;
      font-size: 15px;
      color: var(--text-faint);
    "
  >
    No transcript available
  </div>
{/if}

<style>
  .utterance-row:hover {
    background: var(--raised);
  }

  .utterance-row button:hover {
    color: var(--gold) !important;
  }
</style>
