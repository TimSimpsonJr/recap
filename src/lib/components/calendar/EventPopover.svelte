<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { scale } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { get } from "svelte/store";
  import { settings } from "../../stores/settings";
  import { reducedMotion, motionParams } from "../../reduced-motion";
  import {
    toggleEventAutoRecord,
    toggleSeriesAutoRecord,
  } from "../../stores/calendar";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { platformLabel, formatTimeRange } from "../../calendar-utils";
  import type { CalendarEvent } from "../../tauri";

  interface Props {
    event: CalendarEvent;
    matchedId: string | null;
    anchorRect: DOMRect;
    onClose: () => void;
    onOpenSidePanel: () => void;
    onOpenPopover: (name: string, email: string | null, rect: DOMRect) => void;
  }

  let { event, matchedId, anchorRect, onClose, onOpenSidePanel, onOpenPopover }: Props = $props();

  let popoverEl: HTMLDivElement | undefined = $state();
  let top = $state(0);
  let left = $state(0);

  function updatePosition() {
    if (!popoverEl) return;
    const rect = popoverEl.getBoundingClientRect();
    const viewportH = window.innerHeight;
    const viewportW = window.innerWidth;

    let t = anchorRect.bottom + 6;
    let l = anchorRect.left;

    // Flip above if not enough space below
    const popH = rect.height;
    const popW = rect.width;
    if (t + popH > viewportH - 16) {
      t = anchorRect.top - popH - 6;
    }
    // Clamp horizontally
    if (l + popW > viewportW - 16) {
      l = viewportW - popW - 16;
    }
    if (l < 16) l = 16;

    top = t;
    left = l;
  }

  // Participants filtered to exclude current user
  let visibleParticipants = $derived.by(() => {
    const userName = get(settings).userName?.toLowerCase() ?? "";
    if (!userName) return event.participants;
    return event.participants.filter((p) => {
      if (p.name.toLowerCase() === userName) return false;
      if (p.email && p.email.toLowerCase() === userName) return false;
      return true;
    });
  });

  // Show up to 8 in popover, rest as overflow
  let shownParticipants = $derived(visibleParticipants.slice(0, 8));
  let overflowCount = $derived(
    Math.max(0, visibleParticipants.length - 8)
  );

  // Dismiss handlers
  let handleKey: ((e: KeyboardEvent) => void) | null = null;
  let handleClick: ((e: MouseEvent) => void) | null = null;
  let clickTimeout: ReturnType<typeof setTimeout> | null = null;

  onMount(() => {
    requestAnimationFrame(updatePosition);

    handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);

    handleClick = (e: MouseEvent) => {
      if (popoverEl && !popoverEl.contains(e.target as Node)) {
        onClose();
      }
    };
    clickTimeout = setTimeout(() => {
      if (handleClick) window.addEventListener("click", handleClick);
    }, 0);
  });

  onDestroy(() => {
    if (handleKey) window.removeEventListener("keydown", handleKey);
    if (handleClick) window.removeEventListener("click", handleClick);
    if (clickTimeout) clearTimeout(clickTimeout);
  });

  function handleParticipantClick(
    p: { name: string; email: string | null },
    e: MouseEvent
  ) {
    const btn = e.currentTarget as HTMLElement;
    const rect = btn.getBoundingClientRect();
    onOpenPopover(p.name, p.email, rect);
  }
</script>

<div
  bind:this={popoverEl}
  in:scale={motionParams({ start: 0.9, duration: 150, easing: cubicOut }, $reducedMotion)}
  out:scale={motionParams({ start: 0.95, duration: 100 }, $reducedMotion)}
  style="
    position: fixed;
    top: {top}px;
    left: {left}px;
    min-width: 300px;
    max-width: 380px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 18px;
    z-index: 1000;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    font-family: 'DM Sans', sans-serif;
    transform-origin: {anchorRect.left < window.innerWidth / 2 ? 'top left' : 'top right'};
  "
>
  <!-- Header: Title + platform -->
  <div style="display: flex; align-items: flex-start; gap: 8px;">
    <div style="flex: 1; min-width: 0;">
      <div style="font-size: 15px; font-weight: 700; color: var(--text);">
        {event.title}
      </div>
      <div style="font-size: 13px; color: var(--text-muted); margin-top: 2px;">
        {formatTimeRange(event.start, event.end)}
      </div>
    </div>
    {#if event.detected_platform}
      <span
        style="
          flex-shrink: 0;
          padding: 2px 8px;
          font-size: 11px;
          font-weight: 600;
          color: var(--text-muted);
          background: var(--surface-hover, rgba(255,255,255,0.06));
          border: 1px solid var(--border);
          border-radius: 10px;
          margin-top: 2px;
        "
      >{platformLabel(event.detected_platform)}</span>
    {/if}
  </div>

  <!-- Divider -->
  <div style="border-top: 1px solid var(--border); margin: 10px 0;"></div>

  <!-- Action row -->
  <div style="display: flex; align-items: center; gap: 10px;">
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

  <!-- Participants -->
  {#if shownParticipants.length > 0}
    <div style="margin-top: 12px;">
      <div style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px;">
        Participants ({visibleParticipants.length})
      </div>
      <div style="display: flex; flex-direction: column; gap: 1px;">
        {#each shownParticipants as p}
          <button
            onclick={(e) => handleParticipantClick(p, e)}
            style="
              background: none;
              border: none;
              padding: 3px 0;
              font-size: 13px;
              color: var(--text);
              cursor: pointer;
              font-family: 'DM Sans', sans-serif;
              text-align: left;
            "
          >{p.name}</button>
        {/each}
        {#if overflowCount > 0}
          <button
            onclick={onOpenSidePanel}
            style="
              background: none;
              border: none;
              padding: 3px 0;
              font-size: 12px;
              color: var(--text-muted);
              cursor: pointer;
              font-family: 'DM Sans', sans-serif;
              text-align: left;
            "
          >+{overflowCount} more</button>
        {/if}
      </div>
    </div>
  {/if}

  <!-- See details -->
  <button
    onclick={onOpenSidePanel}
    style="
      display: block;
      margin-top: 12px;
      background: none;
      border: none;
      padding: 0;
      font-size: 13px;
      color: var(--gold);
      cursor: pointer;
      font-family: 'DM Sans', sans-serif;
    "
  >See details &#8594;</button>
</div>
