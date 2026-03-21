<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import { resetMeetings } from "../stores/meetings";
  import { open } from "@tauri-apps/plugin-dialog";
  import SettingsTooltip from "./SettingsTooltip.svelte";

  async function browseRecordingsFolder() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) {
      await saveSetting("recordingsFolder", selected as string);
      await resetMeetings();
    }
  }
</script>

<label style="display:block;">
  <span style="display:flex;align-items:center;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;">Recordings Folder<SettingsTooltip text="Where meeting recordings are stored. SSD recommended for multi-stream capture." /></span>
  <div style="display:flex;gap:8px;">
    <input
      type="text"
      value={$settings.recordingsFolder}
      onblur={async (e) => { const newValue = e.currentTarget.value; if (newValue !== $settings.recordingsFolder) { await saveSetting("recordingsFolder", newValue); await resetMeetings(); } }}
      style="flex:1;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:15px;color:var(--text);font-family:'DM Sans',sans-serif;outline:none;"
      placeholder="Path to store recordings"
    />
    <button
      onclick={browseRecordingsFolder}
      style="font-size:14.5px;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;color:var(--text-secondary);cursor:pointer;font-family:'DM Sans',sans-serif;"
      onmouseenter={(e) => { e.currentTarget.style.background = 'var(--raised)'; }}
      onmouseleave={(e) => { e.currentTarget.style.background = 'var(--surface)'; }}
    >
      Browse
    </button>
  </div>
</label>
