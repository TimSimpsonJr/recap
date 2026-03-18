<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
</script>

<div style="display:flex;flex-direction:column;gap:12px;">
  <label style="display:flex;align-items:center;gap:8px;font-size:13.5px;color:#78756E;font-family:'DM Sans',sans-serif;">
    <input type="checkbox" disabled style="accent-color:#A8A078;" />
    Start on login
    <span style="font-size:11px;color:#585650;">(enabled in final release)</span>
  </label>
  <label style="display:flex;align-items:center;gap:8px;font-size:13.5px;color:#B0ADA5;font-family:'DM Sans',sans-serif;">
    <input type="checkbox" checked={$settings.showNotificationOnComplete} onchange={(e) => saveSetting("showNotificationOnComplete", e.currentTarget.checked)} style="accent-color:#A8A078;" />
    Show notification when processing complete
  </label>
</div>
