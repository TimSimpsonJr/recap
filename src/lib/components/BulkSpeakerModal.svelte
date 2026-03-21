<script lang="ts">
  import { onMount } from "svelte";
  import Modal from "./Modal.svelte";
  import { getSpeakersForMeetings, bulkRenameSpeaker } from "../tauri";
  import { addToast } from "../stores/toasts";

  interface Props {
    selectedIds: Set<string>;
    onclose: () => void;
  }

  let { selectedIds, onclose }: Props = $props();

  let speakers = $state<[string, number][]>([]);
  let loading = $state(true);
  let editingSpeaker = $state<string | null>(null);
  let newName = $state("");
  let renaming = $state(false);

  onMount(async () => {
    try {
      speakers = await getSpeakersForMeetings(Array.from(selectedIds));
    } catch (e) {
      addToast("Failed to load speakers", "error");
    } finally {
      loading = false;
    }
  });

  async function handleRename() {
    if (!editingSpeaker || !newName.trim()) return;
    renaming = true;
    try {
      const count = await bulkRenameSpeaker(
        editingSpeaker,
        newName.trim(),
        Array.from(selectedIds)
      );
      addToast(`Renamed speaker in ${count} meeting${count !== 1 ? "s" : ""}`, "success");
      // Update local list
      speakers = speakers
        .map(([name, cnt]) => {
          if (name === editingSpeaker) return [newName.trim(), cnt] as [string, number];
          return [name, cnt] as [string, number];
        });
      editingSpeaker = null;
      newName = "";
    } catch (e) {
      addToast("Failed to rename speaker", "error");
    } finally {
      renaming = false;
    }
  }

  function startEditing(speaker: string) {
    editingSpeaker = speaker;
    newName = speaker.startsWith("SPEAKER_") ? "" : speaker;
  }

  function cancelEditing() {
    editingSpeaker = null;
    newName = "";
  }
</script>

<Modal title="Fix Speaker Names" {onclose}>
  {#if loading}
    <div
      style="
        padding: 24px;
        text-align: center;
        font-family: 'DM Sans', sans-serif;
        color: var(--text-muted);
        font-size: 14px;
      "
    >
      Loading speakers...
    </div>
  {:else if speakers.length === 0}
    <div
      style="
        padding: 24px;
        text-align: center;
        font-family: 'DM Sans', sans-serif;
        color: var(--text-faint);
        font-size: 14px;
      "
    >
      No speakers found in selected meetings.
    </div>
  {:else}
    <div style="display: flex; flex-direction: column; gap: 2px;">
      {#each speakers as [speaker, count]}
        <div
          style="
            padding: 10px 12px;
            border-radius: 6px;
            background: {editingSpeaker === speaker ? 'var(--raised)' : 'transparent'};
            transition: background 120ms ease;
          "
        >
          {#if editingSpeaker === speaker}
            <div style="display: flex; flex-direction: column; gap: 8px;">
              <div
                style="
                  font-family: 'DM Sans', sans-serif;
                  font-size: 13px;
                  color: var(--text-muted);
                "
              >
                Renaming <strong style="color: var(--text);">{speaker}</strong>
                <span style="color: var(--text-faint);"> — {count} meeting{count !== 1 ? "s" : ""}</span>
              </div>
              <div style="display: flex; gap: 8px; align-items: center;">
                <input
                  type="text"
                  bind:value={newName}
                  placeholder="New name"
                  style="
                    flex: 1;
                    padding: 6px 10px;
                    border-radius: 6px;
                    border: 1px solid var(--border);
                    background: var(--surface);
                    color: var(--text);
                    font-family: 'DM Sans', sans-serif;
                    font-size: 14px;
                    outline: none;
                  "
                  onfocus={(e) => {
                    const el = e.currentTarget as HTMLInputElement;
                    el.style.borderColor = 'var(--gold)';
                  }}
                  onblur={(e) => {
                    const el = e.currentTarget as HTMLInputElement;
                    el.style.borderColor = 'var(--border)';
                  }}
                  onkeydown={(e) => {
                    if (e.key === "Enter") handleRename();
                    if (e.key === "Escape") cancelEditing();
                  }}
                />
                <button
                  onclick={handleRename}
                  disabled={!newName.trim() || renaming}
                  style="
                    padding: 6px 14px;
                    border-radius: 6px;
                    border: none;
                    background: var(--gold);
                    color: var(--bg);
                    font-family: 'DM Sans', sans-serif;
                    font-size: 13px;
                    font-weight: 600;
                    cursor: {!newName.trim() || renaming ? 'not-allowed' : 'pointer'};
                    opacity: {!newName.trim() || renaming ? '0.5' : '1'};
                  "
                >
                  {renaming ? "..." : "Rename"}
                </button>
                <button
                  onclick={cancelEditing}
                  style="
                    padding: 6px 10px;
                    border-radius: 6px;
                    border: 1px solid var(--border);
                    background: transparent;
                    color: var(--text-muted);
                    font-family: 'DM Sans', sans-serif;
                    font-size: 13px;
                    cursor: pointer;
                  "
                >
                  Cancel
                </button>
              </div>
            </div>
          {:else}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div
              onclick={() => startEditing(speaker)}
              style="
                display: flex;
                align-items: center;
                justify-content: space-between;
                cursor: pointer;
                font-family: 'DM Sans', sans-serif;
              "
              onmouseenter={(e) => {
                const el = e.currentTarget as HTMLElement;
                el.parentElement!.style.background = 'var(--raised)';
              }}
              onmouseleave={(e) => {
                const el = e.currentTarget as HTMLElement;
                el.parentElement!.style.background = 'transparent';
              }}
            >
              <span style="font-size: 14px; color: var(--text);">
                {speaker}
              </span>
              <span style="font-size: 12px; color: var(--text-faint);">
                {count} meeting{count !== 1 ? "s" : ""}
              </span>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</Modal>
