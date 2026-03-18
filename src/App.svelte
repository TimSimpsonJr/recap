<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { listen } from "@tauri-apps/api/event";
  import Settings from "./routes/Settings.svelte";
  import Dashboard from "./routes/Dashboard.svelte";
  import Calendar from "./routes/Calendar.svelte";
  import GraphView from "./routes/GraphView.svelte";
  import { loadCredentials, credentials, saveTokens } from "./lib/stores/credentials";
  import type { ProviderName } from "./lib/stores/credentials";
  import { loadSettings, settings, saveSetting } from "./lib/stores/settings";
  import { exchangeOAuthCode, syncCalendar } from "./lib/tauri";

  function setZoom(level: number) {
    const clamped = Math.round(Math.min(2.0, Math.max(0.5, level)) * 10) / 10;
    document.documentElement.style.zoom = String(clamped);
    saveSetting("zoomLevel", clamped);
  }

  function handleKeydown(e: KeyboardEvent) {
    if (!e.ctrlKey) return;
    if (e.key === "=" || e.key === "+") {
      e.preventDefault();
      setZoom((get(settings).zoomLevel ?? 1.0) + 0.1);
    } else if (e.key === "-") {
      e.preventDefault();
      setZoom((get(settings).zoomLevel ?? 1.0) - 0.1);
    } else if (e.key === "0") {
      e.preventDefault();
      setZoom(1.0);
    }
  }

  function handleWheel(e: WheelEvent) {
    if (!e.ctrlKey) return;
    e.preventDefault();
    const current = get(settings).zoomLevel ?? 1.0;
    setZoom(current + (e.deltaY < 0 ? 0.1 : -0.1));
  }

  let currentRoute = $state("dashboard");
  let meetingId = $state<string | null>(null);
  let filterParticipant = $state<string | null>(null);
  let initialized = $state(false);

  // D5: Auto-sync calendar on window focus, debounced to once per 15 min
  let lastCalendarSync = $state(0);

  function handleWindowFocus() {
    const now = Date.now();
    const fifteenMinutes = 15 * 60 * 1000;
    if (now - lastCalendarSync > fifteenMinutes) {
      lastCalendarSync = now;
      syncCalendar().catch(() => {}); // silent background sync
    }
  }

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

    // Apply persisted zoom level
    const savedZoom = get(settings).zoomLevel;
    if (savedZoom && savedZoom !== 1.0) {
      document.documentElement.style.zoom = String(savedZoom);
    }

    const updateRoute = () => {
      const hash = window.location.hash.slice(1) || "dashboard";
      const meetingMatch = hash.match(/^meeting\/(.+)$/);
      const filterMatch = hash.match(/^filter\/participant\/(.+)$/);
      if (meetingMatch) {
        currentRoute = "dashboard";
        meetingId = meetingMatch[1];
        filterParticipant = null;
      } else if (filterMatch) {
        currentRoute = "dashboard";
        meetingId = null;
        filterParticipant = decodeURIComponent(filterMatch[1]);
      } else {
        currentRoute = hash;
        meetingId = null;
        filterParticipant = null;
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

<svelte:window onkeydown={handleKeydown} onfocus={handleWindowFocus} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="flex flex-col h-screen" style="background: var(--bg);" onwheel={handleWheel}>
  {#if !initialized}
    <div
      class="flex items-center justify-center h-screen"
      style="font-family: 'DM Sans', sans-serif; color: var(--text-faint);"
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
        background: var(--bg);
        border-bottom: 1px solid var(--border);
        font-family: 'DM Sans', sans-serif;
        gap: 24px;
      "
    >
      <span
        style="
          font-family: 'Source Serif 4', serif;
          font-size: 18px;
          font-weight: 700;
          color: var(--text);
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
          border-bottom: 2px solid {currentRoute === 'dashboard' ? 'var(--gold)' : 'transparent'};
          color: {currentRoute === 'dashboard' ? 'var(--gold)' : 'var(--text-faint)'};
        "
      >Meetings</a>
      <a
        href="#calendar"
        style="
          font-size: 14.5px;
          text-decoration: none;
          padding: 10px 0;
          border-bottom: 2px solid {currentRoute === 'calendar' ? 'var(--gold)' : 'transparent'};
          color: {currentRoute === 'calendar' ? 'var(--gold)' : 'var(--text-faint)'};
        "
      >Calendar</a>
      <a
        href="#graph"
        style="
          font-size: 14.5px;
          text-decoration: none;
          padding: 10px 0;
          border-bottom: 2px solid {currentRoute === 'graph' ? 'var(--gold)' : 'transparent'};
          color: {currentRoute === 'graph' ? 'var(--gold)' : 'var(--text-faint)'};
        "
      >Graph</a>
      <a
        href="#settings"
        style="
          font-size: 14.5px;
          text-decoration: none;
          padding: 10px 0;
          border-bottom: 2px solid {currentRoute === 'settings' ? 'var(--gold)' : 'transparent'};
          color: {currentRoute === 'settings' ? 'var(--gold)' : 'var(--text-faint)'};
        "
      >Settings</a>
    </nav>

    <!-- Route content -->
    <div class="flex-1 overflow-hidden">
      {#if currentRoute === "settings"}
        <Settings />
      {:else if currentRoute === "calendar"}
        <Calendar />
      {:else if currentRoute === "graph"}
        <GraphView />
      {:else}
        <Dashboard initialMeetingId={meetingId} initialFilterParticipant={filterParticipant} />
      {/if}
    </div>
  {/if}
</div>
