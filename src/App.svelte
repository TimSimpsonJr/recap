<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { listen } from "@tauri-apps/api/event";
  import Settings from "./routes/Settings.svelte";
  import Dashboard from "./routes/Dashboard.svelte";
  import { loadCredentials, credentials, saveTokens } from "./lib/stores/credentials";
  import type { ProviderName } from "./lib/stores/credentials";
  import { loadSettings, settings } from "./lib/stores/settings";
  import { exchangeOAuthCode } from "./lib/tauri";

  let currentRoute = $state("dashboard");
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
      currentRoute = hash;
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

<main class="min-h-screen bg-gray-50">
  {#if !initialized}
    <div class="flex items-center justify-center h-screen">
      <p class="text-gray-400">Loading...</p>
    </div>
  {:else if currentRoute === "settings"}
    <Settings />
  {:else}
    <Dashboard />
  {/if}
</main>
