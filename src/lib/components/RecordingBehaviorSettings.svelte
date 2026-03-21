<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import { listMonitors, type MonitorInfo } from "../tauri";
  import { onMount } from "svelte";
  import SettingsTooltip from "./SettingsTooltip.svelte";

  const inputStyle = "width:100%;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:15px;color:var(--text);font-family:'DM Sans',sans-serif;outline:none;";
  const labelStyle = "display:block;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;";

  let monitors: MonitorInfo[] = $state([]);

  onMount(async () => {
    try {
      monitors = await listMonitors();
    } catch (e) {
      console.warn("Failed to enumerate monitors:", e);
    }
  });
</script>

<div style="display:flex;flex-direction:column;gap:12px;">
  <!-- Auto-detect toggle -->
  <label style="display:flex;align-items:center;justify-content:space-between;">
    <span style="font-size:15px;color:var(--text-secondary);font-family:'DM Sans',sans-serif;">Auto-detect Zoom meetings</span>
    <input
      type="checkbox"
      checked={$settings.autoDetectMeetings}
      onchange={(e) => saveSetting("autoDetectMeetings", e.currentTarget.checked)}
      style="accent-color:var(--gold);"
    />
  </label>

  <!-- Detection action dropdown -->
  <label style="display:block;">
    <span style={labelStyle}>When meeting detected</span>
    <select
      value={$settings.detectionAction}
      onchange={(e) => saveSetting("detectionAction", e.currentTarget.value as "ask" | "always_record" | "never_record")}
      style={inputStyle}
    >
      <option value="ask">Ask me</option>
      <option value="always_record">Always record</option>
      <option value="never_record">Never record</option>
    </select>
  </label>

  <!-- Conditional: timeout settings (only when "ask") -->
  {#if $settings.detectionAction === "ask"}
    <label style="display:block;">
      <span style={labelStyle}>When notification times out</span>
      <select
        value={$settings.timeoutAction}
        onchange={(e) => saveSetting("timeoutAction", e.currentTarget.value as "record" | "skip")}
        style={inputStyle}
      >
        <option value="record">Start recording</option>
        <option value="skip">Skip recording</option>
      </select>
    </label>

    <label style="display:block;">
      <span style={labelStyle}>Notification timeout (seconds)</span>
      <input
        type="number"
        min="10"
        max="300"
        value={$settings.notificationTimeoutSeconds}
        onblur={(e) => saveSetting("notificationTimeoutSeconds", parseInt(e.currentTarget.value))}
        style={inputStyle}
      />
    </label>
  {/if}

  <!-- Auto-record all calendar meetings -->
  <label style="display:flex;align-items:center;justify-content:space-between;">
    <div>
      <span style="font-size:15px;color:var(--text-secondary);font-family:'DM Sans',sans-serif;">Auto-record all calendar meetings<SettingsTooltip text="Automatically start recording when a calendar event begins. Arms the recorder for every upcoming event." /></span>
      <div style="font-size:12px;color:var(--text-faint);font-family:'DM Sans',sans-serif;margin-top:2px;">
        Arms the recorder for every upcoming calendar event
      </div>
    </div>
    <input
      type="checkbox"
      checked={$settings.autoRecordAllCalendar}
      onchange={(e) => saveSetting("autoRecordAllCalendar", e.currentTarget.checked)}
      style="accent-color:var(--gold);"
    />
  </label>

  <!-- Screen share monitor selector -->
  {#if monitors.length > 0}
    <label style="display:block;">
      <span style={labelStyle}>Screen share capture monitor</span>
      <select
        value={$settings.screenShareMonitor}
        onchange={(e) => saveSetting("screenShareMonitor", parseInt(e.currentTarget.value))}
        style={inputStyle}
      >
        {#each monitors as monitor}
          <option value={monitor.index}>
            {monitor.name} ({monitor.width}x{monitor.height}){monitor.is_primary ? " — Primary" : ""}
          </option>
        {/each}
      </select>
    </label>
  {/if}
</div>
