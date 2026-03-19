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
    <span style="color:var(--text-muted);">Version</span>
    <span style="color:var(--text);">{version}</span>
  </div>
  <div style="display:flex;justify-content:space-between;">
    <span style="color:var(--text-muted);">Pipeline Sidecar</span>
    <span style="color:{sidecarFound ? 'var(--green)' : 'var(--red)'};">
      {sidecarFound === null ? "Checking..." : sidecarFound ? "Found" : "Not found"}
    </span>
  </div>
  <div style="display:flex;justify-content:space-between;">
    <span style="color:var(--text-muted);">ffmpeg</span>
    <span style="color:{ffmpegFound ? 'var(--green)' : 'var(--red)'};">
      {ffmpegFound === null ? "Checking..." : ffmpegFound ? "Found" : "Not found"}
    </span>
  </div>
  <div style="display:flex;justify-content:space-between;">
    <span style="color:var(--text-muted);">NVENC (H.265)</span>
    <span style="color:{nvencStatus === 'Available' ? 'var(--green)' : 'var(--warning)'};">
      {ffmpegFound === false ? "Requires ffmpeg" : nvencStatus ?? "Checking..."}
    </span>
  </div>
</div>
