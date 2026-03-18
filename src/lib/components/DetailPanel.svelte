<script lang="ts">
  import { get } from "svelte/store";
  import { settings } from "../stores/settings";
  import { getMeetingDetail, type MeetingDetail, type Utterance } from "../tauri";
  import { USE_DUMMY_DATA, getDummyDetail } from "../dummy-data";
  import MeetingHeader from "./MeetingHeader.svelte";
  import RetryBanner from "./RetryBanner.svelte";
  import MeetingPlayer from "./MeetingPlayer.svelte";
  import MeetingNotes from "./MeetingNotes.svelte";
  import MeetingTranscript from "./MeetingTranscript.svelte";
  import ScreenshotGallery from "./ScreenshotGallery.svelte";
  import PipelineDots from "./PipelineDots.svelte";

  interface Props {
    meetingId: string;
    onClose: () => void;
  }

  let { meetingId, onClose }: Props = $props();

  let detail: MeetingDetail | null = $state(null);
  let error: string | null = $state(null);
  let loading = $state(true);
  let activeTab: "notes" | "transcript" | "screenshots" = $state("notes");
  let playerRef: MeetingPlayer | undefined = $state();

  async function loadDetail() {
    loading = true;
    error = null;
    activeTab = "notes";
    try {
      if (USE_DUMMY_DATA) {
        detail = getDummyDetail(meetingId);
        loading = false;
        return;
      }
      const s = get(settings);
      const recordingsDir = s.recordingsFolder;
      if (!recordingsDir) {
        error = "No recordings folder configured";
        loading = false;
        return;
      }
      const vaultMeetingsDir =
        s.vaultPath && s.meetingsFolder
          ? `${s.vaultPath}/${s.meetingsFolder}`
          : undefined;
      detail = await getMeetingDetail(meetingId, recordingsDir, vaultMeetingsDir);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  // Reload when meetingId changes
  $effect(() => {
    meetingId;
    loadDetail();
  });

  function handleSeek(time: number) {
    playerRef?.seekTo(time);
  }

  let videoSrc = $derived.by(() => {
    if (!detail) return null;
    if (detail.summary.has_video && detail.summary.recording_path) {
      return detail.summary.recording_path;
    }
    if (detail.summary.recording_path) {
      return detail.summary.recording_path;
    }
    return null;
  });

  let isAudioOnly = $derived(
    detail ? !detail.summary.has_video : false
  );

  let screenshotCount = $derived(detail?.screenshots.length ?? 0);
</script>

<div class="detail-panel">
  <!-- Close button -->
  <button
    onclick={onClose}
    class="close-btn"
    title="Close detail panel"
  >
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
      <path d="M1 1l12 12M13 1L1 13" />
    </svg>
  </button>

  {#if loading}
    <div class="detail-loading">
      <span class="spinner"></span>
    </div>
  {:else if error}
    <div class="detail-error">
      {error}
    </div>
  {:else if detail}
    <div class="detail-content">
      <MeetingHeader meeting={detail.summary} showBack={false} />

      <div class="flex items-center gap-3" style="margin-top: 12px;">
        <PipelineDots status={detail.summary.pipeline_status} recordingPath={detail.summary.recording_path} />
      </div>

      <RetryBanner meeting={detail.summary} />

      <MeetingPlayer
        bind:this={playerRef}
        src={videoSrc}
        audioOnly={isAudioOnly}
      />

      <!-- Tabs -->
      <div class="detail-tabs">
        <button
          onclick={() => activeTab = "notes"}
          class="detail-tab"
          class:active={activeTab === "notes"}
        >
          Notes
        </button>
        <button
          onclick={() => activeTab = "transcript"}
          class="detail-tab"
          class:active={activeTab === "transcript"}
        >
          Transcript
        </button>
        {#if screenshotCount > 0}
          <button
            onclick={() => activeTab = "screenshots"}
            class="detail-tab"
            class:active={activeTab === "screenshots"}
          >
            Screenshots ({screenshotCount})
          </button>
        {/if}
      </div>

      <!-- Tab content -->
      <div style="padding-bottom: 32px;">
        {#if activeTab === "notes"}
          <MeetingNotes content={detail.note_content} />
        {:else if activeTab === "transcript"}
          <MeetingTranscript
            utterances={detail.transcript}
            onSeek={handleSeek}
          />
        {:else if activeTab === "screenshots"}
          <ScreenshotGallery screenshots={detail.screenshots} />
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .detail-panel {
    height: 100%;
    overflow-y: auto;
    background: #1D1D1B;
    border-left: 1px solid #262624;
    position: relative;
  }

  .close-btn {
    position: sticky;
    top: 12px;
    float: right;
    margin: 12px 12px 0 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 6px;
    border: none;
    background: #282826;
    color: #78756E;
    cursor: pointer;
    transition: background 120ms ease, color 120ms ease;
  }

  .close-btn:hover {
    background: #2B2B28;
    color: #D8D5CE;
  }

  .detail-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #585650;
  }

  .detail-error {
    padding: 24px;
    font-family: 'DM Sans', sans-serif;
    font-size: 14.5px;
    color: #D06850;
    background: rgba(200,80,60,0.10);
    margin: 16px;
    border-radius: 8px;
  }

  .detail-content {
    padding: 16px 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .detail-tabs {
    display: flex;
    gap: 0;
    border-bottom: 1px solid #262624;
    font-family: 'DM Sans', sans-serif;
    font-size: 14.5px;
  }

  .detail-tab {
    padding: 8px 16px;
    border: none;
    background: none;
    cursor: pointer;
    font-family: 'DM Sans', sans-serif;
    font-size: 14.5px;
    font-weight: 400;
    color: #585650;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }

  .detail-tab.active {
    font-weight: 600;
    color: #A8A078;
    border-bottom-color: #A8A078;
  }

  .spinner {
    display: inline-block;
    width: 24px;
    height: 24px;
    border: 2px solid #464440;
    border-top-color: #A8A078;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }
</style>
