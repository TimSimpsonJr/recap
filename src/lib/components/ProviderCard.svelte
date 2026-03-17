<script lang="ts">
  import { type ProviderName, type ProviderState, saveClientCredentials, disconnect } from "../stores/credentials";
  import { startOAuth } from "../tauri";
  import { settings } from "../stores/settings";

  interface Props {
    provider: ProviderName;
    label: string;
    providerState: ProviderState;
    showRegion?: boolean;
  }

  let { provider, label, providerState, showRegion = false }: Props = $props();

  let clientId = $state(providerState.clientId);
  let clientSecret = $state(providerState.clientSecret);
  let saving = $state(false);
  let connecting = $state(false);

  $effect(() => {
    clientId = providerState.clientId;
    clientSecret = providerState.clientSecret;
  });

  let hasCredentials = $derived(clientId.trim() !== "" && clientSecret.trim() !== "");

  async function saveCredentials() {
    saving = true;
    try {
      await saveClientCredentials(provider, clientId, clientSecret);
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
</script>

<div class="border border-gray-200 rounded-lg p-4 bg-white">
  <h3 class="font-medium text-gray-900 mb-3">{label}</h3>

  <div class="space-y-3">
    <label class="block">
      <span class="block text-sm text-gray-600 mb-1">Client ID</span>
      <input
        type="text"
        bind:value={clientId}
        onblur={saveCredentials}
        class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
        placeholder="Enter client ID"
      />
    </label>

    <label class="block">
      <span class="block text-sm text-gray-600 mb-1">Client Secret</span>
      <input
        type="password"
        bind:value={clientSecret}
        onblur={saveCredentials}
        class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
        placeholder="Enter client secret"
      />
    </label>

    {#if showRegion}
      <label class="block">
        <span class="block text-sm text-gray-600 mb-1">Region</span>
        <select class="w-full border border-gray-300 rounded px-3 py-1.5 text-sm">
          <option value="com">.com (US)</option>
          <option value="eu">.eu (Europe)</option>
          <option value="in">.in (India)</option>
          <option value="com.au">.com.au (Australia)</option>
        </select>
      </label>
    {/if}

    <div class="flex items-center justify-between pt-2">
      <div class="text-sm">
        {#if providerState.status === "connected"}
          <span class="text-green-600">Connected{providerState.displayName ? ` as ${providerState.displayName}` : ""}</span>
        {:else if providerState.status === "reconnect_required"}
          <span class="text-amber-600">Reconnect required</span>
        {:else}
          <span class="text-gray-400">Disconnected</span>
        {/if}
      </div>

      <div>
        {#if providerState.status === "connected"}
          <button onclick={handleDisconnect} class="text-sm text-red-600 hover:underline">
            Disconnect
          </button>
        {:else}
          <button
            onclick={connect}
            disabled={!hasCredentials || connecting}
            class="text-sm bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {connecting ? "Connecting..." : "Connect"}
          </button>
        {/if}
      </div>
    </div>

    {#if provider === "microsoft" && providerState.status === "connected"}
      <p class="text-xs text-amber-600 mt-1">
        Note: Personal accounts have limited recording API access. Recording will require manual start.
      </p>
    {/if}
  </div>
</div>
