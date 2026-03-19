<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
  import { saveHuggingFaceToken, getHuggingFaceToken } from "../stores/credentials";
  import { onMount } from "svelte";

  let hfToken = $state("");

  onMount(async () => {
    const existing = await getHuggingFaceToken();
    if (existing) hfToken = existing;
  });

  async function saveToken() {
    if (hfToken) await saveHuggingFaceToken(hfToken);
  }

  const inputStyle = "width:100%;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:15px;color:var(--text);font-family:'DM Sans',sans-serif;outline:none;";
  const labelStyle = "display:block;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;";
</script>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
  <label style="display:block;">
    <span style={labelStyle}>Model</span>
    <select value={$settings.whisperxModel} onchange={(e) => saveSetting("whisperxModel", e.currentTarget.value)} style={inputStyle}>
      <option value="large-v3">large-v3</option>
      <option value="medium">medium</option>
      <option value="small">small</option>
      <option value="base">base</option>
      <option value="tiny">tiny</option>
    </select>
  </label>
  <label style="display:block;">
    <span style={labelStyle}>Device</span>
    <select value={$settings.whisperxDevice} onchange={(e) => saveSetting("whisperxDevice", e.currentTarget.value)} style={inputStyle}>
      <option value="cuda">CUDA (GPU)</option>
      <option value="cpu">CPU</option>
    </select>
  </label>
  <label style="display:block;">
    <span style={labelStyle}>Compute Type</span>
    <select value={$settings.whisperxComputeType} onchange={(e) => saveSetting("whisperxComputeType", e.currentTarget.value)} style={inputStyle}>
      <option value="float16">float16</option>
      <option value="int8">int8</option>
      <option value="float32">float32</option>
    </select>
  </label>
  <label style="display:block;">
    <span style={labelStyle}>Language</span>
    <input type="text" value={$settings.whisperxLanguage} onblur={(e) => saveSetting("whisperxLanguage", e.currentTarget.value)} style={inputStyle} placeholder="en" />
  </label>
</div>
<div style="margin-top:12px;">
  <label style="display:block;">
    <span style={labelStyle}>HuggingFace Token</span>
    <input type="password" bind:value={hfToken} onblur={saveToken} style={inputStyle} placeholder="hf_..." />
  </label>
</div>
