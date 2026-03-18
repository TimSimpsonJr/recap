<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    title: string;
    children: Snippet;
  }

  let { title, children }: Props = $props();
</script>

<section>
  <h2 style="font-family:'Source Serif 4',serif;font-size:16px;font-weight:600;color:#D8D5CE;margin-bottom:12px;">
    {title}
  </h2>
  <div style="background:#242422;border-radius:8px;padding:16px;display:flex;flex-direction:column;gap:16px;">
    {@render children()}
  </div>
</section>
