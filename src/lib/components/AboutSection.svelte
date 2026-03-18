<script lang="ts">
  import { onMount } from "svelte";
  import { checkSidecarStatus, checkFfmpeg, checkNvenc } from "../tauri";
  import { getVersion } from "@tauri-apps/api/app";

  let version = $state("...");
  let sidecarFound = $state<boolean | null>(null);
  let ffmpegFound = $state<boolean | null>(null);
  let nvencStatus = $state<string | null>(null);

  onMount(async () => {
    version = await getVersion();
    sidecarFound = await checkSidecarStatus();
    ffmpegFound = await checkFfmpeg();
    if (ffmpegFound) {
      nvencStatus = await checkNvenc();
    }
  });
</script>

<div style="display:flex;flex-direction:column;gap:8px;font-size:15px;font-family:'DM Sans',sans-serif;">
  <div style="display:flex;justify-content:space-between;">
    <span style="color:#78756E;">Version</span>
    <span style="color:#D8D5CE;">{version}</span>
  </div>
  <div style="display:flex;justify-content:space-between;">
    <span style="color:#78756E;">Pipeline Sidecar</span>
    <span style="color:{sidecarFound ? '#4ade80' : '#D06850'};">
      {sidecarFound === null ? "Checking..." : sidecarFound ? "Found" : "Not found"}
    </span>
  </div>
  <div style="display:flex;justify-content:space-between;">
    <span style="color:#78756E;">ffmpeg</span>
    <span style="color:{ffmpegFound ? '#4ade80' : '#D06850'};">
      {ffmpegFound === null ? "Checking..." : ffmpegFound ? "Found" : "Not found"}
    </span>
  </div>
  <div style="display:flex;justify-content:space-between;">
    <span style="color:#78756E;">NVENC (H.265)</span>
    <span style="color:{nvencStatus === 'Available' ? '#4ade80' : '#f59e0b'};">
      {ffmpegFound === false ? "Requires ffmpeg" : nvencStatus ?? "Checking..."}
    </span>
  </div>
</div>
