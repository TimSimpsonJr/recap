<script lang="ts">
  import {
    activeFilters,
    filterOptions,
    toggleFilter,
    clearAllFilters,
    type ActiveFilters,
  } from "../stores/meetings";
  import type { FilterOptions } from "../tauri";

  interface Props {
    expanded: boolean;
    narrowMode?: boolean;
  }

  let { expanded, narrowMode = false }: Props = $props();

  // In narrow mode, force collapsed state regardless of expanded prop
  let effectiveExpanded = $derived(narrowMode ? false : expanded);

  let companiesOpen = $state(true);
  let participantsOpen = $state(true);
  let platformsOpen = $state(true);

  let options = $derived($filterOptions);
  let filters = $derived($activeFilters);

  function totalActive(): number {
    return filters.companies.length + filters.participants.length + filters.platforms.length;
  }
</script>

<div
  class="filter-sidebar"
  style="
    width: {effectiveExpanded ? '200px' : '0px'};
    min-width: {effectiveExpanded ? '200px' : '0px'};
    overflow: hidden;
    transition: width 300ms cubic-bezier(0.4, 0, 0.2, 1), min-width 300ms cubic-bezier(0.4, 0, 0.2, 1), padding 300ms cubic-bezier(0.4, 0, 0.2, 1);
    background: var(--bg);
    border-right: {effectiveExpanded ? '1px solid var(--border)' : 'none'};
    height: 100%;
    flex-shrink: 0;
  "
>
    <div
      style="
        padding: 14px 14px 8px 14px;
        font-family: 'DM Sans', sans-serif;
        opacity: {effectiveExpanded ? '1' : '0'};
        transition: opacity 200ms ease {effectiveExpanded ? '100ms' : '0ms'};
      "
    >
      <!-- Header -->
      <div
        style="
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
        "
      >
        <span
          style="
            font-size: 13.5px;
            font-weight: 600;
            color: var(--text);
            letter-spacing: 0.5px;
          "
        >Filters</span>
        {#if totalActive() > 0}
          <button
            onclick={() => clearAllFilters()}
            style="
              background: none;
              border: none;
              padding: 0;
              cursor: pointer;
              font-family: 'DM Sans', sans-serif;
              font-size: 14px;
              color: var(--gold);
            "
          >Clear all</button>
        {/if}
      </div>

      <!-- Company Section -->
      {#if options.companies.length > 0}
        <div style="margin-bottom: 10px;">
          <button
            onclick={() => (companiesOpen = !companiesOpen)}
            style="
              display: flex;
              align-items: center;
              gap: 4px;
              width: 100%;
              background: none;
              border: none;
              padding: 4px 0;
              cursor: pointer;
              font-family: 'DM Sans', sans-serif;
              font-size: 12px;
              font-weight: 600;
              color: var(--text-faint);
              text-transform: uppercase;
              letter-spacing: 0.8px;
            "
          >
            <span style="font-size: 9px; color: var(--text-faint);">
              {companiesOpen ? "\u25BC" : "\u25B6"}
            </span>
            Company
            {#if filters.companies.length > 0}
              <span
                style="
                  margin-left: auto;
                  background: rgba(168,160,120,0.15);
                  color: var(--gold);
                  font-size: 10px;
                  font-weight: 600;
                  padding: 1px 6px;
                  border-radius: 4px;
                "
              >{filters.companies.length}</span>
            {/if}
          </button>
          {#if companiesOpen}
            <div style="padding-left: 2px;">
              {#each options.companies as company}
                <label
                  style="
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 3px 0;
                    cursor: pointer;
                    font-size: 14px;
                    color: var(--text-secondary);
                  "
                >
                  <input
                    type="checkbox"
                    checked={filters.companies.includes(company)}
                    onchange={() => toggleFilter("companies", company)}
                    class="filter-checkbox"
                  />
                  {company}
                </label>
              {/each}
            </div>
          {/if}
        </div>
      {/if}

      <!-- Platform Section -->
      {#if options.platforms.length > 0}
        <div style="margin-bottom: 10px;">
          <button
            onclick={() => (platformsOpen = !platformsOpen)}
            style="
              display: flex;
              align-items: center;
              gap: 4px;
              width: 100%;
              background: none;
              border: none;
              padding: 4px 0;
              cursor: pointer;
              font-family: 'DM Sans', sans-serif;
              font-size: 12px;
              font-weight: 600;
              color: var(--text-faint);
              text-transform: uppercase;
              letter-spacing: 0.8px;
            "
          >
            <span style="font-size: 9px; color: var(--text-faint);">
              {platformsOpen ? "\u25BC" : "\u25B6"}
            </span>
            Platform
            {#if filters.platforms.length > 0}
              <span
                style="
                  margin-left: auto;
                  background: rgba(168,160,120,0.15);
                  color: var(--gold);
                  font-size: 10px;
                  font-weight: 600;
                  padding: 1px 6px;
                  border-radius: 4px;
                "
              >{filters.platforms.length}</span>
            {/if}
          </button>
          {#if platformsOpen}
            <div style="padding-left: 2px;">
              {#each options.platforms as platform}
                <label
                  style="
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 3px 0;
                    cursor: pointer;
                    font-size: 14px;
                    color: var(--text-secondary);
                  "
                >
                  <input
                    type="checkbox"
                    checked={filters.platforms.includes(platform)}
                    onchange={() => toggleFilter("platforms", platform)}
                    class="filter-checkbox"
                  />
                  {platform}
                </label>
              {/each}
            </div>
          {/if}
        </div>
      {/if}

      <!-- Participants Section -->
      {#if options.participants.length > 0}
        <div style="margin-bottom: 10px;">
          <button
            onclick={() => (participantsOpen = !participantsOpen)}
            style="
              display: flex;
              align-items: center;
              gap: 4px;
              width: 100%;
              background: none;
              border: none;
              padding: 4px 0;
              cursor: pointer;
              font-family: 'DM Sans', sans-serif;
              font-size: 12px;
              font-weight: 600;
              color: var(--text-faint);
              text-transform: uppercase;
              letter-spacing: 0.8px;
            "
          >
            <span style="font-size: 9px; color: var(--text-faint);">
              {participantsOpen ? "\u25BC" : "\u25B6"}
            </span>
            Participants
            {#if filters.participants.length > 0}
              <span
                style="
                  margin-left: auto;
                  background: rgba(168,160,120,0.15);
                  color: var(--gold);
                  font-size: 10px;
                  font-weight: 600;
                  padding: 1px 6px;
                  border-radius: 4px;
                "
              >{filters.participants.length}</span>
            {/if}
          </button>
          {#if participantsOpen}
            <div style="padding-left: 2px;">
              {#each options.participants as participant}
                <label
                  style="
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 3px 0;
                    cursor: pointer;
                    font-size: 14px;
                    color: var(--text-secondary);
                  "
                >
                  <input
                    type="checkbox"
                    checked={filters.participants.includes(participant)}
                    onchange={() => toggleFilter("participants", participant)}
                    class="filter-checkbox"
                  />
                  {participant}
                </label>
              {/each}
            </div>
          {/if}
        </div>
      {/if}

      <!-- Empty state -->
      {#if options.companies.length === 0 && options.platforms.length === 0 && options.participants.length === 0}
        <div
          style="
            font-size: 13.5px;
            color: var(--text-faint);
            padding: 8px 0;
          "
        >
          No filter options available
        </div>
      {/if}
    </div>
</div>

<style>
  .filter-checkbox {
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

  .filter-checkbox:checked {
    background: var(--gold);
    border-color: var(--gold);
  }

  .filter-checkbox:checked::after {
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
</style>
