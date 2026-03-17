<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
</script>

<div class="grid grid-cols-2 gap-3">
  <label class="block">
    <span class="block text-sm text-gray-600 mb-1">Model</span>
    <select value={$settings.whisperxModel} onchange={(e) => saveSetting("whisperxModel", e.currentTarget.value)} class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm">
      <option value="large-v3">large-v3</option>
      <option value="medium">medium</option>
      <option value="small">small</option>
      <option value="base">base</option>
      <option value="tiny">tiny</option>
    </select>
  </label>
  <label class="block">
    <span class="block text-sm text-gray-600 mb-1">Device</span>
    <select value={$settings.whisperxDevice} onchange={(e) => saveSetting("whisperxDevice", e.currentTarget.value)} class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm">
      <option value="cuda">CUDA (GPU)</option>
      <option value="cpu">CPU</option>
    </select>
  </label>
  <label class="block">
    <span class="block text-sm text-gray-600 mb-1">Compute Type</span>
    <select value={$settings.whisperxComputeType} onchange={(e) => saveSetting("whisperxComputeType", e.currentTarget.value)} class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm">
      <option value="float16">float16</option>
      <option value="int8">int8</option>
      <option value="float32">float32</option>
    </select>
  </label>
  <label class="block">
    <span class="block text-sm text-gray-600 mb-1">Language</span>
    <input type="text" value={$settings.whisperxLanguage} onblur={(e) => saveSetting("whisperxLanguage", e.currentTarget.value)} class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm" placeholder="en" />
  </label>
</div>
