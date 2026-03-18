<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { assetUrl } from "../assets";

  interface Props {
    src: string | null;
    audioOnly?: boolean;
  }

  let { src, audioOnly = false }: Props = $props();
  let containerEl: HTMLDivElement | undefined = $state();
  let playerEl: HTMLElement | null = $state(null);
  let vidstackReady = $state(false);

  let resolvedSrc = $derived(src ? assetUrl(src) : null);

  /**
   * Seek the player to a specific time (in seconds).
   */
  export function seekTo(time: number) {
    if (playerEl) {
      (playerEl as any).currentTime = time;
    }
  }

  // Dynamically import vidstack to avoid the "Class extends undefined" error
  // that occurs when vidstack's custom elements are imported at module load time.
  async function loadVidstack() {
    try {
      await import("vidstack/define/media-player.js");
      await import("vidstack/define/media-outlet.js");
      vidstackReady = true;
    } catch (e) {
      console.warn("Vidstack failed to load:", e);
      vidstackReady = false;
    }
  }

  function buildPlayer() {
    if (!containerEl || !resolvedSrc || !vidstackReady) return;

    // Clear existing
    while (containerEl.firstChild) {
      containerEl.removeChild(containerEl.firstChild);
    }

    const player = document.createElement("media-player");
    player.setAttribute("src", resolvedSrc);
    if (audioOnly) {
      player.setAttribute("view-type", "audio");
    }
    player.style.cssText = `
      width: 100%;
      border-radius: 8px;
      overflow: hidden;
      background: #1A1A18;
    `;

    const outlet = document.createElement("media-outlet");
    player.appendChild(outlet);

    // Simple native controls bar using HTML
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

    // Play/pause button
    const playBtn = document.createElement("button");
    playBtn.textContent = "\u25B6";
    playBtn.style.cssText = `
      color: #D8D5CE; cursor: pointer; background: none; border: none;
      font-size: 16px; padding: 4px 8px;
    `;
    playBtn.addEventListener("click", () => {
      if ((player as any).paused) {
        (player as any).play?.();
      } else {
        (player as any).pause?.();
      }
    });
    controls.appendChild(playBtn);

    // Time display
    const timeDisplay = document.createElement("span");
    timeDisplay.style.cssText = "font-size: 11px; color: #78756E; min-width: 80px;";
    timeDisplay.textContent = "0:00 / 0:00";
    controls.appendChild(timeDisplay);

    // Update time display periodically
    const timeInterval = setInterval(() => {
      const ct = (player as any).currentTime || 0;
      const dur = (player as any).duration || 0;
      const fmt = (s: number) => {
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return `${m}:${String(sec).padStart(2, "0")}`;
      };
      timeDisplay.textContent = `${fmt(ct)} / ${fmt(dur)}`;
    }, 500);

    player.appendChild(controls);
    containerEl.appendChild(player);
    playerEl = player;

    // Cleanup interval on destroy
    (containerEl as any).__timeInterval = timeInterval;
  }

  onMount(async () => {
    await loadVidstack();
    if (resolvedSrc && containerEl) {
      buildPlayer();
    }
  });

  $effect(() => {
    if (resolvedSrc && containerEl && vidstackReady) {
      buildPlayer();
    }
  });

  onDestroy(() => {
    if (containerEl) {
      const interval = (containerEl as any).__timeInterval;
      if (interval) clearInterval(interval);
      while (containerEl.firstChild) {
        containerEl.removeChild(containerEl.firstChild);
      }
    }
  });
</script>

{#if src}
  <div bind:this={containerEl} style="width: 100%;"></div>
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
