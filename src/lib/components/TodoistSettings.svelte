<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import SettingsTooltip from "./SettingsTooltip.svelte";

  let newType = $state("");
  let newProject = $state("");

  async function addMapping() {
    if (newType && newProject) {
      const updated = { ...$settings.todoistProjectMap, [newType]: newProject };
      await saveSetting("todoistProjectMap", updated);
      newType = "";
      newProject = "";
    }
  }

  async function removeMapping(type: string) {
    const updated = { ...$settings.todoistProjectMap };
    delete updated[type];
    await saveSetting("todoistProjectMap", updated);
  }

  const inputStyle = "width:100%;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:15px;color:var(--text);font-family:'DM Sans',sans-serif;outline:none;";
  const labelStyle = "display:block;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;";
  const buttonStyle = "background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;color:var(--text-secondary);cursor:pointer;font-family:'DM Sans',sans-serif;";
</script>

<div style="display:flex;flex-direction:column;gap:12px;">
  <label style="display:block;">
    <span style="display:flex;align-items:center;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;">Project<SettingsTooltip text="Default Todoist project for task creation from meetings." /></span>
    <input type="text" value={$settings.todoistProject} onblur={(e) => saveSetting("todoistProject", e.currentTarget.value)} style={inputStyle} placeholder="Project name for meeting tasks" />
  </label>
  <label style="display:block;">
    <span style="display:flex;align-items:center;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;">Project Grouping<SettingsTooltip text="How Todoist projects are organized. Per company creates a project per company (e.g. 'Recap: Acme Corp'). Per meeting creates one per meeting title. Single project puts all tasks in the default project above." /></span>
    <select value={$settings.todoistProjectGrouping} onchange={(e) => saveSetting("todoistProjectGrouping", e.currentTarget.value)} style={inputStyle}>
      <option value="company">Per company</option>
      <option value="meeting">Per meeting</option>
      <option value="single">Single project</option>
    </select>
  </label>
  <label style="display:block;">
    <span style={labelStyle}>Default Labels</span>
    <input type="text" value={$settings.todoistLabels} onblur={(e) => saveSetting("todoistLabels", e.currentTarget.value)} style={inputStyle} placeholder="Comma-separated labels" />
  </label>

  <div>
    <span style={labelStyle}>Project Map</span>
    {#if Object.keys($settings.todoistProjectMap).length > 0}
      <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:8px;">
        {#each Object.entries($settings.todoistProjectMap) as [type, project]}
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="flex:1;font-size:14px;color:var(--text);font-family:'DM Sans',sans-serif;padding:4px 0;">{type}</span>
            <span style="font-size:13px;color:var(--text-muted);font-family:'DM Sans',sans-serif;">&#8594;</span>
            <span style="flex:1;font-size:14px;color:var(--text);font-family:'DM Sans',sans-serif;padding:4px 0;">{project}</span>
            <button onclick={() => removeMapping(type)} style="{buttonStyle};padding:4px 10px;font-size:13px;color:var(--text-muted);">&#10005;</button>
          </div>
        {/each}
      </div>
    {/if}
    <div style="display:flex;align-items:center;gap:8px;">
      <input type="text" bind:value={newType} style="{inputStyle};flex:1;" placeholder="Meeting type" />
      <input type="text" bind:value={newProject} style="{inputStyle};flex:1;" placeholder="Project name" />
      <button onclick={addMapping} style={buttonStyle}>Add</button>
    </div>
  </div>
</div>
