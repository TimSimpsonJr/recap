<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
</script>

<div class="space-y-3">
  <label class="flex items-center gap-2 text-sm text-gray-600">
    <input type="checkbox" disabled class="rounded" />
    Start on login
    <span class="text-xs text-gray-400">(enabled in final release)</span>
  </label>
  <label class="flex items-center gap-2 text-sm text-gray-600">
    <input type="checkbox" checked={$settings.showNotificationOnComplete} onchange={(e) => saveSetting("showNotificationOnComplete", e.currentTarget.checked)} class="rounded" />
    Show notification when processing complete
  </label>
</div>
