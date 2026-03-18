<script lang="ts">
  import { recorderState, recorderTag, startRec, stopRec } from "../stores/recorder";

  let state = $derived($recorderState);
  let tag = $derived(recorderTag(state));
  let processName = $derived(
    typeof state === "object" && "detected" in state ? state.detected.process_name : null
  );
</script>

{#if tag !== "idle" && tag !== "declined"}
  <div
    class="flex items-center justify-between"
    style="
      padding: 8px 28px;
      background: #1A1A18;
      border-bottom: 1px solid #262624;
      font-family: 'DM Sans', sans-serif;
      font-size: 13.5px;
    "
  >
    <div class="flex items-center gap-3">
      {#if tag === "recording"}
        <span class="rec-dot"></span>
        <span style="color: #B0ADA5;">Recording</span>
      {:else if tag === "detected"}
        <span style="color: #78756E;">
          <svg class="inline-block mr-1" width="14" height="14" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="5" stroke="#78756E" stroke-width="1.5"/>
            <circle cx="7" cy="7" r="2" fill="#78756E"/>
          </svg>
          {processName} detected
        </span>
      {:else if tag === "processing"}
        <span class="spinner"></span>
        <span style="color: #B0ADA5;">Processing recording...</span>
      {/if}
    </div>

    <div class="flex items-center gap-2">
      {#if tag === "detected"}
        <button
          onclick={startRec}
          style="
            padding: 4px 14px;
            border-radius: 6px;
            border: none;
            background: #A8A078;
            color: #1D1D1B;
            font-family: 'DM Sans', sans-serif;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
          "
        >
          Start Recording
        </button>
      {:else if tag === "recording"}
        <button
          onclick={stopRec}
          style="
            padding: 4px 14px;
            border-radius: 6px;
            border: none;
            background: #A8A078;
            color: #1D1D1B;
            font-family: 'DM Sans', sans-serif;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
          "
        >
          Stop
        </button>
      {/if}
    </div>
  </div>
{/if}

<style>
  .rec-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #ef4444;
    animation: pulse 1.5s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  .spinner {
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 2px solid #464440;
    border-top-color: #A8A078;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }
</style>
