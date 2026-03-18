<script lang="ts">
  import type { MeetingSummary } from "../tauri";
  import { retryProcessing } from "../tauri";

  interface Props {
    meeting: MeetingSummary;
  }

  let { meeting }: Props = $props();
  let retrying = $state(false);

  const stages = ["merge", "frames", "transcribe", "diarize", "analyze", "export"] as const;

  let failedStage = $derived(
    stages.find((s) => meeting.pipeline_status[s].error) ?? null
  );

  let allDone = $derived(stages.every((s) => meeting.pipeline_status[s].completed));

  let missingOutputs = $derived.by(() => {
    if (!allDone) return false;
    return !meeting.has_note || !meeting.has_transcript;
  });

  let shouldShow = $derived(failedStage !== null || missingOutputs);

  function getRecordingDir(filePath: string): string {
    const lastSep = Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\'));
    return lastSep > 0 ? filePath.substring(0, lastSep) : filePath;
  }

  async function retry(fromStage?: string) {
    if (!meeting.recording_path || retrying) return;
    retrying = true;
    try {
      await retryProcessing(getRecordingDir(meeting.recording_path), fromStage);
    } catch (e) {
      console.error("Retry failed:", e);
    } finally {
      retrying = false;
    }
  }
</script>

{#if shouldShow}
  <div
    class="flex items-center justify-between flex-wrap gap-2"
    style="
      padding: 10px 14px;
      border-radius: 8px;
      background: {failedStage ? 'rgba(200,80,60,0.10)' : 'rgba(180,165,130,0.10)'};
      font-family: 'DM Sans', sans-serif;
      font-size: 14.5px;
    "
  >
    <span style="color: {failedStage ? '#D06850' : '#B4A882'};">
      {#if failedStage}
        Pipeline failed at {failedStage}: {meeting.pipeline_status[failedStage].error}
      {:else}
        Some outputs are missing (note or transcript).
      {/if}
    </span>

    <div class="flex gap-2">
      {#if failedStage}
        <button
          onclick={() => retry(failedStage ?? undefined)}
          disabled={retrying}
          style="
            padding: 4px 12px;
            border-radius: 6px;
            border: none;
            background: rgba(200,80,60,0.15);
            color: #D06850;
            font-family: 'DM Sans', sans-serif;
            font-size: 13.5px;
            font-weight: 600;
            cursor: pointer;
          "
        >
          {retrying ? "Retrying..." : `Retry from ${failedStage}`}
        </button>
      {/if}
      {#if !meeting.has_note && allDone}
        <button
          onclick={() => retry("analyze")}
          disabled={retrying}
          style="
            padding: 4px 12px;
            border-radius: 6px;
            border: none;
            background: rgba(180,165,130,0.15);
            color: #B4A882;
            font-family: 'DM Sans', sans-serif;
            font-size: 13.5px;
            font-weight: 600;
            cursor: pointer;
          "
        >
          Generate Note
        </button>
      {/if}
      {#if !meeting.has_transcript && allDone}
        <button
          onclick={() => retry("transcribe")}
          disabled={retrying}
          style="
            padding: 4px 12px;
            border-radius: 6px;
            border: none;
            background: rgba(180,165,130,0.15);
            color: #B4A882;
            font-family: 'DM Sans', sans-serif;
            font-size: 13.5px;
            font-weight: 600;
            cursor: pointer;
          "
        >
          Re-transcribe
        </button>
      {/if}
    </div>
  </div>
{/if}
