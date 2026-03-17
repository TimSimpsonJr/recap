<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
</script>

<div class="space-y-4">
  <!-- Auto-detect toggle -->
  <label class="flex items-center justify-between">
    <span class="text-sm text-gray-600">Auto-detect Zoom meetings</span>
    <input
      type="checkbox"
      checked={$settings.autoDetectMeetings}
      onchange={(e) => saveSetting("autoDetectMeetings", e.currentTarget.checked)}
      class="rounded"
    />
  </label>

  <!-- Detection action dropdown -->
  <label class="block">
    <span class="block text-sm text-gray-600 mb-1">When meeting detected</span>
    <select
      value={$settings.detectionAction}
      onchange={(e) => saveSetting("detectionAction", e.currentTarget.value as "ask" | "always_record" | "never_record")}
      class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
    >
      <option value="ask">Ask me</option>
      <option value="always_record">Always record</option>
      <option value="never_record">Never record</option>
    </select>
  </label>

  <!-- Conditional: timeout settings (only when "ask") -->
  {#if $settings.detectionAction === "ask"}
    <label class="block">
      <span class="block text-sm text-gray-600 mb-1">When notification times out</span>
      <select
        value={$settings.timeoutAction}
        onchange={(e) => saveSetting("timeoutAction", e.currentTarget.value as "record" | "skip")}
        class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
      >
        <option value="record">Start recording</option>
        <option value="skip">Skip recording</option>
      </select>
    </label>

    <label class="block">
      <span class="block text-sm text-gray-600 mb-1">Notification timeout (seconds)</span>
      <input
        type="number"
        min="10"
        max="300"
        value={$settings.notificationTimeoutSeconds}
        onblur={(e) => saveSetting("notificationTimeoutSeconds", parseInt(e.currentTarget.value))}
        class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
      />
    </label>
  {/if}
</div>
