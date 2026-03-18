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
  }

  let { expanded }: Props = $props();

  let companiesOpen = $state(true);
  let participantsOpen = $state(true);
  let platformsOpen = $state(true);

  let options: FilterOptions = $state({ companies: [], participants: [], platforms: [] });
  let filters: ActiveFilters = $state({ companies: [], participants: [], platforms: [] });

  filterOptions.subscribe((v) => (options = v));
  activeFilters.subscribe((v) => (filters = v));

  function totalActive(): number {
    return filters.companies.length + filters.participants.length + filters.platforms.length;
  }
</script>

<div
  class="filter-sidebar"
  style="
    width: {expanded ? '200px' : '0px'};
    min-width: {expanded ? '200px' : '0px'};
    overflow: hidden;
    transition: width 200ms ease, min-width 200ms ease;
    background: #1A1A18;
    border-right: {expanded ? '1px solid #262624' : 'none'};
    height: 100%;
    flex-shrink: 0;
  "
>
  {#if expanded}
    <div
      style="
        padding: 14px 14px 8px 14px;
        font-family: 'DM Sans', sans-serif;
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
            font-size: 12px;
            font-weight: 600;
            color: #D8D5CE;
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
              font-size: 11px;
              color: #A8A078;
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
              font-size: 10.5px;
              font-weight: 600;
              color: #585650;
              text-transform: uppercase;
              letter-spacing: 0.8px;
            "
          >
            <span style="font-size: 9px; color: #585650;">
              {companiesOpen ? "\u25BC" : "\u25B6"}
            </span>
            Company
            {#if filters.companies.length > 0}
              <span
                style="
                  margin-left: auto;
                  background: rgba(168,160,120,0.15);
                  color: #A8A078;
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
                    font-size: 12.5px;
                    color: #B0ADA5;
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
              font-size: 10.5px;
              font-weight: 600;
              color: #585650;
              text-transform: uppercase;
              letter-spacing: 0.8px;
            "
          >
            <span style="font-size: 9px; color: #585650;">
              {platformsOpen ? "\u25BC" : "\u25B6"}
            </span>
            Platform
            {#if filters.platforms.length > 0}
              <span
                style="
                  margin-left: auto;
                  background: rgba(168,160,120,0.15);
                  color: #A8A078;
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
                    font-size: 12.5px;
                    color: #B0ADA5;
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
              font-size: 10.5px;
              font-weight: 600;
              color: #585650;
              text-transform: uppercase;
              letter-spacing: 0.8px;
            "
          >
            <span style="font-size: 9px; color: #585650;">
              {participantsOpen ? "\u25BC" : "\u25B6"}
            </span>
            Participants
            {#if filters.participants.length > 0}
              <span
                style="
                  margin-left: auto;
                  background: rgba(168,160,120,0.15);
                  color: #A8A078;
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
                    font-size: 12.5px;
                    color: #B0ADA5;
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
            font-size: 12px;
            color: #585650;
            padding: 8px 0;
          "
        >
          No filter options available
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .filter-checkbox {
    appearance: none;
    -webkit-appearance: none;
    width: 14px;
    height: 14px;
    border: 1.5px solid #464440;
    border-radius: 3px;
    background: transparent;
    cursor: pointer;
    position: relative;
    flex-shrink: 0;
  }

  .filter-checkbox:checked {
    background: #A8A078;
    border-color: #A8A078;
  }

  .filter-checkbox:checked::after {
    content: "";
    position: absolute;
    left: 3px;
    top: 0px;
    width: 5px;
    height: 8px;
    border: solid #1A1A18;
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
  }
</style>
