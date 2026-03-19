<script lang="ts">
  import type { ProviderName } from "../lib/stores/credentials";
  import ProviderCard from "../lib/components/ProviderCard.svelte";
  import ProviderStatusCard from "../lib/components/ProviderStatusCard.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import SettingsSection from "../lib/components/SettingsSection.svelte";
  import VaultSettings from "../lib/components/VaultSettings.svelte";
  import RecordingSettings from "../lib/components/RecordingSettings.svelte";
  import RecordingBehaviorSettings from "../lib/components/RecordingBehaviorSettings.svelte";
  import ClaudeSettings from "../lib/components/ClaudeSettings.svelte";
  import WhisperXSettings from "../lib/components/WhisperXSettings.svelte";
  import TodoistSettings from "../lib/components/TodoistSettings.svelte";
  import GeneralSettings from "../lib/components/GeneralSettings.svelte";
  import AboutSection from "../lib/components/AboutSection.svelte";
  import { credentials } from "../lib/stores/credentials";
  import { slide } from "svelte/transition";

  type ProviderEntry = { provider: ProviderName; label: string; showRegion?: boolean };

  const providers: ProviderEntry[] = [
    { provider: "zoom", label: "Zoom" },
    { provider: "google", label: "Google" },
    { provider: "microsoft", label: "Microsoft Teams" },
    { provider: "zoho", label: "Zoho", showRegion: true },
    { provider: "todoist", label: "Todoist" },
  ];

  let activeModal = $state<ProviderName | null>(null);
  let platformsExpanded = $state(false);
  let windowWidth = $state(window.innerWidth);

  function openModal(provider: ProviderName) {
    activeModal = provider;
  }

  function closeModal() {
    activeModal = null;
  }

  let activeProvider = $derived(providers.find((p) => p.provider === activeModal));

  function isConnected(provider: ProviderName): boolean {
    return $credentials[provider]?.status === "connected";
  }

  function needsReconnect(provider: ProviderName): boolean {
    return $credentials[provider]?.status === "reconnect_required";
  }

  function statusColor(provider: ProviderName): string {
    if (isConnected(provider)) return "var(--green)";
    if (needsReconnect(provider)) return "var(--warning)";
    return "var(--text-faint)";
  }

  // Auto-close modal when provider becomes connected
  $effect(() => {
    if (activeModal && $credentials[activeModal]?.status === "connected") {
      activeModal = null;
    }
  });

  function handleResize() {
    windowWidth = window.innerWidth;
  }
</script>

<svelte:window onresize={handleResize} />

<div style="height:100%;overflow-y:auto;background:var(--bg);">
<div style="
  display: grid;
  grid-template-columns: {windowWidth > 1000 ? '1fr 1fr' : '1fr'};
  gap: 24px;
  max-width: {windowWidth > 1000 ? '1000px' : '700px'};
  margin: 0 auto;
  padding: 24px 28px 48px;
">
    <!-- Platform Connections spans both columns -->
    <div style="grid-column: 1 / -1;">
      <section>
        <!-- Collapsible header -->
        <button
          onclick={() => platformsExpanded = !platformsExpanded}
          style="
            width:100%;display:flex;align-items:center;justify-content:space-between;
            background:none;border:none;cursor:pointer;padding:0;margin-bottom:{platformsExpanded ? '12px' : '0'};
          "
        >
          <div style="display:flex;align-items:center;gap:12px;">
            <h2 style="font-family:'Source Serif 4',serif;font-size:18px;font-weight:600;color:var(--text);margin:0;">
              Platform Connections
            </h2>
            <div style="display:flex;align-items:center;gap:6px;">
              {#each providers as p}
                <span style="
                  display:inline-block;width:8px;height:8px;border-radius:50%;
                  background:{statusColor(p.provider)};
                "></span>
              {/each}
            </div>
          </div>
          <svg
            width="16" height="16" viewBox="0 0 16 16" fill="none"
            stroke="var(--text-muted)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
            style="transform:rotate({platformsExpanded ? '180deg' : '0deg'});transition:transform 0.2s ease;"
          >
            <path d="M4 6l4 4 4-4"/>
          </svg>
        </button>

        {#if platformsExpanded}
          <div transition:slide={{ duration: 200 }} style="display:flex;flex-direction:column;gap:4px;">
            {#each providers as p}
              <ProviderStatusCard
                label={p.label}
                providerState={$credentials[p.provider]}
                onconfigure={() => openModal(p.provider)}
              />
            {/each}
          </div>
        {/if}
      </section>
    </div>

    <SettingsSection title="Vault">
      <VaultSettings />
    </SettingsSection>

    <SettingsSection title="Recording">
      <RecordingSettings />
      <div style="border-top:1px solid var(--border);padding-top:12px;">
        <RecordingBehaviorSettings />
      </div>
    </SettingsSection>

    <SettingsSection title="Claude">
      <ClaudeSettings />
    </SettingsSection>

    <SettingsSection title="WhisperX">
      <WhisperXSettings />
    </SettingsSection>

    <SettingsSection title="Todoist">
      <TodoistSettings />
    </SettingsSection>

    <SettingsSection title="General">
      <GeneralSettings />
    </SettingsSection>

    <div style="grid-column: 1 / -1;">
      <SettingsSection title="About">
        <AboutSection />
      </SettingsSection>
    </div>
</div>
</div>

{#if activeModal && activeProvider}
  <Modal title="{activeProvider.label} Connection" onclose={closeModal}>
    <ProviderCard
      provider={activeProvider.provider}
      label={activeProvider.label}
      providerState={$credentials[activeProvider.provider]}
      showRegion={activeProvider.showRegion ?? false}
    />
  </Modal>
{/if}
