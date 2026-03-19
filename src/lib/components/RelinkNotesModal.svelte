<script lang="ts">
  import Modal from "./Modal.svelte";
  import { relinkVaultNotes } from "../tauri";
  import { open } from "@tauri-apps/plugin-dialog";

  interface Props {
    missingPaths: string[];
    onclose: () => void;
    onrelinked?: (relinked: [string, string][]) => void;
  }

  let { missingPaths, onclose, onrelinked }: Props = $props();

  // Track status per path: "missing" | "locating" | found path string
  let statuses = $state<Map<string, string>>(new Map(
    missingPaths.map(p => [p, "missing"])
  ));

  // Collect all successful relinks to report back
  let allRelinked = $state<[string, string][]>([]);

  let missingCount = $derived(
    Array.from(statuses.values()).filter(s => s === "missing").length
  );
  let allResolved = $derived(missingCount === 0);

  function filename(path: string): string {
    const sep = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
    return sep >= 0 ? path.substring(sep + 1) : path;
  }

  function dirpath(path: string): string {
    const sep = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
    return sep >= 0 ? path.substring(0, sep) : "";
  }

  async function locateNote(expectedPath: string) {
    statuses.set(expectedPath, "locating");
    statuses = new Map(statuses);

    try {
      const selected = await open({
        title: "Locate vault note",
        filters: [{ name: "Markdown", extensions: ["md"] }],
      });

      if (!selected) {
        statuses.set(expectedPath, "missing");
        statuses = new Map(statuses);
        return;
      }

      const foundPath = selected as string;

      // Mark the one the user located
      statuses.set(expectedPath, foundPath);
      allRelinked.push([expectedPath, foundPath]);

      // Try to auto-relink the rest
      const otherMissing = Array.from(statuses.entries())
        .filter(([_, status]) => status === "missing")
        .map(([path, _]) => path);

      if (otherMissing.length > 0) {
        const relinked = await relinkVaultNotes(foundPath, expectedPath, otherMissing);
        for (const [expected, found] of relinked) {
          statuses.set(expected, found);
          allRelinked.push([expected, found]);
        }
      }

      statuses = new Map(statuses);
    } catch (e) {
      statuses.set(expectedPath, "missing");
      statuses = new Map(statuses);
    }
  }

  function handleDone() {
    if (onrelinked && allRelinked.length > 0) {
      onrelinked(allRelinked);
    }
    onclose();
  }
</script>

<Modal title="Missing Vault Notes" onclose={onclose}>
  <div
    style="
      font-family: 'DM Sans', sans-serif;
      font-size: 14px;
      color: var(--text-secondary);
      margin-bottom: 16px;
    "
  >
    {missingPaths.length} meeting note{missingPaths.length !== 1 ? "s" : ""} could not be found
    at {missingPaths.length !== 1 ? "their" : "its"} expected location{missingPaths.length !== 1 ? "s" : ""}.
    Locate one and the rest may be found automatically.
  </div>

  <div style="display: flex; flex-direction: column; gap: 4px; margin-bottom: 20px;">
    {#each missingPaths as expectedPath}
      {@const status = statuses.get(expectedPath) ?? "missing"}
      <div
        style="
          padding: 10px 12px;
          border-radius: 6px;
          background: var(--raised);
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
        "
      >
        <div style="flex: 1; min-width: 0; overflow: hidden;">
          <div
            style="
              font-size: 13px;
              font-weight: 500;
              color: {status !== 'missing' && status !== 'locating' ? 'var(--green)' : 'var(--text)'};
              white-space: nowrap;
              overflow: hidden;
              text-overflow: ellipsis;
            "
          >
            {filename(expectedPath)}
          </div>
          <div
            style="
              font-size: 11px;
              color: var(--text-faint);
              white-space: nowrap;
              overflow: hidden;
              text-overflow: ellipsis;
              margin-top: 2px;
            "
            title={expectedPath}
          >
            {#if status !== "missing" && status !== "locating"}
              Found: {dirpath(status)}
            {:else}
              Expected: {dirpath(expectedPath)}
            {/if}
          </div>
        </div>

        {#if status === "missing"}
          <button
            onclick={() => locateNote(expectedPath)}
            style="
              padding: 5px 12px;
              border-radius: 6px;
              border: 1px solid var(--border);
              background: transparent;
              color: var(--blue);
              font-family: 'DM Sans', sans-serif;
              font-size: 12px;
              font-weight: 500;
              cursor: pointer;
              white-space: nowrap;
              flex-shrink: 0;
            "
          >
            Locate
          </button>
        {:else if status === "locating"}
          <span
            style="
              font-size: 12px;
              color: var(--text-muted);
              font-style: italic;
              flex-shrink: 0;
            "
          >
            Browsing...
          </span>
        {:else}
          <span
            style="
              font-size: 12px;
              color: var(--green);
              font-weight: 600;
              flex-shrink: 0;
            "
          >
            Found!
          </span>
        {/if}
      </div>
    {/each}
  </div>

  <div style="display: flex; justify-content: flex-end; gap: 8px;">
    <button
      onclick={onclose}
      style="
        padding: 7px 16px;
        border-radius: 6px;
        border: 1px solid var(--border);
        background: transparent;
        color: var(--text-muted);
        font-family: 'DM Sans', sans-serif;
        font-size: 13px;
        cursor: pointer;
      "
    >
      Skip
    </button>
    <button
      onclick={handleDone}
      disabled={!allResolved && allRelinked.length === 0}
      style="
        padding: 7px 16px;
        border-radius: 6px;
        border: none;
        background: var(--gold);
        color: var(--bg);
        font-family: 'DM Sans', sans-serif;
        font-size: 13px;
        font-weight: 600;
        cursor: {!allResolved && allRelinked.length === 0 ? 'not-allowed' : 'pointer'};
        opacity: {!allResolved && allRelinked.length === 0 ? '0.5' : '1'};
      "
    >
      {allResolved ? "Done" : "Done"}
    </button>
  </div>
</Modal>
