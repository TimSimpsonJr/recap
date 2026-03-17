<script lang="ts">
  import { onMount } from "svelte";
  import Settings from "./routes/Settings.svelte";
  import Dashboard from "./routes/Dashboard.svelte";
  import { loadCredentials } from "./lib/stores/credentials";
  import { loadSettings } from "./lib/stores/settings";

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
  });
</script>

<main class="min-h-screen bg-gray-50">
  {#if currentRoute === "settings"}
    <Settings />
  {:else}
    <Dashboard />
  {/if}
</main>
