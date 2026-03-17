<script lang="ts">
  import { onMount } from "svelte";
  import { checkSidecarStatus } from "../tauri";
  import { getVersion } from "@tauri-apps/api/app";

  let version = $state("...");
  let sidecarFound = $state<boolean | null>(null);

  onMount(async () => {
    version = await getVersion();
    sidecarFound = await checkSidecarStatus();
  });
</script>

<div class="space-y-2 text-sm">
  <div class="flex justify-between">
    <span class="text-gray-600">Version</span>
    <span class="text-gray-900">{version}</span>
  </div>
  <div class="flex justify-between">
    <span class="text-gray-600">Pipeline Sidecar</span>
    <span class={sidecarFound ? "text-green-600" : "text-red-600"}>
      {sidecarFound === null ? "Checking..." : sidecarFound ? "Found" : "Not found"}
    </span>
  </div>
</div>
