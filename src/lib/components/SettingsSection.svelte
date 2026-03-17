<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    title: string;
    children: Snippet;
  }

  let { title, children }: Props = $props();
</script>

<section>
  <h2 class="text-lg font-semibold text-gray-800 mb-4">{title}</h2>
  <div class="border border-gray-200 rounded-lg p-4 bg-white space-y-4">
    {@render children()}
  </div>
</section>
