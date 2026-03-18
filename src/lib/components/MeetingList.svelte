<script lang="ts">
  import type { MeetingSummary } from "../tauri";
  import MeetingRow from "./MeetingRow.svelte";

  interface Props {
    meetings: MeetingSummary[];
    hasMore: boolean;
    isLoading: boolean;
    onLoadMore: () => void;
  }

  let { meetings, hasMore, isLoading, onLoadMore }: Props = $props();

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

{#if !meetings.length && !isLoading}
  <div
    class="flex flex-col items-center justify-center py-20"
    style="
      font-family: 'DM Sans', sans-serif;
      color: #585650;
      font-size: 13.5px;
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
          font-size: 10.5px;
          font-weight: 600;
          color: #585650;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        "
      >
        {group.label}
      </div>
      {#each group.meetings as meeting (meeting.id)}
        <MeetingRow {meeting} />
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
          background: #242422;
          color: #A8A078;
          font-family: 'DM Sans', sans-serif;
          font-size: 12.5px;
          font-weight: 600;
          cursor: pointer;
          transition: background 120ms ease;
        "
        onmouseenter={(e) => {
          const el = e.currentTarget as HTMLElement;
          el.style.background = '#2B2B28';
        }}
        onmouseleave={(e) => {
          const el = e.currentTarget as HTMLElement;
          el.style.background = '#242422';
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
    border: 2px solid #464440;
    border-top-color: #A8A078;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }
</style>
