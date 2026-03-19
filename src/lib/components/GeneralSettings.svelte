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
  <label style="display:flex;align-items:center;gap:8px;font-size:15px;color:var(--text-secondary);font-family:'DM Sans',sans-serif;">
    <input type="checkbox" checked={$settings.meetingNotifications} onchange={(e) => saveSetting("meetingNotifications", e.currentTarget.checked)} style="accent-color:var(--gold);" />
    Pre-meeting notifications
  </label>
  {#if $settings.meetingNotifications}
    <div style="display:flex;align-items:center;gap:8px;margin-left:28px;">
      <label style="font-size:14px;color:var(--text-muted);font-family:'DM Sans',sans-serif;">Lead time</label>
      <select
        value={$settings.meetingLeadTimeMinutes}
        onchange={(e) => saveSetting("meetingLeadTimeMinutes", Number(e.currentTarget.value))}
        style="
          padding: 4px 8px;
          font-size: 13px;
          font-family: 'DM Sans', sans-serif;
          border-radius: 4px;
          border: 1px solid var(--border);
          background: var(--surface);
          color: var(--text);
        "
      >
        <option value={5}>5 minutes</option>
        <option value={10}>10 minutes</option>
        <option value={15}>15 minutes</option>
      </select>
    </div>
  {/if}
</div>
