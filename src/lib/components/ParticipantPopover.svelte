<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { getParticipantInfo, type ParticipantInfo } from "../tauri";
  import { writeText } from "@tauri-apps/plugin-clipboard-manager";
  import { activeFilters } from "../stores/meetings";

  interface Props {
    name: string;
    email: string | null;
    anchorRect: DOMRect;
    onclose: () => void;
  }

  let { name, email, anchorRect, onclose }: Props = $props();

  let info: ParticipantInfo | null = $state(null);
  let loading = $state(true);
  let copied = $state(false);
  let popoverEl: HTMLDivElement | undefined = $state();

  // Position: below anchor, flip up if near bottom
  let top = $state(0);
  let left = $state(0);

  function updatePosition() {
    if (!popoverEl) return;
    const rect = popoverEl.getBoundingClientRect();
    const viewportH = window.innerHeight;
    const viewportW = window.innerWidth;

    let t = anchorRect.bottom + 6;
    let l = anchorRect.left;

    // Flip up if not enough space below
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

  // Event handlers stored for cleanup
  let handleKey: ((e: KeyboardEvent) => void) | null = null;
  let handleClick: ((e: MouseEvent) => void) | null = null;
  let clickTimeout: ReturnType<typeof setTimeout> | null = null;

  onMount(async () => {
    try {
      info = await getParticipantInfo(name, email);
    } catch (err) {
      console.warn("Failed to load participant info:", err);
      info = { name, email, company: null, recent_meetings: [] };
    } finally {
      loading = false;
    }

    // Position after render
    requestAnimationFrame(updatePosition);

    // Close on Escape
    handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onclose();
    };
    window.addEventListener("keydown", handleKey);

    // Close on click outside
    // Delay to avoid the opening click from immediately closing
    handleClick = (e: MouseEvent) => {
      if (popoverEl && !popoverEl.contains(e.target as Node)) {
        onclose();
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

  async function copyEmail() {
    if (!info?.email) return;
    try {
      await writeText(info.email);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch (err) {
      console.warn("Failed to copy email:", err);
    }
  }

  function navigateToParticipant() {
    if (!info) return;
    activeFilters.set({
      companies: [],
      participants: [info.name],
      platforms: [],
    });
    window.location.hash = "#dashboard";
    onclose();
  }

  function navigateToCompany() {
    if (!info?.company) return;
    activeFilters.set({
      companies: [info.company],
      participants: [],
      platforms: [],
    });
    window.location.hash = "#dashboard";
    onclose();
  }

  function navigateToMeeting(meetingId: string) {
    window.location.hash = `#meeting/${meetingId}`;
    onclose();
  }

  function formatShortDate(iso: string): string {
    if (!iso) return "";
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  }
</script>

<div
  bind:this={popoverEl}
  style="
    position: fixed;
    top: {top}px;
    left: {left}px;
    width: 300px;
    background: var(--raised, var(--surface));
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    z-index: 1100;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    font-family: 'DM Sans', sans-serif;
  "
>
  {#if loading}
    <div style="color: var(--text-muted); font-size: 13px;">Loading...</div>
  {:else if info}
    <!-- Name -->
    <div style="font-size: 15px; font-weight: 600; color: var(--text);">
      {info.name}
    </div>

    <!-- Company -->
    {#if info.company}
      <button
        onclick={navigateToCompany}
        style="
          display: block;
          font-size: 13px;
          color: var(--text-muted);
          margin-top: 2px;
          background: none;
          border: none;
          padding: 0;
          cursor: pointer;
          font-family: 'DM Sans', sans-serif;
          text-decoration: underline;
          text-decoration-color: var(--border);
          text-underline-offset: 2px;
        "
      >{info.company}</button>
    {/if}

    <!-- Email -->
    {#if info.email}
      <div style="display: flex; align-items: center; gap: 6px; margin-top: 8px;">
        <span style="font-size: 13px; color: var(--text-secondary, var(--text-muted));">
          {info.email}
        </span>
        <button
          onclick={copyEmail}
          title="Copy email"
          style="
            background: none;
            border: none;
            cursor: pointer;
            padding: 2px;
            color: var(--text-muted);
            font-size: 13px;
            position: relative;
          "
        >
          {copied ? "✓" : "⧉"}
          {#if copied}
            <span
              style="
                position: absolute;
                top: -24px;
                left: 50%;
                transform: translateX(-50%);
                font-size: 11px;
                color: var(--green);
                white-space: nowrap;
              "
            >Copied!</span>
          {/if}
        </button>
      </div>
    {/if}

    <!-- Recent meetings -->
    {#if info.recent_meetings.length > 0}
      <div
        style="
          border-top: 1px solid var(--border);
          margin-top: 12px;
          padding-top: 10px;
        "
      >
        {#each info.recent_meetings as meeting}
          <button
            onclick={() => navigateToMeeting(meeting.id)}
            style="
              display: block;
              width: 100%;
              text-align: left;
              background: none;
              border: none;
              padding: 4px 0;
              cursor: pointer;
              font-family: 'DM Sans', sans-serif;
            "
          >
            <span style="font-size: 13px; color: var(--text);">
              {meeting.title}
            </span>
            <span style="font-size: 12px; color: var(--text-faint); margin-left: 6px;">
              {formatShortDate(meeting.date)}
            </span>
          </button>
        {/each}

        <button
          onclick={navigateToParticipant}
          style="
            display: block;
            font-size: 12.5px;
            color: var(--gold);
            margin-top: 6px;
            background: none;
            border: none;
            padding: 0;
            cursor: pointer;
            font-family: 'DM Sans', sans-serif;
          "
        >See all in Meetings →</button>
      </div>
    {/if}
  {/if}
</div>
