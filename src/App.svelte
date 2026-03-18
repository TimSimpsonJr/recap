<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { listen } from "@tauri-apps/api/event";
  import Settings from "./routes/Settings.svelte";
  import Dashboard from "./routes/Dashboard.svelte";
  import GraphView from "./routes/GraphView.svelte";
  import { loadCredentials, credentials, saveTokens } from "./lib/stores/credentials";
  import type { ProviderName } from "./lib/stores/credentials";
  import { loadSettings, settings } from "./lib/stores/settings";
  import { exchangeOAuthCode } from "./lib/tauri";

  let currentRoute = $state("dashboard");
  let meetingId = $state<string | null>(null);
  let initialized = $state(false);

  onMount(async () => {
    try {
      await loadCredentials();
    } catch (err) {
      console.error("Failed to load credentials:", err);
    }
    try {
      await loadSettings();
    } catch (err) {
      console.error("Failed to load settings:", err);
    }
    initialized = true;

    const updateRoute = () => {
      const hash = window.location.hash.slice(1) || "dashboard";
      const meetingMatch = hash.match(/^meeting\/(.+)$/);
      if (meetingMatch) {
        currentRoute = "dashboard";
        meetingId = meetingMatch[1];
      } else {
        currentRoute = hash;
        meetingId = null;
      }
    };
    window.addEventListener("hashchange", updateRoute);
    updateRoute();

    // Deep link flow (Zoom, Zoho, Todoist): receives auth code, exchanges for tokens
    await listen("oauth-callback", async (event: any) => {
      const { provider, code } = event.payload;
      const creds = get(credentials);
      const providerState = creds[provider as ProviderName];

      if (providerState?.clientId && providerState?.clientSecret) {
        try {
          const zohoRegion = provider === "zoho" ? get(settings).zohoRegion : undefined;
          const tokens = await exchangeOAuthCode(
            provider,
            code,
            providerState.clientId,
            providerState.clientSecret,
            zohoRegion
          );
          await saveTokens(
            provider as ProviderName,
            tokens.access_token,
            tokens.refresh_token,
            null
          );
        } catch (err) {
          console.error(`OAuth token exchange failed for ${provider}:`, err);
        }
      }
    });

    // Localhost flow (Google, Microsoft): Rust already exchanged the code, receives tokens directly
    await listen("oauth-tokens", async (event: any) => {
      const { provider, access_token, refresh_token } = event.payload;
      await saveTokens(
        provider as ProviderName,
        access_token,
        refresh_token ?? null,
        null
      );
    });
  });
</script>

<div class="flex flex-col h-screen" style="background: #1D1D1B;">
  {#if !initialized}
    <div
      class="flex items-center justify-center h-screen"
      style="font-family: 'DM Sans', sans-serif; color: #585650;"
    >
      Loading...
    </div>
  {:else}
    <!-- Nav bar -->
    <nav
      class="flex items-center shrink-0"
      style="
        height: 48px;
        padding: 0 28px;
        background: #1A1A18;
        border-bottom: 1px solid #262624;
        font-family: 'DM Sans', sans-serif;
        gap: 24px;
      "
    >
      <span
        style="
          font-family: 'Source Serif 4', serif;
          font-size: 18px;
          font-weight: 700;
          color: #D8D5CE;
          margin-right: 12px;
        "
      >
        Recap
      </span>
      <a
        href="#dashboard"
        style="
          font-size: 14.5px;
          text-decoration: none;
          padding: 10px 0;
          border-bottom: 2px solid {currentRoute === 'dashboard' ? '#A8A078' : 'transparent'};
          color: {currentRoute === 'dashboard' ? '#A8A078' : '#585650'};
        "
      >Meetings</a>
      <a
        href="#graph"
        style="
          font-size: 14.5px;
          text-decoration: none;
          padding: 10px 0;
          border-bottom: 2px solid {currentRoute === 'graph' ? '#A8A078' : 'transparent'};
          color: {currentRoute === 'graph' ? '#A8A078' : '#585650'};
        "
      >Graph</a>
      <a
        href="#settings"
        style="
          font-size: 14.5px;
          text-decoration: none;
          padding: 10px 0;
          border-bottom: 2px solid {currentRoute === 'settings' ? '#A8A078' : 'transparent'};
          color: {currentRoute === 'settings' ? '#A8A078' : '#585650'};
        "
      >Settings</a>
    </nav>

    <!-- Route content -->
    <div class="flex-1 overflow-hidden">
      {#if currentRoute === "settings"}
        <Settings />
      {:else if currentRoute === "graph"}
        <GraphView />
      {:else}
        <Dashboard initialMeetingId={meetingId} />
      {/if}
    </div>
  {/if}
</div>
