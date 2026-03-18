<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { settings } from "../stores/settings";
  import { getMeetingDetail, type MeetingDetail, type MeetingSummary, type Utterance } from "../tauri";
  import MeetingNotes from "./MeetingNotes.svelte";
  import MeetingTranscript from "./MeetingTranscript.svelte";

  interface Props {
    nodeId: string;
    nodeLabel: string;
    nodeType: string; // "person" or "company"
    /** All meetings connected to this node (passed from GraphView) */
    connectedMeetings: { id: string; label: string }[];
    onClose: () => void;
  }

  let { nodeId, nodeLabel, nodeType, connectedMeetings, onClose }: Props = $props();

  // Sidebar view state: "list" or "detail"
  let view = $state<"list" | "detail">("list");
  let selectedMeetingId = $state<string | null>(null);
  let detail: MeetingDetail | null = $state(null);
  let detailLoading = $state(false);
  let detailError = $state<string | null>(null);
  let activeTab: "notes" | "transcript" = $state("notes");

  // ── DUMMY DATA (remove before PR) ──
  const DUMMY_DATA = true;

  function doneStatus() {
    const done = { completed: true, timestamp: "2026-03-17T10:00:00", error: null };
    return { merge: done, frames: done, transcribe: done, diarize: done, analyze: done, export: done };
  }

  const DUMMY_NOTE = `## Summary

Brief meeting summary with key discussion points.

## Key Points

- Discussion point one
- Discussion point two

## Action Items

- [ ] Follow up on discussed items`;

  const DUMMY_TRANSCRIPT: Utterance[] = [
    { speaker: "Tim", start: 0, end: 15, text: "Let's discuss the key items on the agenda." },
    { speaker: "Participant", start: 16, end: 35, text: "Sure, let's start with the first topic." },
  ];

  function getDummyDetail(meetingId: string): MeetingDetail {
    const meeting = connectedMeetings.find((m) => m.id === meetingId);
    const title = meeting?.label ?? "Meeting";
    const date = meetingId.substring(0, 10);
    return {
      summary: {
        id: meetingId,
        title,
        date,
        platform: "zoom",
        participants: [],
        duration_seconds: 2700,
        pipeline_status: doneStatus(),
        has_note: true,
        has_transcript: true,
        has_video: false,
        recording_path: null,
        note_path: null,
      },
      note_content: DUMMY_NOTE,
      transcript: DUMMY_TRANSCRIPT,
      screenshots: [],
    };
  }
  // ── END DUMMY DATA ──

  async function openMeetingDetail(meetingId: string) {
    selectedMeetingId = meetingId;
    view = "detail";
    detailLoading = true;
    detailError = null;
    activeTab = "notes";

    try {
      if (DUMMY_DATA) {
        detail = getDummyDetail(meetingId);
        detailLoading = false;
        return;
      }

      const s = get(settings);
      const recordingsDir = s.recordingsFolder;
      if (!recordingsDir) {
        detailError = "No recordings folder configured";
        detailLoading = false;
        return;
      }
      const vaultMeetingsDir =
        s.vaultPath && s.meetingsFolder
          ? `${s.vaultPath}/${s.meetingsFolder}`
          : undefined;
      detail = await getMeetingDetail(meetingId, recordingsDir, vaultMeetingsDir);
    } catch (e) {
      detailError = e instanceof Error ? e.message : String(e);
    } finally {
      detailLoading = false;
    }
  }

  function backToList() {
    view = "list";
    selectedMeetingId = null;
    detail = null;
  }
</script>

