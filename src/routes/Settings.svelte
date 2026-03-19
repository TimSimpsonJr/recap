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
    modalOpenStatus = $credentials[provider]?.status ?? "disconnected";
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

  let modalOpenStatus = $state<string | null>(null);
  $effect(() => {
    if (activeModal && modalOpenStatus !== "connected" && $credentials[activeModal]?.status === "connected") {
      activeModal = null;
      modalOpenStatus = null;
    }
  });

  let wide = $derived(windowWidth > 1000);
</script>

<svelte:window onresize={() => windowWidth = window.innerWidth} />

<div style="height:100%;overflow-y:auto;background:var(--bg);">
<div style="
  max-width: {wide ? '1000px' : '600px'};
  margin: 0 auto;
  padding: 24px 28px 48px;
  display: flex;
  flex-direction: column;
  gap: 24px;
">
  <!-- Platform Connections — full width -->
  <section>
    <button
      onclick={() => platformsExpanded = !platformsExpanded}
      style="
        width: 100%; display: flex; align-items: center; justify-content: space-between;
        background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
        cursor: pointer; padding: 12px 16px;
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
      <div transition:slide={{ duration: 200 }} style="display:flex;flex-direction:column;gap:4px;margin-top:8px;">
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

  <!-- Two-column row: Vault | Recording -->
  {#if wide}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start;">
      <SettingsSection title="Vault">
        <VaultSettings />
      </SettingsSection>
      <SettingsSection title="Recording">
        <RecordingSettings />
        <div style="border-top:1px solid var(--border);padding-top:12px;">
          <RecordingBehaviorSettings />
        </div>
      </SettingsSection>
    </div>
  {:else}
    <SettingsSection title="Vault">
      <VaultSettings />
    </SettingsSection>
    <SettingsSection title="Recording">
      <RecordingSettings />
      <div style="border-top:1px solid var(--border);padding-top:12px;">
        <RecordingBehaviorSettings />
      </div>
    </SettingsSection>
  {/if}

  <!-- Two-column row: Claude | WhisperX -->
  {#if wide}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start;">
      <SettingsSection title="Claude">
        <ClaudeSettings />
      </SettingsSection>
      <SettingsSection title="WhisperX">
        <WhisperXSettings />
      </SettingsSection>
    </div>
  {:else}
    <SettingsSection title="Claude">
      <ClaudeSettings />
    </SettingsSection>
    <SettingsSection title="WhisperX">
      <WhisperXSettings />
    </SettingsSection>
  {/if}

  <!-- Two-column row: Todoist | General -->
  {#if wide}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start;">
      <SettingsSection title="Todoist">
        <TodoistSettings />
      </SettingsSection>
      <SettingsSection title="General">
        <GeneralSettings />
      </SettingsSection>
    </div>
  {:else}
    <SettingsSection title="Todoist">
      <TodoistSettings />
    </SettingsSection>
    <SettingsSection title="General">
      <GeneralSettings />
    </SettingsSection>
  {/if}

  <!-- About — full width -->
  <SettingsSection title="About">
    <AboutSection />
  </SettingsSection>
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
