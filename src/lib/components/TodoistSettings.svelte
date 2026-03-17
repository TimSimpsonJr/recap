<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
</script>

<div class="space-y-3">
  <label class="block">
    <span class="block text-sm text-gray-600 mb-1">Project</span>
    <input type="text" value={$settings.todoistProject} onblur={(e) => saveSetting("todoistProject", e.currentTarget.value)} class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm" placeholder="Project name for meeting tasks" />
  </label>
  <label class="block">
    <span class="block text-sm text-gray-600 mb-1">Default Labels</span>
    <input type="text" value={$settings.todoistLabels} onblur={(e) => saveSetting("todoistLabels", e.currentTarget.value)} class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm" placeholder="Comma-separated labels" />
  </label>
</div>
