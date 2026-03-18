<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { settings } from "../stores/settings";
  import { generateBriefing, type Briefing } from "../tauri";

  interface Props {
    eventId: string;
    title: string;
    participants: string[];
    time: string;
    eventDescription?: string;
  }

  let { eventId, title, participants, time, eventDescription }: Props = $props();

  let briefing: Briefing | null = $state(null);
  let loading = $state(true);
  let error: string | null = $state(null);

  async function loadBriefing() {
    loading = true;
    error = null;
    try {
      const s = get(settings);
      const participantNames = participants;
      const vaultMeetingsDir = s.vaultPath && s.meetingsFolder
        ? `${s.vaultPath}/${s.meetingsFolder}`
        : undefined;

      briefing = await generateBriefing(
        eventId,
        title,
        participantNames,
        time,
        s.recordingsFolder,
        vaultMeetingsDir,
        eventDescription
      );
    } catch (err) {
      error = String(err);
      console.error("Briefing generation failed:", err);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadBriefing();
  });
</script>

<div
  style="
    background: var(--bg);
    border-top: 1px solid var(--border);
    padding: 16px 18px;
    font-family: 'DM Sans', sans-serif;
  "
>
  {#if loading}
    <!-- Loading state -->
    <div style="display: flex; align-items: center; gap: 10px; padding: 12px 0;">
      <div
        style="
          width: 16px;
          height: 16px;
          border: 2px solid var(--border);
          border-top-color: var(--gold);
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        "
      ></div>
      <span style="font-size: 13px; color: var(--text-muted);">Generating briefing...</span>
    </div>
  {:else if error}
    <!-- Error state -->
    <div style="padding: 12px 0;">
      <div style="font-size: 13px; color: var(--red); margin-bottom: 8px;">
        Failed to generate briefing: {error}
      </div>
      <button
        onclick={loadBriefing}
        style="
          padding: 4px 12px;
          font-size: 12px;
          font-family: 'DM Sans', sans-serif;
          border-radius: 4px;
          border: 1px solid var(--border);
          background: var(--surface);
          color: var(--text);
          cursor: pointer;
        "
      >Retry</button>
    </div>
  {:else if briefing}
    <!-- First-meeting banner -->
    {#if briefing.first_meeting}
      <div
        style="
          background: var(--surface);
          border: 1px solid var(--gold);
          border-radius: 6px;
          padding: 10px 14px;
          margin-bottom: 14px;
          font-size: 13px;
          color: var(--gold);
        "
      >
        First meeting with these participants
        {#if eventDescription}
          <div style="color: var(--text-muted); margin-top: 6px; font-size: 12.5px;">
            {eventDescription}
          </div>
        {/if}
      </div>
    {/if}

    <!-- Topics -->
    {#if briefing.topics.length > 0}
      <div style="margin-bottom: 14px;">
        <h4
          style="
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0 0 6px 0;
          "
        >Topics</h4>
        <ul style="margin: 0; padding-left: 18px; list-style: none;">
          {#each briefing.topics as topic}
            <li
              style="
                font-size: 13px;
                color: var(--text);
                padding: 2px 0;
                position: relative;
                padding-left: 2px;
              "
            >
              <span
                style="
                  position: absolute;
                  left: -14px;
                  color: var(--gold);
                  font-weight: bold;
                "
              >&bull;</span>
              {topic}
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    <!-- Open Action Items -->
    {#if briefing.action_items.length > 0}
      <div style="margin-bottom: 14px;">
        <h4
          style="
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0 0 6px 0;
          "
        >Open Action Items</h4>
        <div style="display: flex; flex-direction: column; gap: 4px;">
          {#each briefing.action_items as item}
            <div
              style="
                display: flex;
                gap: 8px;
                font-size: 13px;
                padding: 4px 0;
                align-items: baseline;
              "
            >
              <span
                style="
                  color: var(--blue);
                  font-weight: 500;
                  white-space: nowrap;
                  flex-shrink: 0;
                "
              >{item.assignee}</span>
              <span style="color: var(--text);">{item.description}</span>
              <span
                style="
                  color: var(--text-faint);
                  font-size: 12px;
                  white-space: nowrap;
                  flex-shrink: 0;
                  margin-left: auto;
                "
              >{item.from_meeting}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Context -->
    {#if briefing.context}
      <div style="margin-bottom: 14px;">
        <h4
          style="
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0 0 6px 0;
          "
        >Context</h4>
        <p style="font-size: 13px; color: var(--text-muted); margin: 0; line-height: 1.5;">
          {briefing.context}
        </p>
      </div>
    {/if}

    <!-- Relationship Summary -->
    {#if briefing.relationship_summary}
      <div>
        <h4
          style="
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0 0 6px 0;
          "
        >Relationship</h4>
        <p style="font-size: 13px; color: var(--text-muted); margin: 0; line-height: 1.5;">
          {briefing.relationship_summary}
        </p>
      </div>
    {/if}
  {/if}
</div>

<style>
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
</style>
