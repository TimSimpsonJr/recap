<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import { open } from "@tauri-apps/plugin-dialog";

  async function browseVaultPath() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) {
      await saveSetting("vaultPath", selected as string);
    }
  }

  const inputStyle = "width:100%;background:#282826;border:1px solid #262624;border-radius:6px;padding:6px 12px;font-size:13.5px;color:#D8D5CE;font-family:'DM Sans',sans-serif;outline:none;";
  const labelStyle = "display:block;font-size:12.5px;color:#78756E;margin-bottom:4px;font-family:'DM Sans',sans-serif;";
</script>

<div style="display:flex;flex-direction:column;gap:12px;">
  <label style="display:block;">
    <span style={labelStyle}>Vault Path</span>
    <div style="display:flex;gap:8px;">
      <input
        type="text"
        value={$settings.vaultPath}
        onblur={(e) => saveSetting("vaultPath", e.currentTarget.value)}
        style="flex:1;background:#282826;border:1px solid #262624;border-radius:6px;padding:6px 12px;font-size:13.5px;color:#D8D5CE;font-family:'DM Sans',sans-serif;outline:none;"
        placeholder="Path to Obsidian vault"
      />
      <button
        onclick={browseVaultPath}
        style="font-size:13px;background:#282826;border:1px solid #262624;border-radius:6px;padding:6px 12px;color:#B0ADA5;cursor:pointer;font-family:'DM Sans',sans-serif;"
        onmouseenter={(e) => { e.currentTarget.style.background = '#2B2B28'; }}
        onmouseleave={(e) => { e.currentTarget.style.background = '#282826'; }}
      >
        Browse
      </button>
    </div>
  </label>

  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;">
    <label style="display:block;">
      <span style={labelStyle}>Meetings Folder</span>
      <input type="text" value={$settings.meetingsFolder} onblur={(e) => saveSetting("meetingsFolder", e.currentTarget.value)} style={inputStyle} />
    </label>
    <label style="display:block;">
      <span style={labelStyle}>People Folder</span>
      <input type="text" value={$settings.peopleFolder} onblur={(e) => saveSetting("peopleFolder", e.currentTarget.value)} style={inputStyle} />
    </label>
    <label style="display:block;">
      <span style={labelStyle}>Companies Folder</span>
      <input type="text" value={$settings.companiesFolder} onblur={(e) => saveSetting("companiesFolder", e.currentTarget.value)} style={inputStyle} />
    </label>
  </div>
</div>
