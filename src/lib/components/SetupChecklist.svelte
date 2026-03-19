<script lang="ts">
  import { fly } from "svelte/transition";
  import { credentials } from "../stores/credentials";
  import type { ProviderName } from "../stores/credentials";
  import { settings, saveSetting } from "../stores/settings";
  import Modal from "./Modal.svelte";
  import ProviderCard from "./ProviderCard.svelte";

  type ProviderEntry = { provider: ProviderName; label: string; showRegion?: boolean };

  const providers: ProviderEntry[] = [
    { provider: "zoom", label: "Zoom" },
    { provider: "google", label: "Google" },
    { provider: "microsoft", label: "Microsoft Teams" },
    { provider: "zoho", label: "Zoho", showRegion: true },
    { provider: "todoist", label: "Todoist" },
  ];

  interface ChecklistItem {
    id: string;
    label: string;
    completed: boolean;
    action: () => void;
    actionLabel: string;
  }

  let activeModal = $state<ProviderName | null>(null);

  function openModal(provider: ProviderName) {
    activeModal = provider;
  }

  function closeModal() {
    activeModal = null;
  }

  let activeProvider = $derived(providers.find((p) => p.provider === activeModal));

  // Auto-close modal when provider becomes connected
  $effect(() => {
    if (activeModal && $credentials[activeModal]?.status === "connected") {
      activeModal = null;
    }
  });

  async function markExtensionInstalled() {
    await saveSetting("extensionInstalled", true);
  }

  let items = $derived<ChecklistItem[]>([
    {
      id: "zoom",
      label: "Connect Zoom",
      completed: $credentials.zoom.status === "connected",
      action: () => openModal("zoom"),
      actionLabel: "Connect",
    },
    {
      id: "google",
      label: "Connect Google",
      completed: $credentials.google.status === "connected",
      action: () => openModal("google"),
      actionLabel: "Connect",
    },
    {
      id: "microsoft",
      label: "Connect Microsoft Teams",
      completed: $credentials.microsoft.status === "connected",
      action: () => openModal("microsoft"),
      actionLabel: "Connect",
    },
    {
      id: "zoho",
      label: "Connect Zoho",
      completed: $credentials.zoho.status === "connected",
      action: () => openModal("zoho"),
      actionLabel: "Connect",
    },
    {
      id: "todoist",
      label: "Connect Todoist",
      completed: $credentials.todoist.status === "connected",
      action: () => openModal("todoist"),
      actionLabel: "Connect",
    },
    {
      id: "extension",
      label: "Install browser extension",
      completed: $settings.extensionInstalled,
      action: markExtensionInstalled,
      actionLabel: "Done",
    },
  ]);

  let allComplete = $derived(items.every((item) => item.completed));
  let completedCount = $derived(items.filter((item) => item.completed).length);
  let incompleteItems = $derived(items.filter((item) => !item.completed));
  let visible = $derived($settings.onboardingComplete && !allComplete && !$settings.setupChecklistDismissed);
</script>

{#if visible}
  <div
    style="
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px 18px;
      margin-bottom: 14px;
      font-family: 'DM Sans', sans-serif;
    "
  >
    <div
      style="
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 10px;
      "
    >
      <span
        style="
          font-size: 14px;
          font-weight: 600;
          color: var(--text);
        "
      >
        Setup checklist
        <span style="font-weight: 400; color: var(--text-muted); margin-left: 6px;">
          {completedCount}/{items.length}
        </span>
      </span>
      <button
        onclick={() => { saveSetting('setupChecklistDismissed', true); }}
        style="
          background: none;
          border: none;
          color: var(--text-muted);
          font-size: 18px;
          cursor: pointer;
          padding: 0 4px;
          line-height: 1;
        "
        aria-label="Dismiss checklist"
      >
        &times;
      </button>
    </div>

    <div style="display: flex; flex-direction: column; gap: 6px;">
      {#each incompleteItems as item (item.id)}
        <div
          transition:fly={{ x: -20, duration: 300 }}
          style="
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 6px 0;
          "
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style="flex-shrink: 0;">
            <circle cx="8" cy="8" r="7" stroke="var(--border)" stroke-width="1" />
          </svg>
          <span
            style="
              flex: 1;
              font-size: 13.5px;
              color: var(--text);
            "
          >
            {item.label}
          </span>
          <button
            onclick={item.action}
            style="
              font-size: 12.5px;
              background: none;
              border: 1px solid var(--border);
              border-radius: 5px;
              color: var(--gold);
              padding: 3px 10px;
              cursor: pointer;
              font-family: 'DM Sans', sans-serif;
              font-weight: 500;
            "
          >
            {item.actionLabel}
          </button>
        </div>
      {/each}
    </div>
  </div>
{/if}

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
