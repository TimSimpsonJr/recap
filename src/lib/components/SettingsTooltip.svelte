<script lang="ts">
  interface Props { text: string; }
  let { text }: Props = $props();
  let visible = $state(false);
</script>

<span
  role="img"
  aria-label={text}
  style="position:relative;display:inline-flex;align-items:center;margin-left:6px;cursor:help;"
  onmouseenter={() => visible = true}
  onmouseleave={() => visible = false}
>
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="var(--text-faint)" stroke-width="1.5">
    <circle cx="7" cy="7" r="6"/>
    <path d="M5.5 5.5a1.5 1.5 0 1 1 2.12 1.37c-.42.24-.62.63-.62 1.13M7 10h.01"/>
  </svg>
  {#if visible}
    <div style="
      position:absolute;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);
      padding:8px 12px;border-radius:6px;background:var(--raised);border:1px solid var(--border);
      color:var(--text-secondary);font-size:12px;font-family:'DM Sans',sans-serif;
      white-space:normal;max-width:250px;z-index:100;box-shadow:0 4px 12px rgba(0,0,0,0.3);
      pointer-events:none;
    ">
      {text}
    </div>
  {/if}
</span>
