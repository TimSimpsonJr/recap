<script lang="ts">
  import { fly } from "svelte/transition";
  import type { MeetingSummary } from "../tauri";
  import MeetingRow from "./MeetingRow.svelte";

  interface Props {
    meetings: MeetingSummary[];
    hasMore: boolean;
    isLoading: boolean;
    onLoadMore: () => void;
    selectedId?: string | null;
    onSelect?: (id: string) => void;
  }

  let { meetings, hasMore, isLoading, onLoadMore, selectedId = null, onSelect }: Props = $props();

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
        "
      >
        {group.label}
      </div>
      {#each group.meetings as meeting, i (meeting.id)}
        <div transition:fly={{ y: 10, duration: 200, delay: i * 30 }}>
          <MeetingRow
            {meeting}
            isSelected={selectedId === meeting.id}
            {onSelect}
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
