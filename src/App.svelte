<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { get } from "svelte/store";
  import { listen } from "@tauri-apps/api/event";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import Settings from "./routes/Settings.svelte";
  import Dashboard from "./routes/Dashboard.svelte";
  import Calendar from "./routes/Calendar.svelte";
  import GraphView from "./routes/GraphView.svelte";
  import { loadCredentials, credentials, saveTokens } from "./lib/stores/credentials";
  import type { ProviderName } from "./lib/stores/credentials";
  import { loadSettings, settings, saveSetting } from "./lib/stores/settings";
  import { exchangeOAuthCode, syncCalendar } from "./lib/tauri";
  import Onboarding from "./lib/components/Onboarding.svelte";
  import ToastContainer from "./lib/components/ToastContainer.svelte";
  import { fade } from "svelte/transition";
  import logoSvg from "./lib/assets/logo.svg";

  const appWindow = getCurrentWindow();

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
  let windowWidth = $state(window.innerWidth);

  function handleResize() {
    windowWidth = window.innerWidth;
  }

  // D5: Auto-sync calendar on window focus, debounced to once per 15 min
  let lastCalendarSync = $state(0);

  function handleWindowFocus() {
    const now = Date.now();
    const fifteenMinutes = 15 * 60 * 1000;
    if (now - lastCalendarSync > fifteenMinutes) {
      lastCalendarSync = now;
      syncCalendar().catch((err) => {
        console.warn("Calendar auto-sync failed:", err);
      });
    }
  }

  onDestroy(() => {
    window.removeEventListener("resize", handleResize);
  });

  onMount(async () => {
    window.addEventListener("resize", handleResize);

    // Load settings first (fast, plugin-store) so UI can render immediately
    try {
      await loadSettings();
    } catch (err) {
      console.error("Failed to load settings:", err);
    }
    initialized = true;

    // Load credentials in background
    loadCredentials().catch((err) => {
      console.error("Failed to load credentials:", err);
    });

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
<div class="flex flex-col h-screen overflow-hidden" style="background: var(--bg);" onwheel={handleWheel}>
  {#if !initialized}
    <div
      class="flex items-center justify-center h-screen"
      style="font-family: 'DM Sans', sans-serif; color: var(--text-faint);"
    >
      Loading...
    </div>
  {:else}
    {#if !$settings.onboardingComplete}
      <Onboarding />
    {:else}
    <!-- Title bar + Nav -->
    <nav
      data-tauri-drag-region
      class="flex items-center shrink-0"
      style="
        height: 48px;
        padding: 0 16px 0 28px;
        background: var(--bg);
        border-bottom: 1px solid var(--border);
        font-family: 'DM Sans', sans-serif;
        gap: 24px;
        user-select: none;
      "
    >
      <!-- Logo + Title -->
      <span
        class="flex items-center gap-2"
        style="
          font-family: 'Source Serif 4', serif;
          font-size: 18px;
          font-weight: 700;
          color: var(--text);
          margin-right: 12px;
          -webkit-app-region: no-drag;
        "
      >
        <img src={logoSvg} alt="Recap" width="22" height="22" />
        Recap
      </span>

      <!-- Nav links -->
      <a
        href="#dashboard"
        class="nav-link"
        title="Meetings"
        style="
          font-size: 14.5px;
          text-decoration: none;
          padding: 10px 0;
          display: flex;
          align-items: center;
          gap: 6px;
          border-bottom: 2px solid {currentRoute === 'dashboard' ? 'var(--gold)' : 'transparent'};
          color: {currentRoute === 'dashboard' ? 'var(--gold)' : 'var(--text-faint)'};
          -webkit-app-region: no-drag;
        "
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M2 4h12M2 8h12M2 12h12"/>
        </svg>
        <span style="display:{windowWidth >= 900 ? 'inline' : 'none'};">Meetings</span>
      </a>
      <a
        href="#calendar"
        class="nav-link"
        title="Calendar"
        style="
          font-size: 14.5px;
          text-decoration: none;
          padding: 10px 0;
          display: flex;
          align-items: center;
          gap: 6px;
          border-bottom: 2px solid {currentRoute === 'calendar' ? 'var(--gold)' : 'transparent'};
          color: {currentRoute === 'calendar' ? 'var(--gold)' : 'var(--text-faint)'};
          -webkit-app-region: no-drag;
        "
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="3" width="12" height="11" rx="1.5"/><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3"/>
        </svg>
        <span style="display:{windowWidth >= 900 ? 'inline' : 'none'};">Calendar</span>
      </a>
      <a
        href="#graph"
        class="nav-link"
        title="Graph"
        style="
          font-size: 14.5px;
          text-decoration: none;
          padding: 10px 0;
          display: flex;
          align-items: center;
          gap: 6px;
          border-bottom: 2px solid {currentRoute === 'graph' ? 'var(--gold)' : 'transparent'};
          color: {currentRoute === 'graph' ? 'var(--gold)' : 'var(--text-faint)'};
          -webkit-app-region: no-drag;
        "
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="4" cy="5" r="2"/><circle cx="12" cy="4" r="2"/><circle cx="8" cy="12" r="2"/><path d="M5.7 6.3L6.8 10.5M10.3 5.3L9.2 10.5"/>
        </svg>
        <span style="display:{windowWidth >= 900 ? 'inline' : 'none'};">Graph</span>
      </a>
      <a
        href="#settings"
        class="nav-link"
        title="Settings"
        style="
          font-size: 14.5px;
          text-decoration: none;
          padding: 10px 0;
          display: flex;
          align-items: center;
          gap: 6px;
          border-bottom: 2px solid {currentRoute === 'settings' ? 'var(--gold)' : 'transparent'};
          color: {currentRoute === 'settings' ? 'var(--gold)' : 'var(--text-faint)'};
          -webkit-app-region: no-drag;
        "
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="8" cy="8" r="2.5"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/>
        </svg>
        <span style="display:{windowWidth >= 900 ? 'inline' : 'none'};">Settings</span>
      </a>

      <!-- Spacer -->
      <div class="flex-1"></div>

      <!-- Window controls -->
      <div class="flex items-center" style="-webkit-app-region: no-drag;">
        <button
          class="titlebar-btn"
          onclick={() => appWindow.minimize()}
          aria-label="Minimize"
        >
          <svg width="12" height="12" viewBox="0 0 12 12">
            <rect x="1" y="5.5" width="10" height="1" fill="currentColor"/>
          </svg>
        </button>
        <button
          class="titlebar-btn"
          onclick={() => appWindow.toggleMaximize()}
          aria-label="Maximize"
        >
          <svg width="12" height="12" viewBox="0 0 12 12">
            <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" stroke-width="1.2"/>
          </svg>
        </button>
        <button
          class="titlebar-btn titlebar-close"
          onclick={() => appWindow.close()}
          aria-label="Close"
        >
          <svg width="12" height="12" viewBox="0 0 12 12">
            <path d="M2 2L10 10M10 2L2 10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
          </svg>
        </button>
      </div>
    </nav>

    <!-- Route content -->
    {#key currentRoute}
      <div class="flex-1 overflow-hidden" transition:fade={{ duration: 150 }}>
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
    {/key}
    {/if}
  {/if}
  <ToastContainer />
</div>
