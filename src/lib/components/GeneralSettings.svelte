<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
</script>

<div style="display:flex;flex-direction:column;gap:12px;">
  <label style="display:flex;align-items:center;gap:8px;font-size:15px;color:var(--text-muted);font-family:'DM Sans',sans-serif;">
    <input type="checkbox" disabled style="accent-color:var(--gold);" />
    Start on login
    <span style="font-size:12.5px;color:var(--text-faint);">(enabled in final release)</span>
  </label>
  <label style="display:flex;align-items:center;gap:8px;font-size:15px;color:var(--text-secondary);font-family:'DM Sans',sans-serif;">
    <input type="checkbox" checked={$settings.showNotificationOnComplete} onchange={(e) => saveSetting("showNotificationOnComplete", e.currentTarget.checked)} style="accent-color:var(--gold);" />
    Show notification when processing complete
  </label>
</div>
