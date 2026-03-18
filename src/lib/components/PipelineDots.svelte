<script lang="ts">
  import type { PipelineStatus } from "../tauri";
  import { retryProcessing } from "../tauri";

  interface Props {
    status: PipelineStatus;
    recordingPath?: string | null;
  }

  let { status, recordingPath = null }: Props = $props();

  const stages = ["merge", "frames", "transcribe", "diarize", "analyze", "export"] as const;
  type Stage = (typeof stages)[number];

  let expanded = $state(false);

  let ariaLabel = $derived.by(() => {
    const parts = stages.map((s) => {
      const st = status[s];
      if (st.error) return `${s}: failed`;
      if (st.completed) return `${s}: completed`;
      return `${s}: pending`;
    });
    return `Pipeline stages: ${parts.join(", ")}`;
  });

  function dotColor(stage: Stage): string {
    const st = status[stage];
    if (st.error) return "#D06850";
    if (st.completed) return "#A8A078";
    return "#464440";
  }

  function stageIcon(stage: Stage): string {
    const st = status[stage];
    if (st.error) return "\u2717";
    if (st.completed) return "\u2713";
    return "\u2022";
  }

  function stageIconColor(stage: Stage): string {
    const st = status[stage];
    if (st.error) return "#D06850";
    if (st.completed) return "#A8A078";
    return "#585650";
  }

  function formatTimestamp(ts: string | null): string | null {
    if (!ts) return null;
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return ts;
    }
  }

  function toggleExpanded(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    expanded = !expanded;
  }

  function handleDetailClick(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
  }

  async function handleRetry(e: MouseEvent, stage: Stage) {
    e.stopPropagation();
    e.preventDefault();
    if (recordingPath) {
      await retryProcessing(recordingPath, stage);
    }
  }
</script>

<div style="display: flex; flex-direction: column; align-items: flex-end;">
  <!-- svelte-ignore a11y_role_has_required_aria_properties -->
  <button
    type="button"
    onclick={toggleExpanded}
    aria-expanded={expanded}
    aria-label={ariaLabel}
    style="
      display: inline-flex;
      align-items: center;
      gap: 3px;
      padding: 4px 6px;
      border: none;
      border-radius: 4px;
      background: transparent;
      cursor: pointer;
      transition: background 120ms ease;
    "
    onmouseenter={(e) => {
      (e.currentTarget as HTMLElement).style.background = 'rgba(168,160,120,0.08)';
    }}
    onmouseleave={(e) => {
      (e.currentTarget as HTMLElement).style.background = 'transparent';
    }}
  >
    {#each stages as stage}
      <span
        style="
          display: inline-block;
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: {dotColor(stage)};
        "
      ></span>
    {/each}
  </button>

  {#if expanded}
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      onclick={handleDetailClick}
      style="
        margin-top: 8px;
        padding: 10px 12px;
        border-radius: 6px;
        background: #1A1A18;
        font-family: 'DM Sans', sans-serif;
        font-size: 12px;
        min-width: 240px;
      "
    >
      {#each stages as stage}
        {@const st = status[stage]}
        <div
          style="
            display: flex;
            align-items: flex-start;
            gap: 8px;
            padding: 4px 0;
            {stage !== stages[stages.length - 1] ? 'border-bottom: 1px solid rgba(88,86,80,0.2);' : ''}
          "
        >
          <span
            style="
              flex-shrink: 0;
              width: 16px;
              text-align: center;
              color: {stageIconColor(stage)};
              font-size: 13px;
              line-height: 1.4;
            "
          >{stageIcon(stage)}</span>

          <div style="flex: 1; min-width: 0;">
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
              <span style="color: #D8D5CE; text-transform: capitalize;">{stage}</span>
              {#if st.completed && st.timestamp}
                <span style="color: #78756E; font-size: 11px; white-space: nowrap;">
                  {formatTimestamp(st.timestamp)}
                </span>
              {/if}
            </div>
            {#if st.error}
              <div style="color: #D06850; font-size: 11px; margin-top: 2px; word-break: break-word;">
                {st.error}
              </div>
              {#if recordingPath}
                <button
                  type="button"
                  onclick={(e) => handleRetry(e, stage)}
                  style="
                    margin-top: 4px;
                    padding: 2px 8px;
                    border: 1px solid rgba(208,104,80,0.3);
                    border-radius: 3px;
                    background: rgba(208,104,80,0.08);
                    color: #D06850;
                    font-family: 'DM Sans', sans-serif;
                    font-size: 11px;
                    cursor: pointer;
                    transition: background 120ms ease;
                  "
                  onmouseenter={(e) => {
                    (e.currentTarget as HTMLElement).style.background = 'rgba(208,104,80,0.18)';
                  }}
                  onmouseleave={(e) => {
                    (e.currentTarget as HTMLElement).style.background = 'rgba(208,104,80,0.08)';
                  }}
                >
                  Retry
                </button>
              {/if}
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
