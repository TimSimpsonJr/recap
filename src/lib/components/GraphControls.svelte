<script lang="ts">
  interface GroupDef {
    label: string;
    color: string;
  }

  interface Props {
    // Filter
    filterQuery: string;
    onFilterChange: (query: string) => void;

    // Groups
    groups: GroupDef[];

    // Display
    showLabels: boolean;
    onShowLabelsChange: (v: boolean) => void;
    showArrows: boolean;
    onShowArrowsChange: (v: boolean) => void;
    showOrphans: boolean;
    onShowOrphansChange: (v: boolean) => void;

    // Forces
    centerForce: number;
    onCenterForceChange: (v: number) => void;
    repelForce: number;
    onRepelForceChange: (v: number) => void;
    linkDistance: number;
    onLinkDistanceChange: (v: number) => void;
    linkStrength: number;
    onLinkStrengthChange: (v: number) => void;
  }

  let {
    filterQuery,
    onFilterChange,
    groups,
    showLabels,
    onShowLabelsChange,
    showArrows,
    onShowArrowsChange,
    showOrphans,
    onShowOrphansChange,
    centerForce,
    onCenterForceChange,
    repelForce,
    onRepelForceChange,
    linkDistance,
    onLinkDistanceChange,
    linkStrength,
    onLinkStrengthChange,
  }: Props = $props();

  let panelOpen = $state(true);
  let filtersOpen = $state(true);
  let groupsOpen = $state(true);
  let displayOpen = $state(true);
  let forcesOpen = $state(true);
</script>

