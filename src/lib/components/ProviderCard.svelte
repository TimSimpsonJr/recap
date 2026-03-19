<script lang="ts">
  import { type ProviderName, type ProviderState, saveClientCredentials, disconnect } from "../stores/credentials";
  import { startOAuth } from "../tauri";
  import { settings, saveSetting } from "../stores/settings";
  import { openUrl } from "@tauri-apps/plugin-opener";

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
  let showGuide = $state(false);

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

  function handleWindowClick() {
    if (showGuide) showGuide = false;
  }

  function handleGuideClick(e: MouseEvent) {
    e.stopPropagation();
    const target = e.target as HTMLElement;
    const anchor = target.closest("a");
    if (anchor?.href) {
      e.preventDefault();
      openUrl(anchor.href);
    }
  }

  type GuideInfo = { url: string; steps: string[]; redirectUri: string; note?: string };

  const guides: Record<ProviderName, GuideInfo> = {
    zoom: {
      url: "https://marketplace.zoom.us/develop/create",
      steps: [
        'Go to the <a href="https://marketplace.zoom.us/develop/create" target="_blank" rel="noopener noreferrer" style="color:var(--blue);">Zoom App Marketplace</a>',
        'Select <strong>General App</strong> and click "Create"',
        'Under OAuth redirect URL, add: <code style="background:var(--bg);padding:1px 4px;border-radius:3px;font-size:12px;">recap://oauth/zoom/callback</code>',
        'Go to the <strong>Scopes</strong> tab and add: <strong>meeting:read</strong>, <strong>recording:read</strong>, <strong>user:read</strong>',
        'Copy the <strong>Client ID</strong> and <strong>Client Secret</strong> from the <strong>App Credentials</strong> section',
      ],
      redirectUri: "recap://oauth/zoom/callback",
    },
    google: {
      url: "https://console.cloud.google.com/apis/credentials",
      steps: [
        'Go to <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" style="color:var(--blue);">Google Cloud Console → Credentials</a>',
        'Click "Create Credentials" → <strong>OAuth client ID</strong>',
        'Application type: <strong>Desktop app</strong>',
        'Enable the <strong>Google Calendar API</strong> and <strong>Google Meet REST API</strong> in your project',
        "Copy the <strong>Client ID</strong> and <strong>Client Secret</strong> from the created credential",
      ],
      redirectUri: "http://localhost (auto-assigned)",
      note: "You may need to configure the OAuth consent screen first. Set it to External and add your Google account as a test user.",
    },
    microsoft: {
      url: "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
      steps: [
        'Go to <a href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade" target="_blank" rel="noopener noreferrer" style="color:var(--blue);">Azure Portal → App Registrations</a>',
        'Click "New registration"',
        'Under Redirect URI, select <strong>Mobile and desktop applications</strong> and add: <code style="background:var(--bg);padding:1px 4px;border-radius:3px;font-size:12px;">http://localhost</code>',
        'Go to "Certificates & secrets" → New client secret → copy the <strong>Value</strong> (this is your Client Secret)',
        'Copy the <strong>Application (client) ID</strong> from the Overview page',
      ],
      redirectUri: "http://localhost",
      note: "Personal Microsoft accounts have limited meeting API access. Calendar integration will still work.",
    },
    zoho: {
      url: "https://api-console.zoho.com/",
      steps: [
        'Go to <a href="https://api-console.zoho.com/" target="_blank" rel="noopener noreferrer" style="color:var(--blue);">Zoho API Console</a>',
        'Click "Add Client" → choose <strong>Server-based Applications</strong>',
        'Set the Redirect URI to: <code style="background:var(--bg);padding:1px 4px;border-radius:3px;font-size:12px;">recap://oauth/zoho/callback</code>',
        "Add scopes: <strong>ZohoMeeting.manageOrg.READ</strong>, <strong>ZohoCalendar.calendar.READ</strong>",
        "Copy the <strong>Client ID</strong> and <strong>Client Secret</strong>",
      ],
      redirectUri: "recap://oauth/zoho/callback",
      note: "Make sure to select the correct region above to match your Zoho account.",
    },
    todoist: {
      url: "https://developer.todoist.com/appconsole.html",
      steps: [
        'Go to <a href="https://developer.todoist.com/appconsole.html" target="_blank" rel="noopener noreferrer" style="color:var(--blue);">Todoist App Console</a>',
        'Click "Create a new app"',
        'Set the OAuth redirect URL to: <code style="background:var(--bg);padding:1px 4px;border-radius:3px;font-size:12px;">recap://oauth/todoist/callback</code>',
        "Copy the <strong>Client ID</strong> and <strong>Client Secret</strong> from the app settings",
      ],
      redirectUri: "recap://oauth/todoist/callback",
    },
  };

  let guide = $derived(guides[provider]);

  const inputStyle = "width:100%;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:15px;color:var(--text);font-family:'DM Sans',sans-serif;outline:none;";
  const labelStyle = "display:block;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;";
  const guideIconStyle = "display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;margin-left:6px;border-radius:50%;background:var(--border);color:var(--text-muted);font-size:11px;font-weight:700;cursor:pointer;user-select:none;flex-shrink:0;";
