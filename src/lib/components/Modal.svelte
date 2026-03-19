<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    title: string;
    onclose: () => void;
    children: Snippet;
  }

  let { title, onclose, children }: Props = $props();

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") onclose();
  }

  function onOverlayClick(e: MouseEvent) {
    if (e.target === e.currentTarget) onclose();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="modal-overlay"
  onclick={onOverlayClick}
  style="position:fixed;inset:0;z-index:50;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.6);"
>
  <div
    class="modal-card"
    style="background:var(--surface);border-radius:12px;max-width:480px;width:90%;max-height:85vh;overflow-y:auto;padding:24px;position:relative;box-shadow:0 4px 24px rgba(0,0,0,0.5);"
  >
    <button
      onclick={onclose}
      style="position:absolute;top:12px;right:12px;background:none;border:none;color:var(--text-muted);font-size:20px;cursor:pointer;padding:4px 8px;line-height:1;"
      aria-label="Close"
    >
      &times;
    </button>

    <h2 style="font-family:'Source Serif 4',serif;font-size:18px;font-weight:600;color:var(--text);margin:0 0 16px 0;">
      {title}
    </h2>

    {@render children()}
  </div>
</div>