<div class="graph-controls-wrapper">
  <!-- Toggle button -->
  <button
    class="toggle-btn"
    onclick={() => panelOpen = !panelOpen}
    title={panelOpen ? "Hide graph settings" : "Show graph settings"}
  >
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  </button>

  {#if panelOpen}
    <div class="graph-controls-panel">
      <!-- Filters section -->
      <div class="section">
        <button class="section-header" onclick={() => filtersOpen = !filtersOpen}>
          <span class="section-arrow">{filtersOpen ? "\u25BC" : "\u25B6"}</span>
          Filters
        </button>
        {#if filtersOpen}
          <div class="section-body">
            <input
              type="text"
              class="filter-input"
              placeholder="Filter nodes..."
              value={filterQuery}
              oninput={(e) => onFilterChange((e.target as HTMLInputElement).value)}
            />
          </div>
        {/if}
      </div>

      <!-- Groups section -->
      <div class="section">
        <button class="section-header" onclick={() => groupsOpen = !groupsOpen}>
          <span class="section-arrow">{groupsOpen ? "\u25BC" : "\u25B6"}</span>
          Groups
        </button>
        {#if groupsOpen}
          <div class="section-body">
            {#each groups as group}
              <div class="group-row">
                <span
                  class="group-swatch"
                  style="background: {group.color};"
                ></span>
                <span class="group-label">{group.label}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>

      <!-- Display section -->
      <div class="section">
        <button class="section-header" onclick={() => displayOpen = !displayOpen}>
          <span class="section-arrow">{displayOpen ? "\u25BC" : "\u25B6"}</span>
          Display
        </button>
        {#if displayOpen}
          <div class="section-body">
            <label class="toggle-row">
              <input
                type="checkbox"
                class="ctrl-checkbox"
                checked={showLabels}
                onchange={() => onShowLabelsChange(!showLabels)}
              />
              Show labels
            </label>
            <label class="toggle-row">
              <input
                type="checkbox"
                class="ctrl-checkbox"
                checked={showArrows}
                onchange={() => onShowArrowsChange(!showArrows)}
              />
              Show arrows on edges
            </label>
            <label class="toggle-row">
              <input
                type="checkbox"
                class="ctrl-checkbox"
                checked={showOrphans}
                onchange={() => onShowOrphansChange(!showOrphans)}
              />
              Show orphan nodes
            </label>
          </div>
        {/if}
      </div>

      <!-- Forces section -->
      <div class="section">
        <button class="section-header" onclick={() => forcesOpen = !forcesOpen}>
          <span class="section-arrow">{forcesOpen ? "\u25BC" : "\u25B6"}</span>
          Forces
        </button>
        {#if forcesOpen}
          <div class="section-body">
            <label class="slider-row">
              <span class="slider-label">Center force</span>
              <input
                type="range"
                class="slider"
                min="0"
                max="100"
                value={centerForce}
                oninput={(e) => onCenterForceChange(Number((e.target as HTMLInputElement).value))}
              />
              <span class="slider-value">{centerForce}</span>
            </label>
            <label class="slider-row">
              <span class="slider-label">Repel force</span>
              <input
                type="range"
                class="slider"
                min="0"
                max="500"
                value={repelForce}
                oninput={(e) => onRepelForceChange(Number((e.target as HTMLInputElement).value))}
              />
              <span class="slider-value">{repelForce}</span>
            </label>
            <label class="slider-row">
              <span class="slider-label">Link distance</span>
              <input
                type="range"
                class="slider"
                min="20"
                max="200"
                value={linkDistance}
                oninput={(e) => onLinkDistanceChange(Number((e.target as HTMLInputElement).value))}
              />
              <span class="slider-value">{linkDistance}</span>
            </label>
            <label class="slider-row">
              <span class="slider-label">Link strength</span>
              <input
                type="range"
                class="slider"
                min="0"
                max="100"
                value={linkStrength}
                oninput={(e) => onLinkStrengthChange(Number((e.target as HTMLInputElement).value))}
              />
              <span class="slider-value">{linkStrength}</span>
            </label>
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .graph-controls-wrapper {
    position: absolute;
    top: 12px;
    right: 12px;
    z-index: 10;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 8px;
  }

  .toggle-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    border: none;
    background: var(--surface);
    color: var(--text-muted);
    cursor: pointer;
    transition: background 120ms ease, color 120ms ease;
  }

  .toggle-btn:hover {
    background: var(--raised);
    color: var(--text);
  }

  .graph-controls-panel {
    width: 320px;
    background: var(--surface);
    border-radius: 10px;
    padding: 8px 0;
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    font-family: 'DM Sans', sans-serif;
    max-height: calc(100vh - 120px);
    overflow-y: auto;
  }

  .section {
    border-bottom: 1px solid var(--raised);
  }

  .section:last-child {
    border-bottom: none;
  }

  .section-header {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 8px 14px;
    background: none;
    border: none;
    cursor: pointer;
    font-family: 'DM Sans', sans-serif;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.6px;
  }

  .section-header:hover {
    color: var(--text-secondary);
  }

  .section-arrow {
    font-size: 8px;
    color: inherit;
  }

  .section-body {
    padding: 4px 14px 10px;
  }

  .filter-input {
    width: 100%;
    padding: 6px 10px;
    border-radius: 6px;
    border: none;
    background: var(--bg);
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    outline: none;
  }

  .filter-input::placeholder {
    color: var(--text-faint);
  }

  .filter-input:focus {
    box-shadow: 0 0 0 1px rgba(168,160,120,0.3);
  }

  .group-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 0;
  }

  .group-swatch {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 3px;
    flex-shrink: 0;
  }

  .group-label {
    font-size: 13px;
    color: var(--text-secondary);
  }

  .toggle-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 0;
    cursor: pointer;
    font-size: 13px;
    color: var(--text-secondary);
  }

  .ctrl-checkbox {
    appearance: none;
    -webkit-appearance: none;
    width: 14px;
    height: 14px;
    border: 1.5px solid var(--border);
    border-radius: 3px;
    background: transparent;
    cursor: pointer;
    position: relative;
    flex-shrink: 0;
  }

  .ctrl-checkbox:checked {
    background: var(--gold);
    border-color: var(--gold);
  }

  .ctrl-checkbox:checked::after {
    content: "";
    position: absolute;
    left: 3px;
    top: 0px;
    width: 5px;
    height: 8px;
    border: solid var(--bg);
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
  }

  .slider-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
  }

  .slider-label {
    font-size: 12.5px;
    color: var(--text-muted);
    white-space: nowrap;
    min-width: 80px;
  }

  .slider {
    flex: 1;
    -webkit-appearance: none;
    appearance: none;
    height: 4px;
    border-radius: 2px;
    background: var(--bg);
    outline: none;
    cursor: pointer;
  }

  .slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--gold);
    cursor: pointer;
  }

  .slider-value {
    font-size: 11px;
    color: var(--text-faint);
    min-width: 28px;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  /* Scrollbar styling */
  .graph-controls-panel::-webkit-scrollbar {
    width: 4px;
  }

  .graph-controls-panel::-webkit-scrollbar-track {
    background: transparent;
  }

  .graph-controls-panel::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 2px;
  }
</style>
