<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import { open } from "@tauri-apps/plugin-dialog";

  async function browseVaultPath() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) {
      await saveSetting("vaultPath", selected as string);
    }
  }
</script>

<div class="space-y-3">
  <label class="block">
    <span class="block text-sm text-gray-600 mb-1">Vault Path</span>
    <div class="flex gap-2">
      <input
        type="text"
        value={$settings.vaultPath}
        onblur={(e) => saveSetting("vaultPath", e.currentTarget.value)}
        class="flex-1 border border-gray-300 rounded px-3 py-1.5 text-sm"
        placeholder="Path to Obsidian vault"
      />
      <button onclick={browseVaultPath} class="text-sm bg-gray-100 px-3 py-1.5 rounded border border-gray-300 hover:bg-gray-200">
        Browse
      </button>
    </div>
  </label>

  <div class="grid grid-cols-3 gap-3">
    <label class="block">
      <span class="block text-sm text-gray-600 mb-1">Meetings Folder</span>
      <input type="text" value={$settings.meetingsFolder} onblur={(e) => saveSetting("meetingsFolder", e.currentTarget.value)} class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm" />
    </label>
    <label class="block">
      <span class="block text-sm text-gray-600 mb-1">People Folder</span>
      <input type="text" value={$settings.peopleFolder} onblur={(e) => saveSetting("peopleFolder", e.currentTarget.value)} class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm" />
    </label>
    <label class="block">
      <span class="block text-sm text-gray-600 mb-1">Companies Folder</span>
      <input type="text" value={$settings.companiesFolder} onblur={(e) => saveSetting("companiesFolder", e.currentTarget.value)} class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm" />
    </label>
  </div>
</div>
