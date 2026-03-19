<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import { resetMeetings } from "../stores/meetings";
  import { open } from "@tauri-apps/plugin-dialog";

  async function browseVaultPath() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) {
      await saveSetting("vaultPath", selected as string);
      await resetMeetings();
    }
  }

  const inputStyle = "width:100%;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:15px;color:var(--text);font-family:'DM Sans',sans-serif;outline:none;";
  const labelStyle = "display:block;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;";
</script>

<div style="display:flex;flex-direction:column;gap:12px;">
  <label style="display:block;">
    <span style={labelStyle}>Vault Path</span>
    <div style="display:flex;gap:8px;">
      <input
        type="text"
        value={$settings.vaultPath}
        onblur={async (e) => { const newValue = e.currentTarget.value; if (newValue !== $settings.vaultPath) { await saveSetting("vaultPath", newValue); await resetMeetings(); } }}
        style="flex:1;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:15px;color:var(--text);font-family:'DM Sans',sans-serif;outline:none;"
        placeholder="Path to Obsidian vault"
      />
      <button
        onclick={browseVaultPath}
        style="font-size:14.5px;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;color:var(--text-secondary);cursor:pointer;font-family:'DM Sans',sans-serif;"
        onmouseenter={(e) => { e.currentTarget.style.background = 'var(--raised)'; }}
        onmouseleave={(e) => { e.currentTarget.style.background = 'var(--surface)'; }}
      >
        Browse
      </button>
    </div>
  </label>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;">
    <label style="display:block;">
      <span style={labelStyle}>Meetings Folder</span>
      <input type="text" value={$settings.meetingsFolder} onblur={async (e) => { const newValue = e.currentTarget.value; if (newValue !== $settings.meetingsFolder) { await saveSetting("meetingsFolder", newValue); await resetMeetings(); } }} style={inputStyle} />
    </label>
    <label style="display:block;">
      <span style={labelStyle}>People Folder</span>
      <input type="text" value={$settings.peopleFolder} onblur={async (e) => { const newValue = e.currentTarget.value; if (newValue !== $settings.peopleFolder) { await saveSetting("peopleFolder", newValue); await resetMeetings(); } }} style={inputStyle} />
    </label>
    <label style="display:block;">
      <span style={labelStyle}>Companies Folder</span>
      <input type="text" value={$settings.companiesFolder} onblur={async (e) => { const newValue = e.currentTarget.value; if (newValue !== $settings.companiesFolder) { await saveSetting("companiesFolder", newValue); await resetMeetings(); } }} style={inputStyle} />
    </label>
  </div>
</div>
