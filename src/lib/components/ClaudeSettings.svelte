<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import SettingsTooltip from "./SettingsTooltip.svelte";

  const inputStyle = "width:100%;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:15px;color:var(--text);font-family:'DM Sans',sans-serif;outline:none;";
  const labelStyle = "display:block;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;";
</script>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
  <label style="display:block;">
    <span style="display:flex;align-items:center;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;">Model<SettingsTooltip text="Which Claude model to use for meeting analysis." /></span>
    <select value={$settings.claudeModel} onchange={(e) => saveSetting("claudeModel", e.currentTarget.value)} style={inputStyle}>
      <option value="haiku">Haiku</option>
      <option value="sonnet">Sonnet</option>
      <option value="opus">Opus</option>
    </select>
  </label>
  <label style="display:block;">
    <span style={labelStyle}>CLI Path</span>
    <input type="text" value={$settings.claudeCommand} onblur={(e) => saveSetting("claudeCommand", e.currentTarget.value)} style={inputStyle} placeholder="claude" />
  </label>
</div>
