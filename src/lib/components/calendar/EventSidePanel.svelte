<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { fly, fade } from "svelte/transition";
  import { get } from "svelte/store";
  import { reducedMotion, motionParams } from "../../reduced-motion";
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

  // Participants filtered to exclude current user (check name and email against userName)
  let visibleParticipants = $derived.by(() => {
    const userName = get(settings).userName?.toLowerCase() ?? "";
    if (!userName) return event.participants;
    return event.participants.filter((p) => {
      if (p.name.toLowerCase() === userName) return false;
      if (p.email && p.email.toLowerCase() === userName) return false;
      return true;
    });
  });

  const COLLAPSED_COUNT = 4;
  let participantsExpanded = $state(false);
  let shownParticipants = $derived(
    participantsExpanded ? visibleParticipants : visibleParticipants.slice(0, COLLAPSED_COUNT)
  );
  let hiddenCount = $derived(Math.max(0, visibleParticipants.length - COLLAPSED_COUNT));

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
  transition:fade={motionParams({ duration: 150 }, $reducedMotion)}
></div>

<!-- Panel -->
<div class="side-panel" transition:fly={motionParams({ x: 400, duration: 200 }, $reducedMotion)}>
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
      <span style="font-size: 12px; color: var(--text-muted);">Auto-record</span>

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
          style="
            background: none;
            border: none;
            padding: 2px 8px;
            font-size: 12px;
            cursor: pointer;
            color: var(--blue, #58a6ff);
            font-family: 'DM Sans', sans-serif;
          "
        >Join &#8599;</button>
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
        <button
          onclick={() => { if (hiddenCount > 0) participantsExpanded = !participantsExpanded; }}
          style="
            display: flex;
            align-items: center;
            gap: 4px;
            width: 100%;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0 0 8px 0;
            background: none;
            border: none;
            padding: 0;
            cursor: {hiddenCount > 0 ? 'pointer' : 'default'};
            font-family: 'DM Sans', sans-serif;
          "
        >
          Participants ({visibleParticipants.length})
          {#if hiddenCount > 0}
            <span style="
              font-size: 10px;
              margin-left: auto;
              transition: transform 0.15s;
              transform: rotate({participantsExpanded ? '-90deg' : '0deg'});
            ">&#9664;</span>
          {/if}
        </button>
        <div style="display: flex; flex-wrap: wrap; gap: 6px;">
          {#each shownParticipants as p}
            <button
              onclick={(e) => handleParticipantClick(p, e)}
              style="
                background: var(--surface-hover, rgba(255,255,255,0.06));
                border: 1px solid var(--border);
                border-radius: 14px;
                padding: 4px 10px;
                font-size: 12px;
                color: var(--text);
                cursor: pointer;
                font-family: 'DM Sans', sans-serif;
                white-space: nowrap;
              "
            >{p.name}</button>
          {/each}
          {#if !participantsExpanded && hiddenCount > 0}
            <button
              onclick={() => participantsExpanded = true}
              style="
                background: none;
                border: 1px dashed var(--border);
                border-radius: 14px;
                padding: 4px 10px;
                font-size: 12px;
                color: var(--text-muted);
                cursor: pointer;
                font-family: 'DM Sans', sans-serif;
                white-space: nowrap;
              "
            >+{hiddenCount} more</button>
          {/if}
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
    z-index: 40;
  }

  .side-panel {
    position: fixed;
    top: 0;
    right: 0;
    width: 400px;
    height: 100%;
    background: var(--surface);
    border-left: 1px solid var(--border);
    z-index: 41;
    font-family: 'DM Sans', sans-serif;
  }
</style>
