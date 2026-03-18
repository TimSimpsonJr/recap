<script lang="ts">
  import { type ProviderName, type ProviderState, saveClientCredentials, disconnect } from "../stores/credentials";
  import { startOAuth } from "../tauri";
  import { settings, saveSetting } from "../stores/settings";

  interface Props {
    provider: ProviderName;
    label: string;
    providerState: ProviderState;
    showRegion?: boolean;
  }

  let { provider, label, providerState, showRegion = false }: Props = $props();

  let editingClientId = $state("");
  let editingClientSecret = $state("");
  let hasPendingEdits = $state(false);
  let saving = $state(false);
  let connecting = $state(false);

  let clientId = $derived(hasPendingEdits ? editingClientId : providerState.clientId);
  let clientSecret = $derived(hasPendingEdits ? editingClientSecret : providerState.clientSecret);

  function onClientIdInput(e: Event) {
    editingClientId = (e.target as HTMLInputElement).value;
    editingClientSecret = clientSecret;
    hasPendingEdits = true;
  }

  function onClientSecretInput(e: Event) {
    editingClientSecret = (e.target as HTMLInputElement).value;
    editingClientId = clientId;
    hasPendingEdits = true;
  }

  let hasCredentials = $derived(clientId.trim() !== "" && clientSecret.trim() !== "");

  async function saveCredentials() {
    saving = true;
    try {
      await saveClientCredentials(provider, clientId, clientSecret);
      hasPendingEdits = false;
    } finally {
      saving = false;
    }
  }

  async function connect() {
    connecting = true;
    try {
      await saveClientCredentials(provider, clientId, clientSecret);
      let zohoRegion: string | undefined;
      if (provider === "zoho") {
        const s = $settings;
        zohoRegion = s.zohoRegion;
      }
      await startOAuth(provider, clientId, clientSecret, zohoRegion);
    } finally {
      connecting = false;
    }
  }

  async function handleDisconnect() {
    await disconnect(provider);
  }

  const inputStyle = "width:100%;background:#282826;border:1px solid #262624;border-radius:6px;padding:6px 12px;font-size:13.5px;color:#D8D5CE;font-family:'DM Sans',sans-serif;outline:none;";
  const labelStyle = "display:block;font-size:12.5px;color:#78756E;margin-bottom:4px;font-family:'DM Sans',sans-serif;";
</script>

<div style="display:flex;flex-direction:column;gap:12px;">
  <label style="display:block;">
    <span style={labelStyle}>Client ID</span>
    <input
      type="text"
      value={clientId}
      oninput={onClientIdInput}
      onblur={saveCredentials}
      style={inputStyle}
      placeholder="Enter client ID"
    />
  </label>

  <label style="display:block;">
    <span style={labelStyle}>Client Secret</span>
    <input
      type="password"
      value={clientSecret}
      oninput={onClientSecretInput}
      onblur={saveCredentials}
      style={inputStyle}
      placeholder="Enter client secret"
    />
  </label>

  {#if showRegion}
    <label style="display:block;">
      <span style={labelStyle}>Region</span>
      <select
        style={inputStyle}
        value={$settings.zohoRegion}
        onchange={(e) => saveSetting("zohoRegion", (e.target as HTMLSelectElement).value)}
      >
        <option value="com">.com (US)</option>
        <option value="eu">.eu (Europe)</option>
        <option value="in">.in (India)</option>
        <option value="com.au">.com.au (Australia)</option>
      </select>
    </label>
  {/if}

  <div style="display:flex;align-items:center;justify-content:space-between;padding-top:8px;">
    <div style="font-size:13px;">
      {#if providerState.status === "connected"}
        <span style="color:#4ade80;">Connected{providerState.displayName ? ` as ${providerState.displayName}` : ""}</span>
      {:else if providerState.status === "reconnect_required"}
        <span style="color:#f59e0b;">Reconnect required</span>
      {:else}
        <span style="color:#78756E;">Disconnected</span>
      {/if}
    </div>

    <div>
      {#if providerState.status === "connected"}
        <button
          onclick={handleDisconnect}
          style="font-size:13px;color:#D06850;background:none;border:none;cursor:pointer;font-family:'DM Sans',sans-serif;"
          onmouseenter={(e) => { e.currentTarget.style.textDecoration = 'underline'; }}
          onmouseleave={(e) => { e.currentTarget.style.textDecoration = 'none'; }}
        >
          Disconnect
        </button>
      {:else}
        <button
          onclick={connect}
          disabled={!hasCredentials || connecting}
          style="font-size:13px;background:#A8A078;color:#1D1D1B;padding:6px 16px;border-radius:6px;border:none;cursor:pointer;font-family:'DM Sans',sans-serif;font-weight:500;opacity:{!hasCredentials || connecting ? '0.5' : '1'};"
        >
          {connecting ? "Connecting..." : "Connect"}
        </button>
      {/if}
    </div>
  </div>

  {#if provider === "microsoft" && providerState.status === "connected"}
    <p style="font-size:12px;color:#f59e0b;margin-top:4px;">
      Note: Personal accounts have limited recording API access. Recording will require manual start.
    </p>
  {/if}
</div>
