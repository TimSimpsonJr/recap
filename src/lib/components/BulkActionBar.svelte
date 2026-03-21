<script lang="ts">
  import { fly } from "svelte/transition";
  import { selectedCount } from "../stores/selection";

  interface Props {
    onDelete: () => void;
    onReprocess: () => void;
    onFixSpeakers: () => void;
    reprocessDisabled?: boolean;
  }

  let { onDelete, onReprocess, onFixSpeakers, reprocessDisabled = false }: Props = $props();
</script>

{#if $selectedCount > 0}
  <div
    transition:fly={{ y: 60, duration: 300 }}
    style="
      position: sticky;
      bottom: 0;
      z-index: 50;
      background: var(--raised);
      border-top: 1px solid var(--border);
      padding: 12px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      font-family: 'DM Sans', sans-serif;
    "
  >
    <span
      style="
        font-size: 14px;
        font-weight: 600;
        color: var(--gold);
        white-space: nowrap;
      "
    >
      {$selectedCount} selected
    </span>

    <div style="display: flex; gap: 8px;">
      <button
        onclick={onReprocess}
        disabled={reprocessDisabled}
        style="
          padding: 7px 16px;
          border-radius: 6px;
          border: 1px solid var(--border);
          background: var(--surface);
          color: {reprocessDisabled ? 'var(--text-faint)' : 'var(--text)'};
          font-family: 'DM Sans', sans-serif;
          font-size: 13px;
          font-weight: 600;
          cursor: {reprocessDisabled ? 'not-allowed' : 'pointer'};
          opacity: {reprocessDisabled ? '0.5' : '1'};
          transition: background 120ms ease;
        "
        onmouseenter={(e) => {
          if (!reprocessDisabled) {
            const el = e.currentTarget as HTMLElement;
            el.style.background = 'var(--raised)';
          }
        }}
        onmouseleave={(e) => {
          const el = e.currentTarget as HTMLElement;
          el.style.background = 'var(--surface)';
        }}
      >
        Reprocess
      </button>

      <button
        onclick={onFixSpeakers}
        style="
          padding: 7px 16px;
          border-radius: 6px;
          border: 1px solid var(--border);
          background: var(--surface);
          color: var(--text);
          font-family: 'DM Sans', sans-serif;
          font-size: 13px;
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
        Fix Speakers
      </button>

      <button
        onclick={onDelete}
        style="
          padding: 7px 16px;
          border-radius: 6px;
          border: 1px solid rgba(239, 83, 74, 0.3);
          background: rgba(239, 83, 74, 0.1);
          color: var(--red);
          font-family: 'DM Sans', sans-serif;
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
          transition: background 120ms ease;
        "
        onmouseenter={(e) => {
          const el = e.currentTarget as HTMLElement;
          el.style.background = 'rgba(239, 83, 74, 0.2)';
        }}
        onmouseleave={(e) => {
          const el = e.currentTarget as HTMLElement;
          el.style.background = 'rgba(239, 83, 74, 0.1)';
        }}
      >
        Delete
      </button>
    </div>
  </div>
{/if}
