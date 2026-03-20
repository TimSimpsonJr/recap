<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { get } from "svelte/store";
  import { settings } from "../../stores/settings";
  import {
    toggleEventAutoRecord,
    toggleSeriesAutoRecord,
  } from "../../stores/calendar";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import {
    platformLabel,
    formatTimeRange,
    formatDayHeader,
    looksLikeMeetingInvite,
  } from "../../calendar-utils";
  import BriefingPanel from "../BriefingPanel.svelte";
  import type { CalendarEvent } from "../../tauri";

  interface Props {
    event: CalendarEvent;
    matchedId: string | null;
    onClose: () => void;
    onOpenPopover: (name: string, email: string | null, rect: DOMRect) => void;
  }

  let { event, matchedId, onClose, onOpenPopover }: Props = $props();

  // Participants filtered to exclude current user
  let visibleParticipants = $derived.by(() => {
    const userName = get(settings).userName?.toLowerCase() ?? "";
    return event.participants.filter(
      (p) => p.name.toLowerCase() !== userName
    );
  });

  // Description: show only if non-empty and not boilerplate
  let showDescription = $derived(
    event.description != null &&
    event.description.trim().length > 0 &&
    !looksLikeMeetingInvite(event.description)
  );

  function handleParticipantClick(
    p: { name: string; email: string | null },
    e: MouseEvent
  ) {
    const btn = e.currentTarget as HTMLElement;
    const rect = btn.getBoundingClientRect();
    onOpenPopover(p.name, p.email, rect);
  }

  // Dismiss on Escape
  let handleKey: ((e: KeyboardEvent) => void) | null = null;

  onMount(() => {
    handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
  });

  onDestroy(() => {
    if (handleKey) window.removeEventListener("keydown", handleKey);
  });
</script>

<!-- Backdrop -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="backdrop"
  onclick={onClose}
></div>

<!-- Panel -->
<div class="side-panel">
  <!-- Close button -->
  <button
    onclick={onClose}
    title="Close"
    style="
      position: absolute;
      top: 12px;
      right: 12px;
      background: none;
      border: none;
      font-size: 20px;
      color: var(--text-muted);
      cursor: pointer;
      padding: 4px 8px;
      line-height: 1;
      font-family: 'DM Sans', sans-serif;
    "
  >&times;</button>

  <!-- Scrollable content -->
  <div style="overflow-y: auto; height: 100%; padding: 24px;">
    <!-- Title -->
    <div style="font-size: 18px; font-weight: 700; color: var(--text); padding-right: 32px;">
      {event.title}
    </div>

    <!-- Date + time -->
    <div style="font-size: 14px; color: var(--text-muted); margin-top: 4px;">
      {formatDayHeader(new Date(event.start))} &middot; {formatTimeRange(event.start, event.end)}
    </div>

    <!-- Platform badge -->
    {#if event.detected_platform}
      <span
        style="
          display: inline-block;
          margin-top: 8px;
          padding: 2px 8px;
          font-size: 11px;
          font-weight: 600;
          color: var(--text-muted);
          background: var(--surface-hover, rgba(255,255,255,0.06));
          border: 1px solid var(--border);
          border-radius: 10px;
        "
      >{platformLabel(event.detected_platform)}</span>
    {/if}

    <!-- Action row -->
    <div style="display: flex; align-items: center; gap: 10px; margin-top: 14px;">
      <!-- Auto-record toggle -->
      <button
        onclick={() => toggleEventAutoRecord(event.id)}
        title={event.auto_record ? "Disable auto-record" : "Enable auto-record"}
        style="
          width: 14px;
          height: 14px;
          border-radius: 50%;
          border: 2px solid {event.auto_record ? 'var(--gold)' : 'var(--text-muted)'};
          background: {event.auto_record ? 'var(--gold)' : 'transparent'};
          cursor: pointer;
          padding: 0;
          flex-shrink: 0;
        "
      ></button>

      <!-- Series toggle link -->
      {#if event.recurring_series_id}
        <button
          onclick={() => toggleSeriesAutoRecord(event.recurring_series_id!)}
          style="
            background: none;
            border: none;
            padding: 0;
            font-size: 11px;
            color: var(--text-muted);
            cursor: pointer;
            font-family: 'DM Sans', sans-serif;
            text-decoration: underline;
            text-underline-offset: 2px;
            text-decoration-color: var(--border);
          "
        >{event.auto_record ? "Disable" : "Enable"} all in series</button>
      {/if}

      <!-- Spacer -->
      <div style="flex: 1;"></div>

      <!-- Meeting join link -->
      {#if event.meeting_url}
        <button
          onclick={() => openUrl(event.meeting_url!)}
          title="Join meeting"
          style="
            background: none;
            border: none;
            padding: 0;
            font-size: 15px;
            cursor: pointer;
            color: var(--text-muted);
          "
        >&#8599;</button>
      {/if}

      <!-- Recording link -->
      {#if matchedId}
        <a
          href="#meeting/{matchedId}"
          title="View recording"
          style="
            font-size: 15px;
            color: var(--gold);
            text-decoration: none;
          "
        >&#128279;</a>
      {/if}
    </div>

    <!-- Divider -->
    <div style="border-top: 1px solid var(--border); margin: 16px 0;"></div>

    <!-- Participants -->
    {#if visibleParticipants.length > 0}
      <div style="margin-bottom: 16px;">
        <h4
          style="
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0 0 8px 0;
          "
        >Participants</h4>
        <div style="display: flex; flex-direction: column; gap: 2px;">
          {#each visibleParticipants as p}
            <button
              onclick={(e) => handleParticipantClick(p, e)}
              style="
                background: none;
                border: none;
                padding: 4px 0;
                font-size: 13px;
                color: var(--text);
                cursor: pointer;
                font-family: 'DM Sans', sans-serif;
                text-align: left;
                text-decoration: underline;
                text-decoration-color: var(--border);
                text-underline-offset: 2px;
              "
            >{p.name}{#if p.email}<span style="color: var(--text-muted); margin-left: 6px; font-size: 12px; text-decoration: none;">{p.email}</span>{/if}</button>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Event description -->
    {#if showDescription}
      <div style="margin-bottom: 16px;">
        <h4
          style="
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0 0 8px 0;
          "
        >Description</h4>
        <p style="font-size: 13px; color: var(--text-muted); margin: 0; line-height: 1.5; white-space: pre-wrap;">
          {event.description}
        </p>
      </div>
    {/if}

    <!-- Briefing -->
    <BriefingPanel
      eventId={event.id}
      title={event.title}
      participants={event.participants.map(p => p.name)}
      time={event.start}
      eventDescription={event.description ?? undefined}
    />
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.3);
    z-index: 1000;
  }

  .side-panel {
    position: fixed;
    top: 0;
    right: 0;
    width: 400px;
    height: 100%;
    background: var(--surface);
    border-left: 1px solid var(--border);
    z-index: 1001;
    font-family: 'DM Sans', sans-serif;
    animation: slide-in 0.2s ease forwards;
  }

  @keyframes slide-in {
    from {
      transform: translateX(100%);
    }
    to {
      transform: translateX(0);
    }
  }
</style>
