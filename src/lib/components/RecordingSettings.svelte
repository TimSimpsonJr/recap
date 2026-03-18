<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import { resetMeetings } from "../stores/meetings";
  import { open } from "@tauri-apps/plugin-dialog";

  async function browseRecordingsFolder() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) {
      await saveSetting("recordingsFolder", selected as string);
      await resetMeetings();
    }
  }
</script>

<label style="display:block;">
  <span style="display:block;font-size:14px;color:#78756E;margin-bottom:4px;font-family:'DM Sans',sans-serif;">Recordings Folder</span>
  <div style="display:flex;gap:8px;">
    <input
      type="text"
      value={$settings.recordingsFolder}
      onblur={async (e) => { await saveSetting("recordingsFolder", e.currentTarget.value); await resetMeetings(); }}
      style="flex:1;background:#282826;border:1px solid #262624;border-radius:6px;padding:6px 12px;font-size:15px;color:#D8D5CE;font-family:'DM Sans',sans-serif;outline:none;"
      placeholder="Path to store recordings"
    />
    <button
      onclick={browseRecordingsFolder}
      style="font-size:14.5px;background:#282826;border:1px solid #262624;border-radius:6px;padding:6px 12px;color:#B0ADA5;cursor:pointer;font-family:'DM Sans',sans-serif;"
      onmouseenter={(e) => { e.currentTarget.style.background = '#2B2B28'; }}
      onmouseleave={(e) => { e.currentTarget.style.background = '#282826'; }}
    >
      Browse
    </button>
  </div>
</label>
