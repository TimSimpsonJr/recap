<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { assetUrl } from "../assets";

  // Register vidstack custom elements
  import "vidstack/define/media-player.js";
  import "vidstack/define/media-outlet.js";
  import "vidstack/define/media-play-button.js";
  import "vidstack/define/media-mute-button.js";
  import "vidstack/define/media-time-slider.js";
  import "vidstack/define/media-volume-slider.js";
  import "vidstack/define/media-time.js";

  // Base styles
  import "vidstack/styles/defaults.css";
  import "vidstack/styles/base.css";

  interface Props {
    src: string | null;
    audioOnly?: boolean;
    onSeekRequest?: (time: number) => void;
  }

  let { src, audioOnly = false, onSeekRequest }: Props = $props();
  let containerEl: HTMLDivElement | undefined = $state();
  let playerEl: HTMLElement | null = $state(null);

  let resolvedSrc = $derived(src ? assetUrl(src) : null);

  /**
   * Seek the player to a specific time (in seconds).
   */
  export function seekTo(time: number) {
    if (playerEl) {
      (playerEl as any).currentTime = time;
    }
  }

  function clearContainer() {
    if (!containerEl) return;
    while (containerEl.firstChild) {
      containerEl.removeChild(containerEl.firstChild);
    }
  }

  function buildPlayer() {
    if (!containerEl || !resolvedSrc) return;

    clearContainer();

    const player = document.createElement("media-player");
    player.setAttribute("src", resolvedSrc);
    if (audioOnly) {
      player.setAttribute("view-type", "audio");
    }
    player.style.cssText = `
      --media-brand: #A8A078;
      --media-focus-ring-color: rgba(168,160,120,0.4);
      --media-slider-track-fill-bg: #A8A078;
      --media-slider-thumb-bg: #D8D5CE;
      width: 100%;
      border-radius: 8px;
      overflow: hidden;
      background: #1A1A18;
    `;

    const outlet = document.createElement("media-outlet");
    player.appendChild(outlet);

    // Controls bar
    const controls = document.createElement("div");
    controls.style.cssText = `
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      background: #1A1A18;
      font-family: 'DM Sans', sans-serif;
      font-size: 12px;
      color: #B0ADA5;
    `;

    const playBtn = document.createElement("media-play-button");
    playBtn.style.cssText = "color: #D8D5CE; cursor: pointer; width: 28px; height: 28px;";
    controls.appendChild(playBtn);

    const timeSlider = document.createElement("media-time-slider");
    timeSlider.style.cssText = "flex: 1;";
    controls.appendChild(timeSlider);

    const currentTime = document.createElement("media-time");
    currentTime.setAttribute("type", "current");
    currentTime.style.cssText = "color: #B0ADA5; font-size: 11px; min-width: 40px; text-align: right;";
    controls.appendChild(currentTime);

    const sep = document.createElement("span");
    sep.textContent = "/";
    sep.style.cssText = "color: #585650; font-size: 11px;";
    controls.appendChild(sep);

    const duration = document.createElement("media-time");
    duration.setAttribute("type", "duration");
    duration.style.cssText = "color: #78756E; font-size: 11px; min-width: 40px;";
    controls.appendChild(duration);

    const muteBtn = document.createElement("media-mute-button");
    muteBtn.style.cssText = "color: #D8D5CE; cursor: pointer; width: 28px; height: 28px;";
    controls.appendChild(muteBtn);

    const volSlider = document.createElement("media-volume-slider");
    volSlider.style.cssText = "width: 80px;";
    controls.appendChild(volSlider);

    player.appendChild(controls);
    containerEl.appendChild(player);
    playerEl = player;
  }

  onMount(() => {
    if (resolvedSrc && containerEl) {
      buildPlayer();
    }
  });

  // Rebuild player when src changes
  $effect(() => {
    if (resolvedSrc && containerEl) {
      buildPlayer();
    }
  });

  onDestroy(() => {
    clearContainer();
  });
</script>

{#if src}
  <div bind:this={containerEl} class="meeting-player" style="width: 100%;"></div>
{:else}
  <div
    class="flex items-center justify-center"
    style="
      height: 200px;
      background: #242422;
      border-radius: 8px;
      font-family: 'DM Sans', sans-serif;
      font-size: 13px;
      color: #585650;
    "
  >
    No recording available
  </div>
{/if}
