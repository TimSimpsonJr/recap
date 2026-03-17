<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { listen } from "@tauri-apps/api/event";
  import Settings from "./routes/Settings.svelte";
  import Dashboard from "./routes/Dashboard.svelte";
  import { loadCredentials, credentials, saveTokens } from "./lib/stores/credentials";
  import type { ProviderName } from "./lib/stores/credentials";
  import { loadSettings } from "./lib/stores/settings";
  import { exchangeOAuthCode } from "./lib/tauri";

  let currentRoute = $state("dashboard");

  onMount(async () => {
    await loadCredentials();
    await loadSettings();

    const updateRoute = () => {
      const hash = window.location.hash.slice(1) || "dashboard";
      currentRoute = hash;
    };
    window.addEventListener("hashchange", updateRoute);
    updateRoute();

    await listen("oauth-callback", async (event: any) => {
      const { provider, code } = event.payload;
      const creds = get(credentials);
      const providerState = creds[provider as ProviderName];

      if (providerState?.clientId && providerState?.clientSecret) {
        try {
          const tokens = await exchangeOAuthCode(
            provider,
            code,
            providerState.clientId,
            providerState.clientSecret
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
  });
</script>

<main class="min-h-screen bg-gray-50">
  {#if currentRoute === "settings"}
    <Settings />
  {:else}
    <Dashboard />
  {/if}
</main>
