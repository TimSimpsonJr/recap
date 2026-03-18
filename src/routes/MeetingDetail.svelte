<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { settings } from "../lib/stores/settings";
  import { getMeetingDetail, type MeetingDetail } from "../lib/tauri";
  import MeetingHeader from "../lib/components/MeetingHeader.svelte";
  import RetryBanner from "../lib/components/RetryBanner.svelte";
  import MeetingPlayer from "../lib/components/MeetingPlayer.svelte";
  import MeetingNotes from "../lib/components/MeetingNotes.svelte";
  import MeetingTranscript from "../lib/components/MeetingTranscript.svelte";
  import ScreenshotGallery from "../lib/components/ScreenshotGallery.svelte";
  import PipelineStatusBadge from "../lib/components/PipelineStatusBadge.svelte";

  interface Props {
    meetingId: string;
  }

  let { meetingId }: Props = $props();

  let detail: MeetingDetail | null = $state(null);
  let error: string | null = $state(null);
  let loading = $state(true);
  let activeTab: "notes" | "transcript" | "screenshots" = $state("notes");
  let playerRef: MeetingPlayer | undefined = $state();

  onMount(async () => {
    await loadDetail();
  });

  async function loadDetail() {
    loading = true;
    error = null;
    try {
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

  function handleSeek(time: number) {
    playerRef?.seekTo(time);
  }

  let videoSrc = $derived.by(() => {
    if (!detail) return null;
    if (detail.summary.has_video && detail.summary.recording_path) {
      return detail.summary.recording_path;
    }
    // Check for audio-only
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

<div class="flex flex-col min-h-screen" style="background: #1D1D1B;">
  {#if loading}
    <div
      class="flex items-center justify-center h-screen"
      style="font-family: 'DM Sans', sans-serif; color: #585650;"
    >
      <span class="spinner"></span>
    </div>
  {:else if error}
    <div style="padding: 28px;">
      <a
        href="#dashboard"
        style="
          font-family: 'DM Sans', sans-serif;
          font-size: 12.5px;
          color: #A8A078;
          text-decoration: none;
        "
      >&larr; Back</a>
      <div
        class="mt-4 p-3 rounded-lg"
        style="
          background: rgba(200,80,60,0.10);
          color: #D06850;
          font-family: 'DM Sans', sans-serif;
          font-size: 13px;
        "
      >
        {error}
      </div>
    </div>
  {:else if detail}
    <div style="padding: 24px 28px;" class="flex flex-col gap-4">
      <MeetingHeader meeting={detail.summary} />

      <div class="flex items-center gap-3">
        <PipelineStatusBadge status={detail.summary.pipeline_status} />
      </div>

      <RetryBanner meeting={detail.summary} />

      <MeetingPlayer
        bind:this={playerRef}
        src={videoSrc}
        audioOnly={isAudioOnly}
      />

      <!-- Tabs -->
      <div
        class="flex gap-0"
        style="
          border-bottom: 1px solid #262624;
          font-family: 'DM Sans', sans-serif;
          font-size: 13px;
        "
      >
        <button
          onclick={() => activeTab = "notes"}
          style="
            padding: 8px 16px;
            border: none;
            background: none;
            cursor: pointer;
            font-family: 'DM Sans', sans-serif;
            font-size: 13px;
            font-weight: {activeTab === 'notes' ? '600' : '400'};
            color: {activeTab === 'notes' ? '#A8A078' : '#585650'};
            border-bottom: 2px solid {activeTab === 'notes' ? '#A8A078' : 'transparent'};
            margin-bottom: -1px;
          "
        >
          Notes
        </button>
        <button
          onclick={() => activeTab = "transcript"}
          style="
            padding: 8px 16px;
            border: none;
            background: none;
            cursor: pointer;
            font-family: 'DM Sans', sans-serif;
            font-size: 13px;
            font-weight: {activeTab === 'transcript' ? '600' : '400'};
            color: {activeTab === 'transcript' ? '#A8A078' : '#585650'};
            border-bottom: 2px solid {activeTab === 'transcript' ? '#A8A078' : 'transparent'};
            margin-bottom: -1px;
          "
        >
          Transcript
        </button>
        {#if screenshotCount > 0}
          <button
            onclick={() => activeTab = "screenshots"}
            style="
              padding: 8px 16px;
              border: none;
              background: none;
              cursor: pointer;
              font-family: 'DM Sans', sans-serif;
              font-size: 13px;
              font-weight: {activeTab === 'screenshots' ? '600' : '400'};
              color: {activeTab === 'screenshots' ? '#A8A078' : '#585650'};
              border-bottom: 2px solid {activeTab === 'screenshots' ? '#A8A078' : 'transparent'};
              margin-bottom: -1px;
            "
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
