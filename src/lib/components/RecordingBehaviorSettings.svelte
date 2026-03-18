<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";

  const inputStyle = "width:100%;background:#282826;border:1px solid #262624;border-radius:6px;padding:6px 12px;font-size:15px;color:#D8D5CE;font-family:'DM Sans',sans-serif;outline:none;";
  const labelStyle = "display:block;font-size:14px;color:#78756E;margin-bottom:4px;font-family:'DM Sans',sans-serif;";
</script>

<div style="display:flex;flex-direction:column;gap:12px;">
  <!-- Auto-detect toggle -->
  <label style="display:flex;align-items:center;justify-content:space-between;">
    <span style="font-size:15px;color:#B0ADA5;font-family:'DM Sans',sans-serif;">Auto-detect Zoom meetings</span>
    <input
      type="checkbox"
      checked={$settings.autoDetectMeetings}
      onchange={(e) => saveSetting("autoDetectMeetings", e.currentTarget.checked)}
      style="accent-color:#A8A078;"
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
</div>
