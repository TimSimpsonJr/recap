<script lang="ts">
  interface Props {
    lines?: number;
    showPlayer?: boolean;
  }
  let { lines = 4, showPlayer = false }: Props = $props();
</script>

<div style="padding: 16px; display: flex; flex-direction: column; gap: 12px;">
  {#if showPlayer}
    <div class="skeleton" style="width:100%;height:200px;border-radius:8px;"></div>
  {/if}
  <div class="skeleton" style="width:60%;height:20px;border-radius:4px;"></div>
  {#each Array(lines) as _, i}
    <div class="skeleton" style="width:{85 - i * 10}%;height:14px;border-radius:4px;"></div>
  {/each}
</div>

<style>
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
