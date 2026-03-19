<script lang="ts">
  import { fly } from "svelte/transition";
  import { toasts, removeToast } from "../stores/toasts";

  function borderColor(type: "success" | "error" | "info"): string {
    if (type === "error") return "var(--red)";
    if (type === "success") return "var(--green)";
    return "var(--border)";
  }
</script>

{#if $toasts.length > 0}
  <div
    style="
      position: fixed;
      bottom: 20px;
      right: 20px;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      gap: 8px;
      pointer-events: none;
    "
  >
    {#each $toasts as toast (toast.id)}
      <div
        transition:fly={{ x: 100, duration: 300 }}
        style="
          pointer-events: auto;
          max-width: 360px;
          padding: 12px 36px 12px 14px;
          border-radius: 8px;
          background: var(--raised);
          border: 1px solid {borderColor(toast.type)};
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
          font-family: 'DM Sans', sans-serif;
          font-size: 13.5px;
          color: var(--text);
          position: relative;
        "
      >
        {toast.message}
        <button
          onclick={() => removeToast(toast.id)}
          aria-label="Dismiss"
          style="
            position: absolute;
            top: 8px;
            right: 8px;
            background: none;
            border: none;
            color: var(--text-muted);
            font-size: 16px;
            line-height: 1;
            cursor: pointer;
            padding: 2px 4px;
          "
        >&times;</button>
      </div>
    {/each}
  </div>
{/if}
