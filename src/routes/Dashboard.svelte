<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import {
    meetings,
    filteredMeetings,
    loadMeetings,
    loadMore,
    search,
    clearSearch,
    loadFilterOptions,
    activeFilters,
    initMeetingsListener,
    destroyMeetingsListener,
  } from "../lib/stores/meetings";
  import { initRecorderListener, destroyRecorderListener } from "../lib/stores/recorder";
  import RecordingStatusBar from "../lib/components/RecordingStatusBar.svelte";
  import SearchBar from "../lib/components/SearchBar.svelte";
  import MeetingList from "../lib/components/MeetingList.svelte";
  import FilterSidebar from "../lib/components/FilterSidebar.svelte";

  let filtersExpanded = $state(false);

  onMount(async () => {
    await initRecorderListener();
    await initMeetingsListener();
    await loadMeetings();
    await loadFilterOptions();
  });

  onDestroy(() => {
    destroyRecorderListener();
    destroyMeetingsListener();
  });

  function handleSearch(query: string) {
    if (query.trim()) {
      search(query.trim());
    } else {
      clearSearch();
    }
  }

  function handleLoadMore() {
    loadMore();
  }

  function toggleFilters() {
    filtersExpanded = !filtersExpanded;
  }

  let filterCount = $state(0);
  activeFilters.subscribe((f) => {
    filterCount = f.companies.length + f.participants.length + f.platforms.length;
  });
</script>

<div class="flex flex-col h-full" style="background: #1D1D1B;">
  <RecordingStatusBar />

  <div class="flex flex-1 overflow-hidden">
    <FilterSidebar expanded={filtersExpanded} />

    <div class="flex-1 overflow-y-auto" style="padding: 0 28px;">
      <div
        style="
          padding-top: 18px;
          display: flex;
          align-items: center;
          gap: 10px;
        "
      >
        <!-- Filter toggle button -->
        <button
          onclick={toggleFilters}
          title={filtersExpanded ? "Hide filters" : "Show filters"}
          style="
            display: flex;
            align-items: center;
            justify-content: center;
            width: 36px;
            height: 36px;
            border-radius: 8px;
            border: none;
            background: {filtersExpanded ? 'rgba(168,160,120,0.12)' : '#282826'};
            color: {filtersExpanded ? '#A8A078' : '#585650'};
            cursor: pointer;
            flex-shrink: 0;
            position: relative;
            font-size: 16px;
          "
        >
          <!-- Filter icon (funnel) using SVG -->
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M1.5 2h13l-5 6v4.5L7.5 14V8z" />
          </svg>
          {#if filterCount > 0}
            <span
              style="
                position: absolute;
                top: -4px;
                right: -4px;
                background: #A8A078;
                color: #1A1A18;
                font-size: 9px;
                font-weight: 700;
                font-family: 'DM Sans', sans-serif;
                width: 16px;
                height: 16px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
              "
            >{filterCount}</span>
          {/if}
        </button>

        <div class="flex-1">
          <SearchBar onSearch={handleSearch} />
        </div>
      </div>

      {#if $meetings.error}
        <div
          class="mt-4 p-3 rounded-lg"
          style="
            background: rgba(200,80,60,0.10);
            color: #D06850;
            font-family: 'DM Sans', sans-serif;
            font-size: 13px;
          "
        >
          {$meetings.error}
        </div>
      {/if}

      <div style="padding-top: 14px;">
        <MeetingList
          meetings={$filteredMeetings.items}
          hasMore={$filteredMeetings.nextCursor !== null}
          isLoading={$filteredMeetings.loading}
          onLoadMore={handleLoadMore}
        />
      </div>
    </div>
  </div>
</div>
