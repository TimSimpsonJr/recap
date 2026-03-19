<script lang="ts">
  import type { Screenshot } from "../tauri";
  import { assetUrl } from "../assets";

  interface Props {
    screenshots: Screenshot[];
  }

  let { screenshots }: Props = $props();
</script>

{#if screenshots.length > 0}
  <div
    class="grid gap-3 py-4"
    style="grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));"
  >
    {#each screenshots as shot, i}
      <div
        class="overflow-hidden"
        style="
          border-radius: 8px;
          background: var(--surface);
        "
      >
        <img
          src={assetUrl(shot.path)}
          alt={shot.caption ?? `Screenshot ${i + 1}`}
          style="
            width: 100%;
            display: block;
            object-fit: cover;
          "
          loading="lazy"
        />
        {#if shot.caption}
          <div
            style="
              padding: 8px 10px;
              font-family: 'DM Sans', sans-serif;
              font-size: 13.5px;
              color: var(--text-muted);
              line-height: 1.4;
            "
          >
            {shot.caption}
          </div>
        {/if}
      </div>
    {/each}
  </div>
{:else}
  <div
    class="flex items-center justify-center py-16"
    style="
      font-family: 'DM Sans', sans-serif;
      font-size: 15px;
      color: var(--text-faint);
    "
  >
    No screenshots
  </div>
{/if}
