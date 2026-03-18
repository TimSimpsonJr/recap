<script lang="ts">
  import type { ProviderState } from "../stores/credentials";

  interface Props {
    label: string;
    providerState: ProviderState;
    onconfigure: () => void;
  }

  let { label, providerState, onconfigure }: Props = $props();

  let isConnected = $derived(providerState.status === "connected");
  let needsReconnect = $derived(providerState.status === "reconnect_required");
</script>

<div
  style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:var(--surface);border-radius:8px;"
>
  <div style="display:flex;align-items:center;gap:10px;">
    <span style="font-family:'DM Sans',sans-serif;font-size:15.5px;font-weight:500;color:var(--text);">
      {label}
    </span>
  </div>

  <div style="display:flex;align-items:center;gap:12px;">
    <div style="display:flex;align-items:center;gap:6px;">
      {#if isConnected}
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--green);"></span>
        <span style="font-size:14px;color:var(--text-secondary);">
          Connected{providerState.displayName ? ` as ${providerState.displayName}` : ""}
        </span>
      {:else if needsReconnect}
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--warning);"></span>
        <span style="font-size:14px;color:var(--warning);">Reconnect required</span>
      {:else}
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--text-faint);"></span>
        <span style="font-size:14px;color:var(--text-muted);">Not connected</span>
      {/if}
    </div>

    <button
      onclick={onconfigure}
      style="font-family:'DM Sans',sans-serif;font-size:14px;color:var(--gold);background:none;border:1px solid var(--gold);border-radius:6px;padding:4px 12px;cursor:pointer;"
      onmouseenter={(e) => { e.currentTarget.style.background = 'rgba(168,160,120,0.1)'; }}
      onmouseleave={(e) => { e.currentTarget.style.background = 'none'; }}
    >
      Configure
    </button>
  </div>
</div>
