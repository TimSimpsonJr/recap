<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";

  const inputStyle = "width:100%;background:#282826;border:1px solid #262624;border-radius:6px;padding:6px 12px;font-size:13.5px;color:#D8D5CE;font-family:'DM Sans',sans-serif;outline:none;";
  const labelStyle = "display:block;font-size:12.5px;color:#78756E;margin-bottom:4px;font-family:'DM Sans',sans-serif;";
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