</script>

<svelte:window onclick={handleWindowClick} />

<div style="display:flex;flex-direction:column;gap:12px;">
  <div style="position:relative;">
    <div style="display:flex;align-items:center;margin-bottom:8px;">
      <span style="font-size:13px;color:var(--text-muted);font-family:'DM Sans',sans-serif;">How do I get these credentials?</span>
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <span
        onclick={(e) => { e.stopPropagation(); showGuide = !showGuide; }}
        style={guideIconStyle}
        title="Setup guide"
      >?</span>
    </div>

    {#if showGuide}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        onclick={handleGuideClick}
        style="
          position:absolute;
          top:100%;
          left:0;
          right:0;
          background:var(--raised, var(--surface));
          border:1px solid var(--border);
          border-radius:8px;
          padding:16px 18px;
          font-size:13px;
          color:var(--text-secondary);
          line-height:1.6;
          z-index:100;
          box-shadow:0 8px 24px rgba(0,0,0,0.4);
        "
      >
        <div style="margin-bottom:10px;">
          <span style="font-weight:600;color:var(--text);font-size:14px;">Setup Guide</span>
        </div>
        <ol style="margin:0;padding-left:20px;">
          {#each guide.steps as step}
            <li style="margin-bottom:4px;">{@html step}</li>
          {/each}
        </ol>
        {#if guide.note}
          <p style="margin:10px 0 0;font-size:12.5px;color:var(--warning);line-height:1.5;">
            <strong>Note:</strong> {guide.note}
          </p>
        {/if}
      </div>
    {/if}
  </div>

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
    <div style="font-size:14.5px;">
      {#if providerState.status === "connected"}
        <span style="color:var(--green);">Connected{providerState.displayName ? ` as ${providerState.displayName}` : ""}</span>
      {:else if providerState.status === "reconnect_required"}
        <span style="color:var(--warning);">Reconnect required</span>
      {:else}
        <span style="color:var(--text-muted);">Disconnected</span>
      {/if}
    </div>

    <div>
      {#if providerState.status === "connected"}
        <button
          onclick={handleDisconnect}
          style="font-size:14.5px;color:var(--red);background:none;border:none;cursor:pointer;font-family:'DM Sans',sans-serif;"
          onmouseenter={(e) => { e.currentTarget.style.textDecoration = 'underline'; }}
          onmouseleave={(e) => { e.currentTarget.style.textDecoration = 'none'; }}
        >
          Disconnect
        </button>
      {:else}
        <button
          onclick={connect}
          disabled={!hasCredentials || connecting}
          style="font-size:14.5px;background:var(--gold);color:var(--bg);padding:6px 16px;border-radius:6px;border:none;cursor:pointer;font-family:'DM Sans',sans-serif;font-weight:500;opacity:{!hasCredentials || connecting ? '0.5' : '1'};"
        >
          {connecting ? "Connecting..." : "Connect"}
        </button>
      {/if}
    </div>
  </div>

  {#if provider === "microsoft" && providerState.status === "connected"}
    <p style="font-size:13.5px;color:var(--warning);margin-top:4px;">
      Note: Personal accounts have limited recording API access. Recording will require manual start.
    </p>
  {/if}
</div>
