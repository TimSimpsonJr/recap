<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";

  const inputStyle = "width:100%;background:#282826;border:1px solid #262624;border-radius:6px;padding:6px 12px;font-size:15px;color:#D8D5CE;font-family:'DM Sans',sans-serif;outline:none;";
  const labelStyle = "display:block;font-size:14px;color:#78756E;margin-bottom:4px;font-family:'DM Sans',sans-serif;";
</script>

<div style="display:flex;flex-direction:column;gap:12px;">
  <label style="display:block;">
    <span style={labelStyle}>Project</span>
    <input type="text" value={$settings.todoistProject} onblur={(e) => saveSetting("todoistProject", e.currentTarget.value)} style={inputStyle} placeholder="Project name for meeting tasks" />
  </label>
  <label style="display:block;">
    <span style={labelStyle}>Default Labels</span>
    <input type="text" value={$settings.todoistLabels} onblur={(e) => saveSetting("todoistLabels", e.currentTarget.value)} style={inputStyle} placeholder="Comma-separated labels" />
  </label>
</div>
