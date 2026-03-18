<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { settings } from "../stores/settings";
  import { getMeetingDetail, type MeetingDetail, type Utterance } from "../tauri";
  import MeetingHeader from "./MeetingHeader.svelte";
  import RetryBanner from "./RetryBanner.svelte";
  import MeetingPlayer from "./MeetingPlayer.svelte";
  import MeetingNotes from "./MeetingNotes.svelte";
  import MeetingTranscript from "./MeetingTranscript.svelte";
  import ScreenshotGallery from "./ScreenshotGallery.svelte";
  import PipelineStatusBadge from "./PipelineStatusBadge.svelte";

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

  // ── DUMMY DATA (remove before PR) ──
  const DUMMY_DATA = true;

  function doneStatus() {
    const done = { completed: true, timestamp: "2026-03-17T10:00:00", error: null };
    return { merge: done, frames: done, transcribe: done, diarize: done, analyze: done, export: done };
  }

  const DUMMY_NOTE = `---
date: 2026-03-17
participants:
  - "[[Jane Smith]]"
  - "[[Bob Jones]]"
  - "[[Alice Chen]]"
company: "[[Acme Corp]]"
platform: zoom
duration: 45m
type: client-call
---

## Summary

Kicked off the Q2 infrastructure modernization project with the Acme Corp team. Agreed on a phased approach starting with CI/CD pipeline improvements, followed by container orchestration migration. Budget approved for Phase 1.

## Key Points

- **CI/CD Pipeline:** Current Jenkins setup is causing 40-minute build times. Moving to GitHub Actions with NVENC-accelerated test runners.
- **Container Migration:** Targeting Kubernetes on AWS EKS. [[Jane Smith]] has prior experience from Globex migration.
- **Timeline:** Phase 1 (CI/CD) starts next week, target completion by end of April. Phase 2 (containers) begins May.
- **Budget:** $45K approved for Phase 1 tooling and infrastructure. Phase 2 budget TBD pending Phase 1 results.

## Decisions Made

- GitHub Actions over CircleCI (team familiarity + cost)
- EKS over self-managed K8s (operational overhead concern)
- [[Bob Jones]] will lead the CI/CD migration technical work

## Action Items

- [ ] Tim: Send Phase 1 proposal with detailed timeline by Friday
- [ ] [[Jane Smith]]: Review and share Globex migration runbook
- [ ] [[Bob Jones]]: Set up GitHub Actions proof-of-concept repo
- [ ] [[Alice Chen]]: Compile current build time metrics for baseline

## Follow-up Required

- Need to schedule follow-up with Acme Corp DevOps team for Jenkins audit
- Awaiting AWS account access from Acme IT department

## Relationship Notes

Jane is the key technical decision-maker. Bob defers to her on architecture choices. Alice is new to the team (joined 2 weeks ago) and is ramping up quickly.`;

  const DUMMY_TRANSCRIPT: Utterance[] = [
    { speaker: "Tim", start: 0, end: 15, text: "Alright, thanks everyone for joining. Let's kick off the Q2 infrastructure discussion." },
    { speaker: "Jane Smith", start: 16, end: 35, text: "Thanks Tim. We've been looking forward to this. The build times have been killing our velocity." },
    { speaker: "Bob Jones", start: 36, end: 58, text: "Yeah, we're seeing 40-minute builds on average. Some of the integration test suites take even longer. It's really impacting our release cadence." },
    { speaker: "Tim", start: 59, end: 82, text: "That's exactly what we want to address. I've been looking at two options: GitHub Actions and CircleCI. Both support parallel test execution and have good caching." },
    { speaker: "Jane Smith", start: 83, end: 115, text: "I'd vote for GitHub Actions. When I was at Globex, we migrated from Jenkins to Actions and cut our build times by 60%. The team is already familiar with it since our repos are on GitHub." },
    { speaker: "Alice Chen", start: 116, end: 140, text: "I can pull together the current build time metrics so we have a baseline to measure against. I've been looking at our Jenkins dashboards and there's a lot of data there." },
    { speaker: "Tim", start: 141, end: 168, text: "That would be great, Alice. On the container side, we're looking at moving to Kubernetes. Jane, you mentioned you have experience with EKS from the Globex migration?" },
    { speaker: "Jane Smith", start: 169, end: 205, text: "Yes, we ran EKS in production for about two years. I can share our migration runbook. The biggest lesson learned was to invest in proper observability from day one." },
    { speaker: "Bob Jones", start: 206, end: 235, text: "I can set up a proof-of-concept repo for GitHub Actions this week. We should probably start with one of our smaller services to validate the approach." },
    { speaker: "Tim", start: 236, end: 270, text: "Perfect. Let's do Phase 1 on CI/CD first, then tackle containers in Phase 2. I'll send over a detailed proposal with timeline by Friday. Budget-wise, we're looking at about 45K for Phase 1 tooling." },
    { speaker: "Jane Smith", start: 271, end: 295, text: "That sounds reasonable. We'll need to loop in our DevOps team for the Jenkins audit. Can we schedule that for next week?" },
    { speaker: "Tim", start: 296, end: 315, text: "Absolutely. I'll coordinate with your IT department on AWS account access too. Any other questions before we wrap up?" },
    { speaker: "Alice Chen", start: 316, end: 335, text: "Just to confirm, the baseline metrics you want are build times, test suite duration, and deployment frequency?" },
    { speaker: "Tim", start: 336, end: 350, text: "Exactly. And if you can break it down by service, that would be even better. Alright, great meeting everyone. Talk soon." },
  ];

  function getDummyDetail(id: string): MeetingDetail {
    const titles: Record<string, string> = {
      "2026-03-17-project-kickoff-acme": "Project Kickoff with Acme Corp",
      "2026-03-17-weekly-standup": "Weekly Engineering Standup",
      "2026-03-16-quarterly-review": "Quarterly Business Review",
      "2026-03-16-client-feedback": "Client Feedback Session",
      "2026-03-16-design-sprint-retro": "Design Sprint Retro",
      "2026-03-15-investor-update": "Investor Update Call",
      "2026-03-15-1on1-sarah": "1:1 with Sarah",
      "2026-03-14-product-planning": "Product Planning Session",
    };
    const title = titles[id] || "Meeting";
    const date = id.substring(0, 10);

    return {
      summary: {
        id,
        title,
        date,
        platform: "zoom",
        participants: ["Jane Smith", "Bob Jones", "Alice Chen"],
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

  onMount(async () => {
    await loadDetail();
  });

  async function loadDetail() {
    loading = true;
    error = null;
    activeTab = "notes";
    try {
      // ── DUMMY MODE (remove before PR) ──
      if (DUMMY_DATA) {
        detail = getDummyDetail(meetingId);
        loading = false;
        return;
      }
      // ── END DUMMY MODE ──

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
        <PipelineStatusBadge status={detail.summary.pipeline_status} />
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
