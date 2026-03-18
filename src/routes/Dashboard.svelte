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
    toggleFilter,
    clearAllFilters,
    initMeetingsListener,
    destroyMeetingsListener,
  } from "../lib/stores/meetings";
  import { initRecorderListener, destroyRecorderListener } from "../lib/stores/recorder";
  import RecordingStatusBar from "../lib/components/RecordingStatusBar.svelte";
  import SearchBar from "../lib/components/SearchBar.svelte";
  import MeetingList from "../lib/components/MeetingList.svelte";
  import FilterSidebar from "../lib/components/FilterSidebar.svelte";
  import DetailPanel from "../lib/components/DetailPanel.svelte";

  interface Props {
    initialMeetingId?: string | null;
    initialFilterParticipant?: string | null;
  }

  let { initialMeetingId = null, initialFilterParticipant = null }: Props = $props();

  let filtersExpanded = $state(false);
  let selectedMeetingId = $state<string | null>(null);

  // Set initial meeting ID from deep link
  $effect(() => {
    if (initialMeetingId) {
      selectedMeetingId = initialMeetingId;
    }
  });

  // Apply participant filter from wikilink navigation
  $effect(() => {
    if (initialFilterParticipant) {
      // Clear existing filters and set the participant filter
      clearAllFilters();
      toggleFilter("participants", initialFilterParticipant);
      filtersExpanded = true;
    }
  });

  onMount(async () => {
    await initRecorderListener();
    await initMeetingsListener();
    await loadMeetings();
    await loadFilterOptions();
  });

  onDestroy(() => {
    destroyRecorderListener();
    destroyMeetingsListener();
    if (searchTimer) clearTimeout(searchTimer);
  });

  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  function handleSearch(query: string) {
    if (searchTimer) clearTimeout(searchTimer);
    if (!query.trim()) {
      clearSearch();
      return;
    }
    searchTimer = setTimeout(() => {
      search(query.trim());
    }, 300);
  }

  function handleLoadMore() {
    loadMore();
  }

  function toggleFilters() {
    filtersExpanded = !filtersExpanded;
  }

  function handleSelectMeeting(id: string) {
    selectedMeetingId = id;
  }

  function handleCloseDetail() {
    selectedMeetingId = null;
  }

  let filterCount = $derived(
    $activeFilters.companies.length + $activeFilters.participants.length + $activeFilters.platforms.length
  );
</script>

<div class="flex flex-col h-full" style="background: #1D1D1B;">
  <RecordingStatusBar />

  <div class="flex flex-1 overflow-hidden">
    <FilterSidebar expanded={filtersExpanded} />

    <!-- Meeting list panel -->
    <div
      class="meeting-list-panel"
      class:has-detail={selectedMeetingId !== null}
    >
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
            font-size: 18px;
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
            font-size: 14.5px;
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
          selectedId={selectedMeetingId}
          onSelect={handleSelectMeeting}
        />
      </div>
    </div>

    <!-- Detail panel -->
    {#if selectedMeetingId}
      <div class="detail-panel-wrapper">
        {#key selectedMeetingId}
          <DetailPanel
            meetingId={selectedMeetingId}
            onClose={handleCloseDetail}
          />
        {/key}
      </div>
    {/if}
  </div>
</div>

<style>
  .meeting-list-panel {
    flex: 1;
    overflow-y: auto;
    padding: 0 28px;
    transition: flex 200ms ease;
  }

  .meeting-list-panel.has-detail {
    flex: 0 0 320px;
    min-width: 320px;
    max-width: 320px;
    padding: 0 16px;
  }

  .detail-panel-wrapper {
    flex: 1;
    overflow: hidden;
    animation: slide-in 200ms ease;
  }

  @keyframes slide-in {
    from {
      transform: translateX(40px);
      opacity: 0;
    }
    to {
      transform: translateX(0);
      opacity: 1;
    }
  }
</style>
