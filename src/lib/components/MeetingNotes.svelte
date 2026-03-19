<script lang="ts">
  import { renderMarkdown } from "../markdown";

  interface Props {
    content: string | null;
  }

  let { content }: Props = $props();

  let html = $derived(content ? renderMarkdown(content) : null);
</script>

{#if html}
  <div class="meeting-notes" style="
    font-family: 'DM Sans', sans-serif;
    font-size: 15px;
    color: var(--text-secondary);
    line-height: 1.65;
    padding: 16px 0;
  ">
    {@html html}
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
    No meeting note
  </div>
{/if}

<style>
  .meeting-notes :global(h1),
  .meeting-notes :global(h2),
  .meeting-notes :global(h3),
  .meeting-notes :global(h4) {
    font-family: 'Source Serif 4', serif;
    color: var(--text);
    margin: 1.2em 0 0.4em;
  }

  .meeting-notes :global(h1) { font-size: 20px; font-weight: 700; }
  .meeting-notes :global(h2) { font-size: 18px; font-weight: 600; }
  .meeting-notes :global(h3) { font-size: 15.5px; font-weight: 600; }

  .meeting-notes :global(p) {
    margin: 0.5em 0;
  }

  .meeting-notes :global(ul),
  .meeting-notes :global(ol) {
    padding-left: 1.5em;
    margin: 0.5em 0;
  }

  .meeting-notes :global(li) {
    margin: 0.25em 0;
  }

  .meeting-notes :global(code) {
    background: var(--surface);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 13.5px;
  }

  .meeting-notes :global(pre) {
    background: var(--surface);
    padding: 12px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 13.5px;
  }

  .meeting-notes :global(blockquote) {
    border-left: 3px solid var(--border);
    margin: 0.5em 0;
    padding-left: 12px;
    color: var(--text-muted);
  }

  .meeting-notes :global(a) {
    color: var(--gold);
    text-decoration: none;
  }

  .meeting-notes :global(a:hover) {
    color: var(--gold-hover);
    text-decoration: underline;
  }

  .meeting-notes :global(.wikilink) {
    color: var(--gold);
    text-decoration: none;
    cursor: pointer;
  }

  .meeting-notes :global(.wikilink:hover) {
    color: var(--gold-hover);
    text-decoration: underline;
  }

  .meeting-notes :global(img) {
    max-width: 100%;
    border-radius: 8px;
    margin: 8px 0;
  }
</style>
