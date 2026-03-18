<script lang="ts">
  import type { ProviderName } from "../lib/stores/credentials";
  import ProviderCard from "../lib/components/ProviderCard.svelte";
  import ProviderStatusCard from "../lib/components/ProviderStatusCard.svelte";
  import Modal from "../lib/components/Modal.svelte";
  import SettingsSection from "../lib/components/SettingsSection.svelte";
  import VaultSettings from "../lib/components/VaultSettings.svelte";
  import RecordingSettings from "../lib/components/RecordingSettings.svelte";
  import RecordingBehaviorSettings from "../lib/components/RecordingBehaviorSettings.svelte";
  import WhisperXSettings from "../lib/components/WhisperXSettings.svelte";
  import TodoistSettings from "../lib/components/TodoistSettings.svelte";
  import GeneralSettings from "../lib/components/GeneralSettings.svelte";
  import AboutSection from "../lib/components/AboutSection.svelte";
  import { credentials } from "../lib/stores/credentials";

  type ProviderEntry = { provider: ProviderName; label: string; showRegion?: boolean };

  const providers: ProviderEntry[] = [
    { provider: "zoom", label: "Zoom" },
    { provider: "google", label: "Google" },
    { provider: "microsoft", label: "Microsoft Teams" },
    { provider: "zoho", label: "Zoho", showRegion: true },
    { provider: "todoist", label: "Todoist" },
  ];

  let activeModal = $state<ProviderName | null>(null);

  function openModal(provider: ProviderName) {
    activeModal = provider;
  }

  function closeModal() {
    activeModal = null;
  }

  let activeProvider = $derived(providers.find((p) => p.provider === activeModal));
</script>

<div style="max-width:700px;margin:0 auto;padding:24px 28px 48px;">
  <div style="display:flex;flex-direction:column;gap:28px;">
    <section>
      <h2 style="font-family:'Source Serif 4',serif;font-size:16px;font-weight:600;color:#D8D5CE;margin-bottom:12px;">
        Platform Connections
      </h2>
      <div style="display:flex;flex-direction:column;gap:4px;">
        {#each providers as p}
          <ProviderStatusCard
            label={p.label}
            providerState={$credentials[p.provider]}
            onconfigure={() => openModal(p.provider)}
          />
        {/each}
      </div>
    </section>

    <SettingsSection title="Vault">
      <VaultSettings />
    </SettingsSection>

    <SettingsSection title="Recording">
      <RecordingSettings />
      <div style="border-top:1px solid #262624;padding-top:12px;">
        <RecordingBehaviorSettings />
      </div>
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
