<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { meetings, loadMeetings, loadMore, search, clearSearch, initMeetingsListener, destroyMeetingsListener } from "../lib/stores/meetings";
  import { initRecorderListener, destroyRecorderListener } from "../lib/stores/recorder";
  import RecordingStatusBar from "../lib/components/RecordingStatusBar.svelte";
  import SearchBar from "../lib/components/SearchBar.svelte";
  import MeetingList from "../lib/components/MeetingList.svelte";

  onMount(async () => {
    await initRecorderListener();
    await initMeetingsListener();
    await loadMeetings();
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
</script>

<div class="flex flex-col min-h-screen" style="background: #1D1D1B;">
  <RecordingStatusBar />

  <div class="flex-1" style="padding: 0 28px;">
    <div style="padding-top: 18px;">
      <SearchBar onSearch={handleSearch} />
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
        meetings={$meetings.items}
        hasMore={$meetings.nextCursor !== null}
        isLoading={$meetings.loading}
        onLoadMore={handleLoadMore}
      />
    </div>
  </div>
</div>
