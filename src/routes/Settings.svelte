<script lang="ts">
  import ProviderCard from "../lib/components/ProviderCard.svelte";
  import SettingsSection from "../lib/components/SettingsSection.svelte";
  import VaultSettings from "../lib/components/VaultSettings.svelte";
  import RecordingSettings from "../lib/components/RecordingSettings.svelte";
  import WhisperXSettings from "../lib/components/WhisperXSettings.svelte";
  import TodoistSettings from "../lib/components/TodoistSettings.svelte";
  import GeneralSettings from "../lib/components/GeneralSettings.svelte";
  import AboutSection from "../lib/components/AboutSection.svelte";
  import { credentials } from "../lib/stores/credentials";
</script>

<div class="max-w-3xl mx-auto p-8">
  <div class="flex items-center justify-between mb-8">
    <h1 class="text-2xl font-bold text-gray-900">Settings</h1>
    <a href="#dashboard" class="text-blue-600 hover:underline text-sm">Back to Dashboard</a>
  </div>

  <div class="space-y-8">
    <section>
      <h2 class="text-lg font-semibold text-gray-800 mb-4">Platform Connections</h2>
      <div class="space-y-4">
        <ProviderCard provider="zoom" label="Zoom" providerState={$credentials.zoom} />
        <ProviderCard provider="google" label="Google" providerState={$credentials.google} />
        <ProviderCard provider="microsoft" label="Microsoft Teams" providerState={$credentials.microsoft} />
        <ProviderCard provider="zoho" label="Zoho" providerState={$credentials.zoho} showRegion={true} />
        <ProviderCard provider="todoist" label="Todoist" providerState={$credentials.todoist} />
      </div>
    </section>

    <SettingsSection title="Vault">
      <VaultSettings />
    </SettingsSection>

    <SettingsSection title="Recording">
      <RecordingSettings />
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
