<script module lang="ts">
  let persistedMeetingId: string | null = null;
</script>

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
  import { settings } from "../lib/stores/settings";
  import { initRecorderListener, destroyRecorderListener } from "../lib/stores/recorder";
  import {
    selectMode,
    selectedIds,
    selectedCount,
    toggleSelect,
    selectRange,
    enterSelectMode,
    exitSelectMode,
  } from "../lib/stores/selection";
  import { addToast } from "../lib/stores/toasts";
  import { deleteMeetings, reprocessMeetings } from "../lib/tauri";
  import RecordingStatusBar from "../lib/components/RecordingStatusBar.svelte";
  import SearchBar from "../lib/components/SearchBar.svelte";
  import MeetingList from "../lib/components/MeetingList.svelte";
  import FilterSidebar from "../lib/components/FilterSidebar.svelte";
  import DetailPanel from "../lib/components/DetailPanel.svelte";
  import SetupChecklist from "../lib/components/SetupChecklist.svelte";
  import BulkActionBar from "../lib/components/BulkActionBar.svelte";
  import BulkSpeakerModal from "../lib/components/BulkSpeakerModal.svelte";
  import { fly } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { reducedMotion, motionParams } from "../lib/reduced-motion";

  function drawerSlide(node: HTMLElement, { duration = 400, easing = cubicOut }: { duration?: number; easing?: (t: number) => number } = {}) {
    const width = node.offsetWidth;
    return {
      duration,
      easing,
      css: (t: number) => {
        const offset = (1 - t) * width;
        return `clip-path: inset(0 0 0 ${offset}px); transform: translateX(${offset}px);`;
      },
    };
  }

  interface Props {
    initialMeetingId?: string | null;
    initialFilterParticipant?: string | null;
  }

  let { initialMeetingId = null, initialFilterParticipant = null }: Props = $props();

  let filtersExpanded = $state(false);
  let selectedMeetingId = $state<string | null>(persistedMeetingId);
  let windowWidth = $state(window.innerWidth);
  let showSpeakerModal = $state(false);

  // Track last toggled ID for shift-click range selection
  let lastToggledId = $state<string | null>(null);

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

  function handleResize() {
    windowWidth = window.innerWidth;
  }

  onMount(async () => {
    window.addEventListener("resize", handleResize);
    await initRecorderListener();
    await initMeetingsListener();
    await loadMeetings();
    await loadFilterOptions();
  });

  onDestroy(() => {
    window.removeEventListener("resize", handleResize);
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
    persistedMeetingId = id;
  }

  function handleCloseDetail() {
    selectedMeetingId = null;
    persistedMeetingId = null;
  }

  function handleToggleSelectMode() {
    if ($selectMode) {
      exitSelectMode();
      lastToggledId = null;
    } else {
      enterSelectMode();
      selectedMeetingId = null; // Close detail panel when entering select mode
    }
  }

  function handleToggleCheck(id: string, shiftKey: boolean) {
    if (shiftKey && lastToggledId) {
      const allIds = $filteredMeetings.items.map((m) => m.id);
      selectRange(allIds, lastToggledId, id);
    } else {
      toggleSelect(id);
    }
    lastToggledId = id;
  }

  async function handleBulkDelete() {
    const count = $selectedCount;
    const confirmed = window.confirm(
      `Delete ${count} meeting${count !== 1 ? "s" : ""}? This cannot be undone.`
    );
    if (!confirmed) return;

    try {
      const deleted = await deleteMeetings(Array.from($selectedIds));
      addToast(`Deleted ${deleted.length} meeting${deleted.length !== 1 ? "s" : ""}`, "success");
      exitSelectMode();
      await loadMeetings();
    } catch (e) {
      addToast("Failed to delete meetings", "error");
    }
  }

  async function handleBulkReprocess() {
    try {
      await reprocessMeetings(Array.from($selectedIds));
      addToast(`Reprocessing ${$selectedCount} meeting${$selectedCount !== 1 ? "s" : ""}`, "success");
      exitSelectMode();
      await loadMeetings();
    } catch (e) {
      addToast("Failed to start reprocessing", "error");
    }
  }

  function handleFixSpeakers() {
    showSpeakerModal = true;
  }

  function handleCloseSpeakerModal() {
    showSpeakerModal = false;
  }

  let filterCount = $derived(
    $activeFilters.companies.length + $activeFilters.participants.length + $activeFilters.platforms.length
  );
</script>

<div class="flex flex-col h-full" style="background: var(--bg);">
  <RecordingStatusBar />

  {#if windowWidth < 900 && selectedMeetingId}
    <div class="flex flex-col h-full" style="background:var(--bg);">
      <button onclick={handleCloseDetail} style="
        padding:8px 16px;display:flex;align-items:center;gap:6px;
        background:none;border:none;color:var(--text-muted);cursor:pointer;
        font-family:'DM Sans',sans-serif;font-size:14px;
      ">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 2L4 7l5 5"/></svg>
        Back to meetings
      </button>
      <div class="flex-1 overflow-hidden">
        {#key selectedMeetingId}
          <DetailPanel meetingId={selectedMeetingId} onClose={handleCloseDetail} />
        {/key}
      </div>
    </div>
  {:else}
    <div class="flex flex-1 overflow-hidden">
      <FilterSidebar expanded={filtersExpanded} narrowMode={windowWidth < 900} />

      <!-- Meeting list panel -->
      <div
        class="meeting-list-panel"
        class:narrow-mode={windowWidth < 900}
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
              background: {filtersExpanded ? 'rgba(168,160,120,0.12)' : 'var(--surface)'};
              color: {filtersExpanded ? 'var(--gold)' : 'var(--text-faint)'};
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
                  background: var(--gold);
                  color: var(--bg);
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

          <!-- Select / Cancel button -->
          <button
            onclick={handleToggleSelectMode}
            style="
              padding: 7px 14px;
              border-radius: 8px;
              border: 1px solid {$selectMode ? 'var(--gold)' : 'var(--border)'};
              background: {$selectMode ? 'rgba(196, 168, 77, 0.1)' : 'var(--surface)'};
              color: {$selectMode ? 'var(--gold)' : 'var(--text-muted)'};
              font-family: 'DM Sans', sans-serif;
              font-size: 13px;
              font-weight: 600;
              cursor: pointer;
              flex-shrink: 0;
              transition: all 120ms ease;
            "
          >
            {$selectMode ? "Cancel" : "Select"}
          </button>
        </div>

        <SetupChecklist />

        {#if $meetings.error}
          <div
            class="mt-4 p-3 rounded-lg"
            style="
              background: rgba(200,80,60,0.10);
              color: var(--red);
              font-family: 'DM Sans', sans-serif;
              font-size: 14.5px;
            "
          >
            {$meetings.error}
          </div>
        {/if}

        {#if !$settings.recordingsFolder}
          <div
            class="mt-4 p-4 rounded-lg"
            style="
              background: rgba(180,165,130,0.08);
              font-family: 'DM Sans', sans-serif;
              font-size: 14.5px;
              color: var(--gold-muted);
              text-align: center;
            "
          >
            <p style="margin: 0 0 8px 0;">No recordings folder configured</p>
            <a
              href="#settings"
              style="
                color: var(--gold);
                text-decoration: underline;
                font-weight: 600;
              "
            >
              Configure in Settings
            </a>
          </div>
        {/if}

        <div style="padding-top: 14px;">
          <MeetingList
            meetings={$filteredMeetings.items}
            hasMore={$filteredMeetings.nextCursor !== null}
            isLoading={$filteredMeetings.loading}
            onLoadMore={handleLoadMore}
            selectedId={selectedMeetingId}
            onSelect={$selectMode ? undefined : handleSelectMeeting}
            selectMode={$selectMode}
            onToggleCheck={handleToggleCheck}
          />
        </div>

        {#if $selectMode}
          <BulkActionBar
            onDelete={handleBulkDelete}
            onReprocess={handleBulkReprocess}
            onFixSpeakers={handleFixSpeakers}
          />
        {/if}
      </div>

      <!-- Landing / Detail panel -->
      <div class="detail-area">
        <div class="landing-screen">
          <div class="landing-hero">
            <svg viewBox="0 0 100 100" width="72" height="72" class="landing-logo">
              <circle cx="44" cy="38" r="32" fill="none" stroke="var(--gold)" stroke-width="5"/>
              <circle cx="44" cy="38" r="12" fill="var(--gold)"/>
              <circle cx="22" cy="84" r="5" fill="var(--text-faint)"/>
              <circle cx="44" cy="84" r="5" fill="var(--gold)"/>
              <circle cx="66" cy="84" r="5" fill="var(--text-faint)"/>
            </svg>
            <h2 class="landing-heading">Recap</h2>
            <p class="landing-tagline">Your meetings, distilled.</p>
          </div>
          <div class="landing-hint">
            <span>Choose a meeting from the list to view its details, notes, and transcript.</span>
          </div>
        </div>

        {#if !$selectMode && selectedMeetingId}
          <div
            class="detail-panel-wrapper"
            in:drawerSlide={$reducedMotion ? { duration: 0 } : { duration: 400 }}
            out:drawerSlide={$reducedMotion ? { duration: 0 } : { duration: 500 }}
          >
            {#key selectedMeetingId}
              <div
                class="detail-content"
                in:fly={motionParams({ x: -40, duration: 350, delay: 50 }, $reducedMotion)}
                out:fly={motionParams({ x: 40, duration: 200 }, $reducedMotion)}
              >
                <DetailPanel
                  meetingId={selectedMeetingId}
                  onClose={handleCloseDetail}
                />
              </div>
            {/key}
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>

{#if showSpeakerModal}
  <BulkSpeakerModal
    selectedIds={$selectedIds}
    onclose={handleCloseSpeakerModal}
  />
{/if}

<style>
  .meeting-list-panel {
    flex: 0 0 320px;
    overflow-y: auto;
    padding: 0 16px;
    position: relative;
  }

  .meeting-list-panel.narrow-mode {
    flex: 1;
    min-width: 0;
  }

  .detail-area {
    flex: 1;
    position: relative;
    overflow: hidden;
  }

  .landing-screen {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    font-family: 'DM Sans', sans-serif;
  }

  .landing-hero {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    margin-bottom: 48px;
  }

  .landing-logo {
    margin-bottom: 8px;
  }

  .landing-heading {
    font-family: 'Source Serif 4', serif;
    font-size: 32px;
    font-weight: 700;
    color: var(--text);
    margin: 0;
  }

  .landing-tagline {
    font-size: 15px;
    color: var(--text-muted);
    margin: 0;
    letter-spacing: 0.02em;
  }

  .landing-hint {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--text-faint);
    max-width: 260px;
    text-align: center;
    line-height: 1.5;
  }

  .detail-panel-wrapper {
    position: absolute;
    inset: 0;
    overflow: hidden;
    background: var(--bg);
  }

  .detail-content {
    height: 100%;
    min-width: 0;
  }
</style>
