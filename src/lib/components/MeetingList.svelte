<script lang="ts">
  import { fly } from "svelte/transition";
  import { onMount } from "svelte";
  import type { MeetingSummary } from "../tauri";
  import { selectedIds, selectAll } from "../stores/selection";
  import { reducedMotion, motionParams } from "../reduced-motion";
  import MeetingRow from "./MeetingRow.svelte";

  interface Props {
    meetings: MeetingSummary[];
    hasMore: boolean;
    isLoading: boolean;
    onLoadMore: () => void;
    selectedId?: string | null;
    onSelect?: (id: string) => void;
    selectMode?: boolean;
    onToggleCheck?: (id: string, shiftKey: boolean) => void;
  }

  let {
    meetings,
    hasMore,
    isLoading,
    onLoadMore,
    selectedId = null,
    onSelect,
    selectMode = false,
    onToggleCheck,
  }: Props = $props();

  let initialLoad = $state(true);

  onMount(() => {
    requestAnimationFrame(() => {
      initialLoad = false;
    });
  });

  interface DateGroup {
    label: string;
    meetings: MeetingSummary[];
  }

  let groups = $derived.by((): DateGroup[] => {
    if (!meetings.length) return [];

    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today.getTime() - 86400000);

    const map = new Map<string, MeetingSummary[]>();
    const order: string[] = [];

    for (const m of meetings) {
      const d = new Date(m.date);
      const dayStart = new Date(d.getFullYear(), d.getMonth(), d.getDate());

      let label: string;
      if (dayStart.getTime() === today.getTime()) {
        label = "Today";
      } else if (dayStart.getTime() === yesterday.getTime()) {
        label = "Yesterday";
      } else {
        label = dayStart.toLocaleDateString("en-US", {
          month: "long",
          day: "numeric",
          year: dayStart.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
        });
      }

      if (!map.has(label)) {
        map.set(label, []);
        order.push(label);
      }
      map.get(label)!.push(m);
    }

    return order.map((label) => ({ label, meetings: map.get(label)! }));
  });

  function isGroupAllSelected(group: DateGroup): boolean {
    const ids = $selectedIds;
    return group.meetings.every((m) => ids.has(m.id));
  }

  function toggleGroupSelectAll(group: DateGroup) {
    const allSelected = isGroupAllSelected(group);
    if (allSelected) {
      // Deselect all in this group
      selectedIds.update((ids) => {
        const next = new Set(ids);
        group.meetings.forEach((m) => next.delete(m.id));
        return next;
      });
    } else {
      // Select all in this group
      selectAll(group.meetings.map((m) => m.id));
    }
  }
</script>

{#if isLoading && meetings.length === 0}
  <div class="flex flex-col" style="gap: 8px;">
    {#each Array(5) as _}
      <div style="padding:14px 16px;border-radius:8px;background:var(--surface);">
        <div class="skeleton" style="width:70%;height:16px;border-radius:4px;margin-bottom:8px;"></div>
        <div class="skeleton" style="width:40%;height:12px;border-radius:4px;"></div>
      </div>
    {/each}
  </div>
{:else if !meetings.length && !isLoading}
  <div
    class="flex flex-col items-center justify-center py-20"
    style="
      font-family: 'DM Sans', sans-serif;
      color: var(--text-faint);
      font-size: 15px;
    "
  >
    <p>No meetings found</p>
  </div>
{:else}
  <div class="flex flex-col" style="gap: 4px;">
    {#each groups as group}
      <div
        style="
          padding: 14px 0 6px;
          font-family: 'DM Sans', sans-serif;
          font-size: 12px;
          font-weight: 600;
          color: var(--text-faint);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          display: flex;
          align-items: center;
          gap: 8px;
        "
      >
        {#if selectMode}
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div
            onclick={() => toggleGroupSelectAll(group)}
            style="
              width: 16px;
              height: 16px;
              border-radius: 3px;
              border: 2px solid {isGroupAllSelected(group) ? 'var(--gold)' : 'var(--border)'};
              background: {isGroupAllSelected(group) ? 'var(--gold)' : 'transparent'};
              cursor: pointer;
              display: flex;
              align-items: center;
              justify-content: center;
              flex-shrink: 0;
              transition: all 120ms ease;
            "
          >
            {#if isGroupAllSelected(group)}
              <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="var(--bg)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M2.5 6L5 8.5L9.5 3.5" />
              </svg>
            {/if}
          </div>
        {/if}
        {group.label}
      </div>
      {#each group.meetings as meeting, i (meeting.id)}
        <div
          in:fly={initialLoad
            ? motionParams({ y: 20, duration: 250, delay: Math.min(i, 10) * 50 }, $reducedMotion)
            : { duration: 0 }}
        >
          <MeetingRow
            {meeting}
            isSelected={selectedId === meeting.id}
            {onSelect}
            {selectMode}
            isChecked={$selectedIds.has(meeting.id)}
            {onToggleCheck}
          />
        </div>
      {/each}
    {/each}
  </div>

  {#if hasMore}
    <div class="flex justify-center py-4">
      <button
        onclick={onLoadMore}
        disabled={isLoading}
        style="
          padding: 6px 20px;
          border-radius: 6px;
          border: none;
          background: var(--surface);
          color: var(--gold);
          font-family: 'DM Sans', sans-serif;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          transition: background 120ms ease;
        "
        onmouseenter={(e) => {
          const el = e.currentTarget as HTMLElement;
          el.style.background = 'var(--raised)';
        }}
        onmouseleave={(e) => {
          const el = e.currentTarget as HTMLElement;
          el.style.background = 'var(--surface)';
        }}
      >
        {isLoading ? "Loading..." : "Load more"}
      </button>
    </div>
  {/if}

  {#if isLoading && !hasMore}
    <div class="flex justify-center py-4">
      <span class="spinner"></span>
    </div>
  {/if}
{/if}

<style>
  .spinner {
    display: inline-block;
    width: 18px;
    height: 18px;
    border: 2px solid var(--border);
    border-top-color: var(--gold);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .skeleton {
    background: linear-gradient(90deg, var(--surface) 25%, var(--raised) 50%, var(--surface) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s ease-in-out infinite;
  }

  @keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
</style>