<div class="graph-sidebar">
  <!-- Header -->
  <div class="sidebar-header">
    {#if view === "detail"}
      <button class="back-btn" onclick={backToList} title="Back to meeting list">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9 2L4 7l5 5" />
        </svg>
      </button>
    {/if}
    <div class="sidebar-title-area">
      <span class="sidebar-node-type">{nodeType}</span>
      <h3 class="sidebar-title">{nodeLabel}</h3>
    </div>
    <button class="close-btn" onclick={onClose} title="Close sidebar">
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <path d="M1 1l12 12M13 1L1 13" />
      </svg>
    </button>
  </div>

  <!-- Content -->
  <div class="sidebar-content">
    {#if view === "list"}
      <!-- Meeting list -->
      {#if connectedMeetings.length === 0}
        <div class="empty-state">No meetings found</div>
      {:else}
        <div class="meeting-count">{connectedMeetings.length} meeting{connectedMeetings.length === 1 ? '' : 's'}</div>
        {#each connectedMeetings as meeting}
          <button
            class="sidebar-meeting-row"
            onclick={() => openMeetingDetail(meeting.id)}
          >
            <span class="meeting-dot"></span>
            <span class="meeting-label">{meeting.label}</span>
          </button>
        {/each}
      {/if}
    {:else if view === "detail"}
      {#if detailLoading}
        <div class="loading-state">
          <span class="spinner"></span>
        </div>
      {:else if detailError}
        <div class="error-state">{detailError}</div>
      {:else if detail}
        <h4 class="detail-title">{detail.summary.title}</h4>
        <div class="detail-meta">
          {new Date(detail.summary.date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
          {#if detail.summary.platform}
            <span class="meta-dot">&middot;</span>
            {detail.summary.platform}
          {/if}
        </div>

        <!-- Tabs -->
        <div class="detail-tabs">
          <button
            class="detail-tab"
            class:active={activeTab === "notes"}
            onclick={() => activeTab = "notes"}
          >Notes</button>
          <button
            class="detail-tab"
            class:active={activeTab === "transcript"}
            onclick={() => activeTab = "transcript"}
          >Transcript</button>
        </div>

        <div class="detail-body">
          {#if activeTab === "notes"}
            <MeetingNotes content={detail.note_content} />
          {:else}
            <MeetingTranscript utterances={detail.transcript} onSeek={() => {}} />
          {/if}
        </div>
      {/if}
    {/if}
  </div>
</div>

<style>
  .graph-sidebar {
    position: absolute;
    top: 0;
    right: 0;
    width: 340px;
    height: 100%;
    background: #1D1D1B;
    border-left: 1px solid #262624;
    display: flex;
    flex-direction: column;
    z-index: 20;
    animation: sidebar-slide-in 200ms ease;
  }

  @keyframes sidebar-slide-in {
    from {
      transform: translateX(100%);
    }
    to {
      transform: translateX(0);
    }
  }

  .sidebar-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 14px;
    border-bottom: 1px solid #262624;
    flex-shrink: 0;
  }

  .back-btn {
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
    flex-shrink: 0;
    transition: background 120ms ease, color 120ms ease;
  }

  .back-btn:hover {
    background: #2B2B28;
    color: #D8D5CE;
  }

  .sidebar-title-area {
    flex: 1;
    min-width: 0;
  }

  .sidebar-node-type {
    font-family: 'DM Sans', sans-serif;
    font-size: 10px;
    font-weight: 600;
    color: #585650;
    text-transform: uppercase;
    letter-spacing: 0.8px;
  }

  .sidebar-title {
    font-family: 'Source Serif 4', serif;
    font-size: 16px;
    font-weight: 600;
    color: #D8D5CE;
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .close-btn {
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
    flex-shrink: 0;
    transition: background 120ms ease, color 120ms ease;
  }

  .close-btn:hover {
    background: #2B2B28;
    color: #D8D5CE;
  }

  .sidebar-content {
    flex: 1;
    overflow-y: auto;
    padding: 12px 14px;
  }

  .meeting-count {
    font-family: 'DM Sans', sans-serif;
    font-size: 12px;
    color: #585650;
    margin-bottom: 8px;
  }

  .sidebar-meeting-row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 10px 12px;
    border-radius: 6px;
    border: none;
    background: #242422;
    cursor: pointer;
    margin-bottom: 4px;
    text-align: left;
    transition: background 120ms ease;
  }

  .sidebar-meeting-row:hover {
    background: #2B2B28;
  }

  .meeting-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #A8A078;
    flex-shrink: 0;
  }

  .meeting-label {
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    color: #D8D5CE;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .empty-state {
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    color: #585650;
    text-align: center;
    padding: 24px 0;
  }

  .loading-state {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32px 0;
  }

  .error-state {
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    color: #D06850;
    background: rgba(200,80,60,0.10);
    padding: 12px;
    border-radius: 8px;
  }

  .detail-title {
    font-family: 'Source Serif 4', serif;
    font-size: 16px;
    font-weight: 600;
    color: #D8D5CE;
    margin: 0 0 4px 0;
  }

  .detail-meta {
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    color: #78756E;
    margin-bottom: 12px;
  }

  .meta-dot {
    color: #464440;
    margin: 0 4px;
  }

  .detail-tabs {
    display: flex;
    gap: 0;
    border-bottom: 1px solid #262624;
    margin-bottom: 8px;
  }

  .detail-tab {
    padding: 6px 12px;
    border: none;
    background: none;
    cursor: pointer;
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
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

  .detail-body {
    font-size: 14px;
  }

  .spinner {
    display: inline-block;
    width: 20px;
    height: 20px;
    border: 2px solid #464440;
    border-top-color: #A8A078;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* Scrollbar */
  .sidebar-content::-webkit-scrollbar {
    width: 4px;
  }
  .sidebar-content::-webkit-scrollbar-track {
    background: transparent;
  }
  .sidebar-content::-webkit-scrollbar-thumb {
    background: #464440;
    border-radius: 2px;
  }
</style>
