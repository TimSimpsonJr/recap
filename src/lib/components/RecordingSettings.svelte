<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import { open } from "@tauri-apps/plugin-dialog";

  async function browseRecordingsFolder() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) {
      await saveSetting("recordingsFolder", selected as string);
    }
  }
</script>

<label class="block">
  <span class="block text-sm text-gray-600 mb-1">Recordings Folder</span>
  <div class="flex gap-2">
    <input type="text" value={$settings.recordingsFolder} onblur={(e) => saveSetting("recordingsFolder", e.currentTarget.value)} class="flex-1 border border-gray-300 rounded px-3 py-1.5 text-sm" placeholder="Path to store recordings" />
    <button onclick={browseRecordingsFolder} class="text-sm bg-gray-100 px-3 py-1.5 rounded border border-gray-300 hover:bg-gray-200">Browse</button>
  </div>
</label>
