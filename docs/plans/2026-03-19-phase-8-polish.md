# Phase 8: Polish — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Polish the Recap desktop app with responsive layout, bulk meeting operations, Todoist bidirectional sync, and comprehensive animation/UI improvements.

**Architecture:** Four parallel workstreams that can be implemented independently: (1) CSS breakpoints and responsive containers, (2) new Rust IPC commands + Svelte bulk selection UI, (3) Python Todoist sync extensions + settings UI, (4) Svelte transitions/animations + Tauri window config changes. A calendar sync bug fix is also included.

**Tech Stack:** Svelte 5 (runes), Tailwind CSS 4, Tauri v2 (Rust), Python 3.10+, D3.js, todoist-api-python

---

## Task 1: Logo SVG and Title Bar Integration

**Files:**
- Create: `src/lib/assets/logo.svg`
- Modify: `src/App.svelte:156-219` (nav bar)
- Modify: `src-tauri/tauri.conf.json:13-21` (window config)
- Modify: `src-tauri/src/lib.rs:187-195` (window event handling)

**Step 1: Create the logo SVG**

Create `src/lib/assets/logo.svg` — the Recap logo (concentric circles + three dots) using theme gold `#C4A84D`. Trace from the existing `src-tauri/icons/icon.png`. The SVG should be simple geometric shapes: outer circle (stroke, no fill), inner filled circle, three small filled circles below. Viewbox sized for ~24px display.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="24" height="24">
  <circle cx="44" cy="38" r="32" fill="none" stroke="#C4A84D" stroke-width="7"/>
  <circle cx="44" cy="38" r="12" fill="#C4A84D"/>
  <circle cx="22" cy="84" r="6" fill="#8a7e6a"/>
  <circle cx="44" cy="84" r="6" fill="#C4A84D"/>
  <circle cx="66" cy="84" r="6" fill="#8a7e6a"/>
</svg>
```

Compare against `src-tauri/icons/icon.png` and adjust proportions until it matches. The outer two dots are a muted tone, the center dot matches the gold.

**Step 2: Disable Tauri default window decorations**

In `src-tauri/tauri.conf.json`, set `decorations: false` on the main window:

```json
"windows": [
  {
    "title": "Recap",
    "width": 1400,
    "height": 900,
    "visible": false,
    "decorations": false,
    "backgroundColor": "#1D1D1B"
  }
]
```

**Step 3: Add custom title bar to nav bar in App.svelte**

In `src/App.svelte`, replace the current nav bar (lines 156-219) with a version that includes:
- `data-tauri-drag-region` on the nav container for window dragging
- Logo SVG imported and rendered next to "Recap" text (left side)
- Custom window control buttons (minimize, maximize, close) on the right side
- Use `@tauri-apps/api/window` for `getCurrentWindow().minimize()`, `.toggleMaximize()`, `.close()`

The nav links (Meetings, Calendar, Graph, Settings) stay in the center. Window controls go far-right.

Import the window API:
```typescript
import { getCurrentWindow } from "@tauri-apps/api/window";
const appWindow = getCurrentWindow();
```

Window control buttons (right side of nav):
```html
<div class="flex items-center gap-1" style="margin-left: auto; -webkit-app-region: no-drag;">
  <button onclick={() => appWindow.minimize()} title="Minimize"
    style="width:32px;height:32px;background:none;border:none;color:var(--text-muted);cursor:pointer;display:flex;align-items:center;justify-content:center;border-radius:4px;">
    <svg width="12" height="12" viewBox="0 0 12 12"><path d="M1 6h10" stroke="currentColor" stroke-width="1.5"/></svg>
  </button>
  <button onclick={() => appWindow.toggleMaximize()} title="Maximize"
    style="width:32px;height:32px;background:none;border:none;color:var(--text-muted);cursor:pointer;display:flex;align-items:center;justify-content:center;border-radius:4px;">
    <svg width="12" height="12" viewBox="0 0 12 12"><rect x="1" y="1" width="10" height="10" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
  </button>
  <button onclick={() => appWindow.close()} title="Close"
    style="width:32px;height:32px;background:none;border:none;color:var(--text-muted);cursor:pointer;display:flex;align-items:center;justify-content:center;border-radius:4px;"
    onmouseenter={(e) => { e.currentTarget.style.background = 'var(--red)'; e.currentTarget.style.color = 'white'; }}
    onmouseleave={(e) => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = 'var(--text-muted)'; }}>
    <svg width="12" height="12" viewBox="0 0 12 12"><path d="M1 1l10 10M11 1L1 11" stroke="currentColor" stroke-width="1.5"/></svg>
  </button>
</div>
```

Add `data-tauri-drag-region` to the nav bar outer div. Ensure all interactive elements inside have `-webkit-app-region: no-drag`.

**Step 4: Update window close behavior in lib.rs**

In `src-tauri/src/lib.rs` lines 187-195, the existing hide-on-close behavior should continue to work with `decorations: false`. The custom close button calls `window.close()` which triggers the same `CloseRequested` event. Verify this still works — if not, the close button should call `window.hide()` instead and only the tray "Quit" should truly close.

**Step 5: Test and commit**

Run `npm run dev` (or build) and verify:
- Logo + "Recap" text renders in nav bar
- Window is draggable by the nav bar area
- Minimize, maximize, close buttons work
- Nav links are still clickable (not blocked by drag region)
- Hide-on-close still works (window hides, doesn't quit)

```bash
git add src/lib/assets/logo.svg src/App.svelte src-tauri/tauri.conf.json
git commit -m "feat: custom title bar with logo and window controls"
```

---

## Task 2: Setup Checklist Polish

**Files:**
- Modify: `src/lib/stores/settings.ts:4-33` (add setting)
- Modify: `src/lib/components/SetupChecklist.svelte` (dismiss + animate)

**Step 1: Add setupChecklistDismissed to settings**

In `src/lib/stores/settings.ts`, add to the `AppSettings` interface (around line 32):
```typescript
setupChecklistDismissed: boolean;
```

Add to defaults (around line 63):
```typescript
setupChecklistDismissed: false,
```

**Step 2: Wire dismiss behavior in SetupChecklist.svelte**

In `src/lib/components/SetupChecklist.svelte`:
- Import `settings` and `saveSettings` from settings store
- The close button (X) should set `setupChecklistDismissed = true` and save
- At the top of the component, check `if ($settings.setupChecklistDismissed) return` (render nothing)

**Step 3: Animate completed items out**

Use Svelte 5 transitions. When an item's status changes to completed:
- Wrap each checklist item in a keyed block with `transition:fly={{ x: -20, duration: 300 }}`
- Only render items where `!item.completed` — completed items fly out to the left and disappear from the list
- The checklist counter updates (e.g., "3/6" becomes "2/6" then the item vanishes)

Import from svelte/transition:
```typescript
import { fly } from "svelte/transition";
```

Each item:
```html
{#each visibleItems as item (item.key)}
  <div transition:fly={{ x: -20, duration: 300 }}>
    <!-- existing item markup -->
  </div>
{/each}
```

Where `visibleItems` is a `$derived` that filters out completed items.

**Step 4: Test and commit**

Verify:
- Closing the checklist makes it disappear permanently (survives app restart)
- Completing a provider connection animates the item out
- The counter updates correctly

```bash
git add src/lib/stores/settings.ts src/lib/components/SetupChecklist.svelte
git commit -m "feat: setup checklist dismiss + completion animations"
```

---

## Task 3: Toast Notification System

**Files:**
- Create: `src/lib/stores/toasts.ts`
- Create: `src/lib/components/ToastContainer.svelte`
- Modify: `src/App.svelte` (mount ToastContainer)

**Step 1: Create toast store**

```typescript
// src/lib/stores/toasts.ts
import { writable } from "svelte/store";

export interface Toast {
  id: string;
  message: string;
  type: "success" | "error" | "info";
  duration?: number;
}

const { subscribe, update } = writable<Toast[]>([]);

export const toasts = { subscribe };

export function addToast(message: string, type: Toast["type"] = "info", duration = 4000) {
  const id = crypto.randomUUID();
  update((t) => [...t, { id, message, type, duration }]);
  if (duration > 0) {
    setTimeout(() => removeToast(id), duration);
  }
  return id;
}

export function removeToast(id: string) {
  update((t) => t.filter((toast) => toast.id !== id));
}
```

**Step 2: Create ToastContainer component**

```svelte
<!-- src/lib/components/ToastContainer.svelte -->
<script lang="ts">
  import { toasts, removeToast } from "../stores/toasts";
  import { fly, fade } from "svelte/transition";
</script>

<div style="position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none;">
  {#each $toasts as toast (toast.id)}
    <div
      transition:fly={{ x: 100, duration: 300 }}
      style="
        pointer-events:auto;
        padding:12px 16px;
        border-radius:8px;
        font-family:'DM Sans',sans-serif;
        font-size:13.5px;
        color:var(--text);
        background:var(--raised);
        border:1px solid {toast.type === 'error' ? 'var(--red)' : toast.type === 'success' ? 'var(--green)' : 'var(--border)'};
        box-shadow:0 4px 16px rgba(0,0,0,0.3);
        display:flex;
        align-items:center;
        gap:8px;
        max-width:360px;
      "
    >
      <span style="flex:1;">{toast.message}</span>
      <button
        onclick={() => removeToast(toast.id)}
        style="background:none;border:none;color:var(--text-muted);cursor:pointer;padding:2px;"
      >&times;</button>
    </div>
  {/each}
</div>
```

**Step 3: Mount in App.svelte**

Add `<ToastContainer />` at the bottom of App.svelte's template, after the route content:

```svelte
import ToastContainer from "./lib/components/ToastContainer.svelte";
<!-- ... existing template ... -->
<ToastContainer />
```

**Step 4: Commit**

```bash
git add src/lib/stores/toasts.ts src/lib/components/ToastContainer.svelte src/App.svelte
git commit -m "feat: toast notification system"
```

---

## Task 4: Button Micro-interactions and Modal Transitions

**Files:**
- Modify: `src/app.css` (global button transitions)
- Modify: `src/lib/components/Modal.svelte` (if exists, add transitions)

**Step 1: Add global button transition styles**

In `src/app.css`, add after the scrollbar styles:

```css
/* ── Button micro-interactions ── */
button {
  transition: background 150ms ease, transform 80ms ease, box-shadow 150ms ease;
}

button:active:not(:disabled) {
  transform: scale(0.97);
}
```

This gives every button a subtle press-down effect. Individual components can override as needed.

**Step 2: Add modal transitions**

If `src/lib/components/Modal.svelte` exists, add `transition:fade` on the backdrop and `transition:scale` on the modal content:

```svelte
import { fade, scale } from "svelte/transition";

<!-- Backdrop -->
<div transition:fade={{ duration: 150 }} ...>
  <!-- Modal content -->
  <div transition:scale={{ start: 0.95, duration: 200 }} ...>
```

If Modal.svelte doesn't use Svelte transitions yet, wrap the outer container with these transitions.

**Step 3: Commit**

```bash
git add src/app.css src/lib/components/Modal.svelte
git commit -m "feat: button micro-interactions and modal transitions"
```

---

## Task 5: Filter Sidebar Smooth Animation

**Files:**
- Modify: `src/lib/components/FilterSidebar.svelte:31-38`

**Step 1: Improve expand/collapse animation**

In `FilterSidebar.svelte`, the current expand/collapse is done via width transition (lines 31-38). Improve it:
- Increase transition duration from current value to 300ms
- Use `cubic-bezier(0.4, 0, 0.2, 1)` easing
- Add `overflow: hidden` during transition to prevent content flash
- Content inside should fade in with a slight delay (150ms) after width expands

The sidebar container style should include:
```css
transition: width 300ms cubic-bezier(0.4, 0, 0.2, 1), padding 300ms cubic-bezier(0.4, 0, 0.2, 1);
```

Content inside:
```css
transition: opacity 200ms ease 100ms;
opacity: {expanded ? 1 : 0};
```

**Step 2: Commit**

```bash
git add src/lib/components/FilterSidebar.svelte
git commit -m "feat: smooth filter sidebar expand/collapse animation"
```

---

## Task 6: Route Transitions

**Files:**
- Modify: `src/App.svelte:222-232` (route rendering)

**Step 1: Add crossfade between routes**

In `src/App.svelte`, wrap the route content area with a keyed block and a fade transition:

```svelte
import { fade } from "svelte/transition";

{#key currentRoute}
  <div transition:fade={{ duration: 150 }} class="flex-1 overflow-hidden">
    {#if currentRoute === "settings"}
      <Settings />
    {:else if currentRoute === "calendar"}
      <Calendar />
    {:else if currentRoute === "graph"}
      <GraphView />
    {:else}
      <Dashboard ... />
    {/if}
  </div>
{/key}
```

Note: Using `{#key}` will remount components on route change. This is acceptable since each route already loads its own data on mount. If calendar/graph state needs preservation, consider using CSS visibility toggling instead for those specific routes.

**Step 2: Commit**

```bash
git add src/App.svelte
git commit -m "feat: route crossfade transitions"
```

---

## Task 7: Detail Panel and Meeting List Animations

**Files:**
- Modify: `src/routes/Dashboard.svelte:246-276` (split panel animation)
- Modify: `src/lib/components/MeetingList.svelte:71-94` (row animations)
- Modify: `src/lib/components/MeetingRow.svelte` (hover improvements)

**Step 1: Slow down detail panel slide-in**

In `src/routes/Dashboard.svelte`, update the CSS (lines 261-276):

```css
.meeting-list-panel {
  flex: 1;
  overflow-y: auto;
  padding: 0 28px;
  transition: flex 400ms cubic-bezier(0.4, 0, 0.2, 1);
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
  animation: slide-in 400ms cubic-bezier(0.4, 0, 0.2, 1);
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
```

**Step 2: Add fly transitions to MeetingRow entries**

In `src/lib/components/MeetingList.svelte`, add transitions to meeting rows:

```svelte
import { fly } from "svelte/transition";

{#each group.meetings as meeting, i (meeting.id)}
  <div transition:fly={{ y: 10, duration: 200, delay: i * 30 }}>
    <MeetingRow ... />
  </div>
{/each}
```

The staggered delay (30ms per item) creates a cascade effect when the list loads or filters change.

**Step 3: Commit**

```bash
git add src/routes/Dashboard.svelte src/lib/components/MeetingList.svelte
git commit -m "feat: smoother detail panel animation + meeting list transitions"
```

---

## Task 8: Skeleton Loaders

**Files:**
- Create: `src/lib/components/SkeletonLoader.svelte`
- Modify: `src/lib/components/MeetingList.svelte` (loading state)
- Modify: `src/lib/components/DetailPanel.svelte` (loading state)
- Modify: `src/routes/MeetingDetail.svelte` (loading state)

**Step 1: Create reusable skeleton component**

```svelte
<!-- src/lib/components/SkeletonLoader.svelte -->
<script lang="ts">
  interface Props {
    lines?: number;
    showPlayer?: boolean;
  }
  let { lines = 4, showPlayer = false }: Props = $props();
</script>

<div style="padding: 16px; display: flex; flex-direction: column; gap: 12px;">
  {#if showPlayer}
    <div class="skeleton" style="width:100%;height:200px;border-radius:8px;"></div>
  {/if}
  <div class="skeleton" style="width:60%;height:20px;border-radius:4px;"></div>
  {#each Array(lines) as _, i}
    <div class="skeleton" style="width:{85 - i * 10}%;height:14px;border-radius:4px;"></div>
  {/each}
</div>

<style>
  .skeleton {
    background: linear-gradient(90deg, var(--surface) 25%, var(--raised) 50%, var(--surface) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s ease-in-out infinite;
  }

  @keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
</style>
```

**Step 2: Use in MeetingList loading state**

In `src/lib/components/MeetingList.svelte`, replace the current spinner (lines 127-148) with skeleton rows when `isLoading` and the list is empty:

```svelte
{#if isLoading && meetings.length === 0}
  {#each Array(5) as _}
    <div style="padding:14px 16px;border-radius:8px;background:var(--surface);margin-bottom:8px;">
      <div class="skeleton" style="width:70%;height:16px;border-radius:4px;margin-bottom:8px;"></div>
      <div class="skeleton" style="width:40%;height:12px;border-radius:4px;"></div>
    </div>
  {/each}
{/if}
```

Add the same `.skeleton` animation styles.

**Step 3: Use in DetailPanel and MeetingDetail loading states**

Replace the spinner in `DetailPanel.svelte` and `MeetingDetail.svelte` loading states with `<SkeletonLoader showPlayer={true} lines={6} />`.

**Step 4: Commit**

```bash
git add src/lib/components/SkeletonLoader.svelte src/lib/components/MeetingList.svelte src/lib/components/DetailPanel.svelte src/routes/MeetingDetail.svelte
git commit -m "feat: skeleton loaders for meeting list and detail views"
```

---

## Task 9: Pipeline Dots Labels and Dropdown Indicator

**Files:**
- Modify: `src/lib/components/PipelineDots.svelte`

**Step 1: Add labels and dropdown caret to the compact view**

In `PipelineDots.svelte`, the compact dot view (lines 101-138) shows just colored circles. Modify the MeetingDetail usage (not the MeetingRow usage — keep those compact) to show:
- Text labels under or beside each dot: "merge", "frames", "transcribe", "diarize", "analyze", "export"
- A subtle chevron icon (▼) next to the dots row indicating it's clickable/expandable

Add a `showLabels` prop (default `false`). In MeetingDetail.svelte, pass `showLabels={true}`.

When `showLabels` is true:
```html
<div style="display:flex;gap:8px;align-items:center;cursor:pointer;">
  {#each stages as stage}
    <div style="display:flex;flex-direction:column;align-items:center;gap:2px;">
      <div class="dot" style="width:8px;height:8px;border-radius:50%;background:{getColor(stage)};"></div>
      <span style="font-size:9px;color:var(--text-faint);font-family:'DM Sans',sans-serif;">{stage}</span>
    </div>
  {/each}
  <svg width="10" height="10" viewBox="0 0 10 10" style="color:var(--text-faint);margin-left:4px;">
    <path d="M2 3.5l3 3 3-3" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
  </svg>
</div>
```

**Step 2: Pass showLabels in MeetingDetail.svelte and DetailPanel.svelte**

In both `MeetingDetail.svelte` (around line 131) and `DetailPanel.svelte`, update the PipelineDots usage:
```svelte
<PipelineDots status={detail.pipeline_status} recordingPath={detail.recording_path} showLabels={true} />
```

**Step 3: Commit**

```bash
git add src/lib/components/PipelineDots.svelte src/routes/MeetingDetail.svelte src/lib/components/DetailPanel.svelte
git commit -m "feat: pipeline dots with labels and dropdown indicator"
```

---

## Task 10: Graph View Polish

**Files:**
- Modify: `src/routes/GraphView.svelte:541-689` (background, forces)
- Modify: `src/lib/components/GraphControls.svelte:61-73` (settings icon)

**Step 1: Add subtle grid background with bottom glow**

In `GraphView.svelte`, add a background pattern to the SVG container. Before the main `<g>` element, add:

```html
<!-- Grid pattern -->
<defs>
  <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
    <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--border)" stroke-width="0.3" opacity="0.3"/>
  </pattern>
</defs>
<rect width="100%" height="100%" fill="url(#grid)" />

<!-- Bottom glow gradient -->
<defs>
  <linearGradient id="bottomGlow" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0.7" stop-color="transparent"/>
    <stop offset="1" stop-color="rgba(77, 156, 245, 0.06)"/>
  </linearGradient>
</defs>
<rect width="100%" height="100%" fill="url(#bottomGlow)" />
```

The grid is very subtle (0.3 opacity, thin stroke). The bottom glow uses a hint of blue.

**Step 2: Debug and fix center force**

In `GraphView.svelte`, locate the force simulation setup (around lines 74-114). The center force may not be working because:
1. It might be using `d3.forceCenter()` which only sets the center of mass, not actually pulling nodes toward center
2. The `centerForce` slider value from GraphControls may not be wired into the simulation properly

Fix: Use `d3.forceX()` and `d3.forceY()` instead of `d3.forceCenter()` for a true centering pull:

```typescript
simulation
  .force("x", d3.forceX(width / 2).strength(centerForce / 1000))
  .force("y", d3.forceY(height / 2).strength(centerForce / 1000))
```

Remove or replace the existing `d3.forceCenter()` call. The `/1000` scaling maps the 0-100 slider to a reasonable 0-0.1 strength range.

Also ensure the simulation updates when the slider changes:
```typescript
$effect(() => {
  if (simulation) {
    simulation.force("x", d3.forceX(width / 2).strength(centerForce / 1000));
    simulation.force("y", d3.forceY(height / 2).strength(centerForce / 1000));
    simulation.alpha(0.3).restart();
  }
});
```

**Step 3: Fix the settings icon in GraphControls**

In `GraphControls.svelte` (lines 61-73), replace the current icon with a proper gear/cog SVG:

```html
<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="9" cy="9" r="2.5"/>
  <path d="M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2M3.1 3.1l1.4 1.4M13.5 13.5l1.4 1.4M3.1 14.9l1.4-1.4M13.5 4.5l1.4-1.4"/>
</svg>
```

Actually, that's still sun-like. Use a proper cog:

```html
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
  <circle cx="12" cy="12" r="3"/>
</svg>
```

**Step 4: Handle graph resize**

Add a `ResizeObserver` on the SVG container to update `width` and `height` and re-center forces:

```typescript
let resizeObserver: ResizeObserver;

onMount(() => {
  resizeObserver = new ResizeObserver((entries) => {
    const entry = entries[0];
    if (entry) {
      width = entry.contentRect.width;
      height = entry.contentRect.height;
      if (simulation) {
        simulation.force("x", d3.forceX(width / 2).strength(centerForce / 1000));
        simulation.force("y", d3.forceY(height / 2).strength(centerForce / 1000));
        simulation.alpha(0.3).restart();
      }
    }
  });
  resizeObserver.observe(svgElement);
});

onDestroy(() => {
  resizeObserver?.disconnect();
});
```

**Step 5: Commit**

```bash
git add src/routes/GraphView.svelte src/lib/components/GraphControls.svelte
git commit -m "feat: graph view grid background, center force fix, settings icon, resize handling"
```

---

## Task 11: Responsive Layout — Breakpoints

**Files:**
- Modify: `src/app.css` (breakpoint utilities)
- Modify: `src/routes/Dashboard.svelte` (narrow/wide behavior)
- Modify: `src/routes/MeetingDetail.svelte` (wide layout)
- Modify: `src/App.svelte` (nav bar responsive)
- Modify: `src/lib/components/FilterSidebar.svelte` (icon-only at narrow)

**Step 1: Dashboard narrow behavior**

In `Dashboard.svelte`, add a reactive width check. When the window is narrow (<900px) and a meeting is selected, hide the meeting list and show only the detail panel with a back button:

```typescript
let windowWidth = $state(window.innerWidth);

function handleResize() {
  windowWidth = window.innerWidth;
}
```

Add `onMount(() => window.addEventListener("resize", handleResize))` and cleanup in `onDestroy`.

Conditional rendering:
```svelte
{#if windowWidth < 900 && selectedMeetingId}
  <!-- Full-width detail with back button -->
  <div class="flex flex-col h-full">
    <button onclick={handleCloseDetail} style="...">
      ← Back to meetings
    </button>
    <DetailPanel meetingId={selectedMeetingId} onClose={handleCloseDetail} />
  </div>
{:else}
  <!-- Current two-panel layout -->
  ...
{/if}
```

**Step 2: MeetingDetail wide layout**

In `MeetingDetail.svelte`, at >1400px, render player and tab content side-by-side instead of stacked:

```svelte
<div class={windowWidth > 1400 ? "flex gap-6" : "flex flex-col"}>
  <div class={windowWidth > 1400 ? "flex-shrink-0" : ""} style={windowWidth > 1400 ? "width:45%;" : ""}>
    <MeetingPlayer ... />
  </div>
  <div class="flex-1">
    <!-- Tabs + content -->
  </div>
</div>
```

**Step 3: Nav bar icons-only at narrow widths**

In `App.svelte`, conditionally show only icons (no text) for route links when window < 900px. Each route link needs an icon + text, where text hides at narrow widths:

```svelte
<span style={windowWidth < 900 ? "display:none" : ""}>{label}</span>
```

Add route icons (small SVGs) that are always visible.

**Step 4: FilterSidebar icon-only at narrow**

In `FilterSidebar.svelte`, when window < 900px, force the sidebar to icon-only mode (collapsed width with just filter category icons, no text labels). The expanded state should overlay the content instead of pushing it.

**Step 5: Commit**

```bash
git add src/app.css src/routes/Dashboard.svelte src/routes/MeetingDetail.svelte src/App.svelte src/lib/components/FilterSidebar.svelte
git commit -m "feat: responsive layout breakpoints (narrow/standard/wide)"
```

---

## Task 12: Zoom Overflow Bug Fix

**Files:**
- Modify: `src/App.svelte` (container overflow)
- Modify: `src/routes/Dashboard.svelte` (scroll containers)

**Step 1: Audit the overflow hierarchy**

The bug: at zoomed-in sizes, a third scrollbar appears on the far right. This means there's a container that shouldn't be scrollable.

The container hierarchy is:
1. `<body>` / `<html>` — should be `overflow: hidden`
2. `App.svelte` outer div — should be `overflow: hidden`, `height: 100vh`
3. Route content area — should be `overflow: hidden`
4. Individual scroll areas (meeting list, detail panel) — `overflow-y: auto`

Fix in `src/app.css`:
```css
html, body {
  margin: 0;
  padding: 0;
  overflow: hidden;
  height: 100%;
}
```

In `App.svelte`, ensure the outermost container has `height: 100vh; overflow: hidden;`.

The zoom scaling (via `transform: scale()` in App.svelte lines 15-40) may be causing content to extend beyond bounds. Ensure the zoom container has `overflow: hidden` and `transform-origin: top left`.

**Step 2: Test at various zoom levels**

Test at 100%, 125%, 150% zoom and verify only two scrollbars maximum (meeting list + detail panel content).

**Step 3: Commit**

```bash
git add src/app.css src/App.svelte
git commit -m "fix: overflow scrollbar bug at zoomed-in sizes"
```

---

## Task 13: Settings Layout — Two Column and Info Popovers

**Files:**
- Modify: `src/routes/Settings.svelte` (two-column layout, provider dropdown)
- Create: `src/lib/components/SettingsTooltip.svelte`

**Step 1: Two-column layout at wide widths**

In `Settings.svelte`, the current layout is single-column with `max-width: 700px` (line 47-48). Change to a two-column CSS grid at >1000px:

```html
<div style="
  display: grid;
  grid-template-columns: {windowWidth > 1000 ? '1fr 1fr' : '1fr'};
  gap: 24px;
  max-width: {windowWidth > 1000 ? '1000px' : '700px'};
  margin: 0 auto;
  padding: 24px;
">
```

Certain sections (like Platform Connections) should span both columns:
```html
<div style="grid-column: 1 / -1;">
```

**Step 2: Platform connections as dropdown with status dots**

Replace the current ProviderStatusCard grid (lines 50-63) with a collapsible dropdown:

```svelte
<button onclick={() => platformsExpanded = !platformsExpanded} style="
  width:100%;display:flex;align-items:center;justify-content:between;
  padding:12px 16px;background:var(--surface);border-radius:8px;border:1px solid var(--border);
  color:var(--text);cursor:pointer;
">
  <span style="font-weight:600;">Platform Connections</span>
  <div style="display:flex;gap:6px;margin-left:auto;margin-right:12px;">
    {#each providers as provider}
      <span style="width:8px;height:8px;border-radius:50;background:{isConnected(provider) ? 'var(--green)' : 'var(--text-faint)'}"></span>
    {/each}
  </div>
  <svg ...chevron rotated when expanded.../>
</button>

{#if platformsExpanded}
  <div transition:slide={{ duration: 200 }}>
    {#each providers as provider}
      <ProviderStatusCard ... />
    {/each}
  </div>
{/if}
```

**Step 3: Create SettingsTooltip component**

```svelte
<!-- src/lib/components/SettingsTooltip.svelte -->
<script lang="ts">
  interface Props { text: string; }
  let { text }: Props = $props();
  let visible = $state(false);
</script>

<span
  style="position:relative;display:inline-flex;align-items:center;margin-left:6px;cursor:help;"
  onmouseenter={() => visible = true}
  onmouseleave={() => visible = false}
>
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="var(--text-faint)" stroke-width="1.5">
    <circle cx="7" cy="7" r="6"/>
    <path d="M5.5 5.5a1.5 1.5 0 1 1 2.12 1.37c-.42.24-.62.63-.62 1.13M7 10h.01"/>
  </svg>
  {#if visible}
    <div style="
      position:absolute;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);
      padding:8px 12px;border-radius:6px;background:var(--raised);border:1px solid var(--border);
      color:var(--text-secondary);font-size:12px;font-family:'DM Sans',sans-serif;
      white-space:nowrap;z-index:100;box-shadow:0 4px 12px rgba(0,0,0,0.3);
      pointer-events:none;
    ">
      {text}
    </div>
  {/if}
</span>
```

**Step 4: Add tooltips to all settings dropdowns**

Go through each settings component (`VaultSettings`, `RecordingSettings`, `ClaudeSettings`, `WhisperXSettings`, `TodoistSettings`, `GeneralSettings`, `RecordingBehaviorSettings`) and add `<SettingsTooltip text="..." />` next to each dropdown/select label with a description of what the setting does.

**Step 5: Commit**

```bash
git add src/routes/Settings.svelte src/lib/components/SettingsTooltip.svelte src/lib/components/*Settings.svelte
git commit -m "feat: settings two-column layout, provider dropdown, info tooltips"
```

---

## Task 14: Bulk Operations — Rust Backend

**Files:**
- Modify: `src-tauri/src/meetings.rs` (new IPC commands)
- Modify: `src-tauri/src/lib.rs:151-186` (register commands)

**Step 1: Add delete_meetings command**

In `meetings.rs`, add:

```rust
#[tauri::command]
pub async fn delete_meetings(ids: Vec<String>, app: tauri::AppHandle) -> Result<Vec<String>, String> {
    let store = app.store("store.json").map_err(|e| e.to_string())?;
    let recordings_folder: String = store
        .get("recordingsFolder")
        .and_then(|v| v.as_str().map(String::from))
        .ok_or("No recordings folder configured")?;

    let base_path = std::path::PathBuf::from(&recordings_folder);
    let mut deleted = Vec::new();
    let mut errors = Vec::new();

    for id in &ids {
        let meeting_path = base_path.join(id);
        if meeting_path.exists() {
            match std::fs::remove_dir_all(&meeting_path) {
                Ok(_) => deleted.push(id.clone()),
                Err(e) => errors.push(format!("{}: {}", id, e)),
            }
        } else {
            errors.push(format!("{}: not found", id));
        }
    }

    if !errors.is_empty() {
        log::warn!("Some meetings failed to delete: {:?}", errors);
    }

    Ok(deleted)
}
```

**Step 2: Add reprocess_meetings command**

```rust
#[tauri::command]
pub async fn reprocess_meetings(ids: Vec<String>, app: tauri::AppHandle) -> Result<(), String> {
    for id in &ids {
        // Reset status.json to trigger reprocessing
        let store = app.store("store.json").map_err(|e| e.to_string())?;
        let recordings_folder: String = store
            .get("recordingsFolder")
            .and_then(|v| v.as_str().map(String::from))
            .ok_or("No recordings folder configured")?;

        let status_path = std::path::PathBuf::from(&recordings_folder)
            .join(id)
            .join("status.json");

        if status_path.exists() {
            std::fs::write(&status_path, "{}").map_err(|e| e.to_string())?;
        }
    }
    // Launch sidecar for reprocessing — reuse existing run_pipeline logic
    // The frontend should call retryProcessing for each meeting sequentially
    Ok(())
}
```

Note: Bulk reprocess may be better handled by calling the existing `retryProcessing` IPC per meeting from the frontend, sequentially. The Rust side just needs to reset status files. Evaluate during implementation.

**Step 3: Add bulk_rename_speaker command**

```rust
#[tauri::command]
pub async fn bulk_rename_speaker(
    old_name: String,
    new_name: String,
    meeting_ids: Vec<String>,
    app: tauri::AppHandle,
) -> Result<u32, String> {
    let store = app.store("store.json").map_err(|e| e.to_string())?;
    let recordings_folder: String = store
        .get("recordingsFolder")
        .and_then(|v| v.as_str().map(String::from))
        .ok_or("No recordings folder configured")?;

    let base_path = std::path::PathBuf::from(&recordings_folder);
    let mut updated_count: u32 = 0;

    for id in &meeting_ids {
        let transcript_path = base_path.join(id).join("transcript.json");
        if !transcript_path.exists() {
            continue;
        }

        let content = std::fs::read_to_string(&transcript_path).map_err(|e| e.to_string())?;
        let mut data: serde_json::Value = serde_json::from_str(&content).map_err(|e| e.to_string())?;

        let mut changed = false;
        if let Some(utterances) = data.get_mut("utterances").and_then(|v| v.as_array_mut()) {
            for utt in utterances {
                if let Some(speaker) = utt.get_mut("speaker") {
                    if speaker.as_str() == Some(&old_name) {
                        *speaker = serde_json::Value::String(new_name.clone());
                        changed = true;
                    }
                }
            }
        }

        if changed {
            let updated = serde_json::to_string_pretty(&data).map_err(|e| e.to_string())?;
            std::fs::write(&transcript_path, updated).map_err(|e| e.to_string())?;
            updated_count += 1;
        }
    }

    Ok(updated_count)
}
```

**Step 4: Register commands in lib.rs**

In `src-tauri/src/lib.rs`, add the new commands to the `invoke_handler!` macro (lines 151-186):

```rust
meetings::delete_meetings,
meetings::reprocess_meetings,
meetings::bulk_rename_speaker,
```

**Step 5: Commit**

```bash
git add src-tauri/src/meetings.rs src-tauri/src/lib.rs
git commit -m "feat: bulk operations Rust backend (delete, reprocess, rename speaker)"
```

---

## Task 15: Bulk Operations — Frontend IPC and Store

**Files:**
- Modify: `src/lib/tauri.ts` (new IPC wrappers)
- Create: `src/lib/stores/selection.ts` (selection state management)

**Step 1: Add IPC wrappers to tauri.ts**

```typescript
export async function deleteMeetings(ids: string[]): Promise<string[]> {
  return invoke<string[]>("delete_meetings", { ids });
}

export async function reprocessMeetings(ids: string[]): Promise<void> {
  return invoke<void>("reprocess_meetings", { ids });
}

export async function bulkRenameSpeaker(oldName: string, newName: string, meetingIds: string[]): Promise<number> {
  return invoke<number>("bulk_rename_speaker", { oldName, newName, meetingIds });
}
```

**Step 2: Create selection store**

```typescript
// src/lib/stores/selection.ts
import { writable, derived } from "svelte/store";

export const selectMode = writable(false);
export const selectedIds = writable<Set<string>>(new Set());

export const selectedCount = derived(selectedIds, ($ids) => $ids.size);

export function toggleSelect(id: string) {
  selectedIds.update((ids) => {
    const next = new Set(ids);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
}

export function selectRange(allIds: string[], fromId: string, toId: string) {
  const fromIdx = allIds.indexOf(fromId);
  const toIdx = allIds.indexOf(toId);
  if (fromIdx === -1 || toIdx === -1) return;
  const [start, end] = fromIdx < toIdx ? [fromIdx, toIdx] : [toIdx, fromIdx];
  selectedIds.update((ids) => {
    const next = new Set(ids);
    for (let i = start; i <= end; i++) next.add(allIds[i]);
    return next;
  });
}

export function selectAll(ids: string[]) {
  selectedIds.update((current) => {
    const next = new Set(current);
    ids.forEach((id) => next.add(id));
    return next;
  });
}

export function clearSelection() {
  selectedIds.set(new Set());
  selectMode.set(false);
}

export function enterSelectMode() {
  selectMode.set(true);
}

export function exitSelectMode() {
  clearSelection();
}
```

**Step 3: Commit**

```bash
git add src/lib/tauri.ts src/lib/stores/selection.ts
git commit -m "feat: bulk operations IPC wrappers and selection store"
```

---

## Task 16: Bulk Operations — UI Components

**Files:**
- Modify: `src/lib/components/MeetingRow.svelte` (checkbox in select mode)
- Modify: `src/lib/components/MeetingList.svelte` (select-all per group)
- Modify: `src/routes/Dashboard.svelte` (select button, action bar, detail panel state)
- Create: `src/lib/components/BulkActionBar.svelte`
- Create: `src/lib/components/BulkSpeakerModal.svelte`

**Step 1: Add checkbox to MeetingRow**

In `MeetingRow.svelte`, add a `selectMode` and `isChecked` prop. When in select mode, show a checkbox on the left and clicking the row toggles the checkbox instead of navigating:

```svelte
interface Props {
  meeting: MeetingSummary;
  isSelected?: boolean;
  onSelect?: (id: string) => void;
  selectMode?: boolean;
  isChecked?: boolean;
  onToggleCheck?: (id: string, shiftKey: boolean) => void;
}
```

When `selectMode` is true, render a checkbox before the title and handle click differently:
```svelte
function handleClick(e: MouseEvent) {
  if (selectMode && onToggleCheck) {
    e.preventDefault();
    onToggleCheck(meeting.id, e.shiftKey);
    return;
  }
  if (onSelect) {
    e.preventDefault();
    onSelect(meeting.id);
  }
}
```

Checkbox rendering (before the title div):
```html
{#if selectMode}
  <div style="flex-shrink:0;margin-right:10px;display:flex;align-items:center;">
    <div style="
      width:18px;height:18px;border-radius:4px;
      border:2px solid {isChecked ? 'var(--gold)' : 'var(--border-bright)'};
      background:{isChecked ? 'var(--gold)' : 'transparent'};
      display:flex;align-items:center;justify-content:center;
      transition:all 150ms ease;
    ">
      {#if isChecked}
        <svg width="12" height="12" viewBox="0 0 12 12"><path d="M2.5 6l2.5 2.5 4.5-5" stroke="var(--bg)" stroke-width="2" fill="none"/></svg>
      {/if}
    </div>
  </div>
{/if}
```

**Step 2: Add select-all per date group in MeetingList**

In `MeetingList.svelte`, when in select mode, each date group header gets a "Select All" checkbox:

```svelte
{#if $selectMode}
  <div style="..." onclick={() => selectAll(group.meetings.map(m => m.id))}>
    <!-- group select-all checkbox -->
  </div>
{/if}
```

**Step 3: Create BulkActionBar component**

```svelte
<!-- src/lib/components/BulkActionBar.svelte -->
<script lang="ts">
  import { fly } from "svelte/transition";
  import { selectedCount, exitSelectMode } from "../stores/selection";

  interface Props {
    onDelete: () => void;
    onReprocess: () => void;
    onFixSpeakers: () => void;
    reprocessDisabled?: boolean;
  }

  let { onDelete, onReprocess, onFixSpeakers, reprocessDisabled = false }: Props = $props();
</script>

{#if $selectedCount > 0}
  <div
    transition:fly={{ y: 60, duration: 300 }}
    style="
      position:sticky;bottom:0;left:0;right:0;
      padding:12px 24px;
      background:var(--raised);
      border-top:1px solid var(--border);
      display:flex;align-items:center;gap:12px;
      z-index:50;
    "
  >
    <span style="color:var(--gold);font-family:'DM Sans',sans-serif;font-size:14px;font-weight:600;">
      {$selectedCount} selected
    </span>
    <div style="margin-left:auto;display:flex;gap:8px;">
      <button onclick={onReprocess} disabled={reprocessDisabled} style="...">Reprocess</button>
      <button onclick={onFixSpeakers} style="...">Fix Speakers</button>
      <button onclick={onDelete} style="...;color:var(--red);border-color:var(--red);">Delete</button>
    </div>
  </div>
{/if}
```

**Step 4: Create BulkSpeakerModal**

```svelte
<!-- src/lib/components/BulkSpeakerModal.svelte -->
```

This modal:
- Receives the list of selected meeting IDs
- Fetches unique speaker names across those meetings (new IPC: `get_speakers_for_meetings`)
- Shows each speaker name with occurrence count
- User clicks a speaker, types the new name, clicks "Rename"
- Calls `bulkRenameSpeaker(oldName, newName, meetingIds)` from tauri.ts
- Shows toast on completion

**Step 5: Wire everything in Dashboard.svelte**

- "Select" button next to SearchBar, visible when not in select mode
- "Cancel" button when in select mode
- Close detail panel when entering select mode
- BulkActionBar at the bottom of the meeting list panel
- Delete confirmation modal
- BulkSpeakerModal
- All bulk actions show toasts and refresh meeting list on completion

**Step 6: Commit**

```bash
git add src/lib/components/MeetingRow.svelte src/lib/components/MeetingList.svelte src/routes/Dashboard.svelte src/lib/components/BulkActionBar.svelte src/lib/components/BulkSpeakerModal.svelte
git commit -m "feat: bulk operations UI (select mode, action bar, speaker modal)"
```

---

## Task 17: Todoist Project Grouping

**Files:**
- Modify: `src/lib/stores/settings.ts` (new setting)
- Modify: `src/lib/components/TodoistSettings.svelte` (grouping dropdown)
- Modify: `recap/todoist.py` (project-per-company logic)
- Modify: `recap/config.py` (new config field)

**Step 1: Add todoistProjectGrouping setting**

In `settings.ts`, add to `AppSettings` interface:
```typescript
todoistProjectGrouping: "company" | "meeting" | "single";
```

Default: `"company"`

**Step 2: Add grouping dropdown in TodoistSettings.svelte**

Add a select dropdown with the three options + a `<SettingsTooltip>` explaining each:
- "Per company" — Creates a Todoist project per company (e.g., "Recap: Acme Corp")
- "Per meeting" — Creates a Todoist project per meeting (e.g., "Recap: Q1 Planning Review")
- "Single project" — All tasks go to one project (current behavior)

**Step 3: Update todoist.py for project grouping**

Modify `create_tasks()` to accept a `grouping` parameter and a `company_name` / `meeting_title`:

```python
def _resolve_project(
    api: TodoistAPI,
    grouping: str,
    default_project_name: str,
    company_name: str | None,
    meeting_title: str,
) -> str | None:
    if grouping == "company" and company_name:
        project_name = f"Recap: {company_name}"
    elif grouping == "meeting":
        project_name = f"Recap: {meeting_title}"
    else:
        project_name = default_project_name

    # Look up or create project
    projects = api.get_projects()
    for proj in projects:
        if proj.name == project_name:
            return proj.id

    new_proj = api.add_project(name=project_name)
    return new_proj.id
```

Update the `create_tasks` function signature and callers to pass company name and meeting title.

**Step 4: Update config.py**

Add `todoist_project_grouping` field to the config, passed through from the settings store via `config_gen.rs`.

**Step 5: Commit**

```bash
git add src/lib/stores/settings.ts src/lib/components/TodoistSettings.svelte recap/todoist.py recap/config.py
git commit -m "feat: Todoist project grouping (per-company, per-meeting, single)"
```

---

## Task 18: Todoist Task ID Storage

**Files:**
- Modify: `recap/todoist.py` (save task IDs)
- Modify: `recap/pipeline.py` (pass meeting dir to todoist stage)

**Step 1: Save todoist_tasks.json after task creation**

In `todoist.py`, after creating tasks, write a `todoist_tasks.json` file:

```python
import json
from datetime import datetime, timezone

def _save_task_mapping(meeting_dir: pathlib.Path, tasks: list[dict]) -> None:
    path = meeting_dir / "todoist_tasks.json"
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())["tasks"]
        except (json.JSONDecodeError, KeyError):
            pass

    data = {
        "tasks": existing + tasks,
        "last_synced": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2))
```

Modify `create_tasks()` to return task dicts (not just IDs) and call `_save_task_mapping()`:

```python
task_records = []
# ... inside the creation loop, after api.add_task():
task_records.append({
    "todoist_id": task.id,
    "description": item.description,
    "project_id": project_id,
})
# ... after loop:
if task_records and meeting_dir:
    _save_task_mapping(meeting_dir, task_records)
```

**Step 2: Pass meeting_dir to todoist stage**

In `pipeline.py`, ensure the todoist stage receives the meeting directory path so it can write `todoist_tasks.json` alongside `status.json`.

**Step 3: Commit**

```bash
git add recap/todoist.py recap/pipeline.py
git commit -m "feat: save Todoist task IDs in todoist_tasks.json"
```

---

## Task 19: Todoist Completion Sync

**Files:**
- Modify: `recap/todoist.py` (sync_completions function)
- Modify: `recap/vault.py` (update checkboxes)
- Modify: `recap/cli.py` (new --only todoist-sync stage)
- Modify: `recap/pipeline.py` (register new stage)

**Step 1: Add sync_completions function**

```python
def sync_completions(
    meeting_dir: pathlib.Path,
    vault_note_path: pathlib.Path,
    api_token: str,
) -> dict:
    """Sync Todoist task completion status back to vault note."""
    tasks_path = meeting_dir / "todoist_tasks.json"
    if not tasks_path.exists():
        return {"synced": 0, "note_missing": False}

    data = json.loads(tasks_path.read_text())
    tasks = data.get("tasks", [])

    if not tasks:
        return {"synced": 0, "note_missing": False}

    if not vault_note_path.exists():
        return {"synced": 0, "note_missing": True, "expected_path": str(vault_note_path)}

    api = TodoistAPI(api_token)
    synced_count = 0

    for task_record in tasks:
        if task_record.get("completed_at"):
            continue  # Already synced

        todoist_id = task_record["todoist_id"]
        try:
            task = api.get_task(todoist_id)
            if task.is_completed:
                _update_vault_checkbox(vault_note_path, task_record["description"], checked=True)
                task_record["completed_at"] = datetime.now(timezone.utc).isoformat()
                synced_count += 1
        except Exception as e:
            if "404" in str(e):
                # Task was deleted in Todoist
                _update_vault_checkbox(vault_note_path, task_record["description"], strikethrough=True)
                task_record["deleted_at"] = datetime.now(timezone.utc).isoformat()
                synced_count += 1
            else:
                logger.warning("Failed to check task %s: %s", todoist_id, e)

    # Save updated task records
    data["tasks"] = tasks
    data["last_synced"] = datetime.now(timezone.utc).isoformat()
    tasks_path.write_text(json.dumps(data, indent=2))

    return {"synced": synced_count, "note_missing": False}


def _update_vault_checkbox(note_path: pathlib.Path, description: str, checked: bool = False, strikethrough: bool = False) -> None:
    content = note_path.read_text(encoding="utf-8")
    # Match the action item line
    old_pattern = f"- [ ] "  # followed by assignee: description
    if checked:
        new_mark = "- [x] "
    elif strikethrough:
        new_mark = "- [~] "
    else:
        return

    # Find the line containing this description and update the checkbox
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if description in line and line.strip().startswith("- [ ]"):
            lines[i] = line.replace("- [ ]", new_mark, 1)
            break

    note_path.write_text("\n".join(lines), encoding="utf-8")
```

**Step 2: Add todoist-sync CLI stage**

In `cli.py`, add `todoist-sync` as a valid `--only` stage. In `pipeline.py`, register it as a stage that iterates all meetings with `todoist_tasks.json` and calls `sync_completions()`.

**Step 3: Add rate limiting**

Wrap Todoist API calls with a simple rate limiter:

```python
import time

class RateLimiter:
    def __init__(self, calls_per_second: float = 8):
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0.0

    def wait(self):
        elapsed = time.monotonic() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.monotonic()
```

Use before each API call. Handle 429 responses with exponential backoff (1s, 2s, 4s, max 3 retries).

**Step 4: Commit**

```bash
git add recap/todoist.py recap/vault.py recap/cli.py recap/pipeline.py
git commit -m "feat: Todoist bidirectional completion sync with rate limiting"
```

---

## Task 20: Todoist Auto-Sync Timer and UI

**Files:**
- Modify: `src-tauri/src/lib.rs` (add sync timer)
- Modify: `src/lib/components/TodoistSettings.svelte` (sync now + status)
- Modify: `src/lib/stores/settings.ts` (sync interval setting)
- Modify: `src/lib/tauri.ts` (new IPC)

**Step 1: Add sync interval setting**

In `settings.ts`, add:
```typescript
todoistSyncInterval: number;  // minutes, default 15
```

**Step 2: Add auto-sync timer in lib.rs**

In `lib.rs`, alongside the existing 60s auto-record check (lines 89-137), add a Todoist sync timer:

```rust
// Todoist completion sync
let app_handle_todoist = app.handle().clone();
tauri::async_runtime::spawn(async move {
    loop {
        tokio::time::sleep(std::time::Duration::from_secs(900)).await; // 15 min default
        // Read interval from store, launch sidecar with --only todoist-sync
        if let Ok(store) = app_handle_todoist.store("store.json") {
            if let Some(token) = store.get("todoistApiToken") {
                if token.as_str().map(|s| !s.is_empty()).unwrap_or(false) {
                    let _ = crate::sidecar::run_pipeline_sync(&app_handle_todoist, "todoist-sync").await;
                }
            }
        }
    }
});
```

**Step 3: Add "Sync Now" button and last-synced display in TodoistSettings**

Add a button that calls a new IPC command to trigger sync immediately. Show the last sync timestamp (read from the most recent `todoist_tasks.json`).

**Step 4: Commit**

```bash
git add src-tauri/src/lib.rs src/lib/components/TodoistSettings.svelte src/lib/stores/settings.ts src/lib/tauri.ts
git commit -m "feat: Todoist auto-sync timer and manual sync UI"
```

---

## Task 21: Vault Note Relink Flow

**Files:**
- Create: `src/lib/components/RelinkNotesModal.svelte`
- Modify: `src/lib/tauri.ts` (relink IPC)
- Modify: `src-tauri/src/meetings.rs` (relink command)

**Step 1: Create relink modal component**

The modal shows:
- Count of missing vault notes
- List of expected paths that weren't found
- "Locate" button that opens a file dialog (via Tauri's `dialog.open()`)
- After one file is located, check if other missing notes exist in the same relative folder structure
- Auto-relink matches, show remaining for manual resolution
- "Skip" button to dismiss

**Step 2: Add Rust relink command**

```rust
#[tauri::command]
pub async fn relink_vault_notes(
    found_path: String,
    expected_path: String,
    other_missing: Vec<(String, String)>,  // (meeting_id, expected_path)
) -> Result<Vec<(String, String)>, String> {
    // Calculate path offset between expected and found
    // Apply same offset to other missing paths
    // Return list of (meeting_id, new_path) for auto-relinked notes
    // Update todoist_tasks.json with corrected paths
}
```

**Step 3: Wire into Todoist sync flow**

When `sync_completions` returns `note_missing: true`, collect all missing notes and show the relink modal.

**Step 4: Commit**

```bash
git add src/lib/components/RelinkNotesModal.svelte src/lib/tauri.ts src-tauri/src/meetings.rs
git commit -m "feat: vault note relink flow for Todoist sync"
```

---

## Task 22: Calendar Sync Bug Fix

**Files:**
- Modify: `src-tauri/src/calendar.rs` (debug sync)
- Modify: `src/App.svelte:47-57` (auto-sync trigger)

**Step 1: Debug the calendar sync**

In `App.svelte` (lines 47-57), there's an auto-sync that fires on window focus with a 15-minute debounce. The Zoho calendar API calls are in `calendar.rs`.

Investigate:
1. Is the auto-sync function actually being called? Add logging.
2. Are the Zoho OAuth tokens valid? Check token refresh flow.
3. Is the Zoho Calendar API returning data? Check the response parsing.
4. Is the cache invalidation working? The `CalendarCache` struct might be caching stale data.

Common issues:
- Token expired and refresh flow has a bug
- Cache TTL too long
- API endpoint URL incorrect for the user's Zoho data center (zoho.com vs zoho.eu vs zoho.in)

**Step 2: Fix the root cause**

This depends on what debugging reveals. Most likely fixes:
- Add token refresh before API calls
- Reduce cache TTL or add a manual refresh button
- Handle Zoho data center differences in the API URL

**Step 3: Commit**

```bash
git add src-tauri/src/calendar.rs src/App.svelte
git commit -m "fix: calendar sync not updating with Zoho connection"
```

---

## Task 23: Responsive — Remaining Items

**Files:**
- Modify: `src/routes/Settings.svelte` (already handled in Task 13)
- Modify: `src/routes/GraphView.svelte` (already handled resize in Task 10)
- Modify: `src/lib/components/Onboarding.svelte` (narrow width padding)
- Modify: `src/routes/Calendar.svelte` (narrow width overflow)

**Step 1: Onboarding narrow-width fix**

In `Onboarding.svelte`, reduce horizontal padding and max-width at narrow window widths. The wizard content should remain centered and readable.

**Step 2: Calendar narrow-width fix**

Check `Calendar.svelte` for horizontal overflow at narrow widths. Calendar grids often overflow — may need horizontal scrolling or a list-view fallback at narrow widths.

**Step 3: Search bar narrow-width fix**

In `Dashboard.svelte`, ensure the search bar and filter toggle button don't get cramped at narrow widths. The search bar should flex to fill available space.

**Step 4: Commit**

```bash
git add src/lib/components/Onboarding.svelte src/routes/Calendar.svelte src/routes/Dashboard.svelte
git commit -m "feat: responsive fixes for onboarding, calendar, and search"
```

---

## Task 24: Final Polish Sweep

**Step 1: Visual review pass**

Run the app and check every view:
- Dashboard (with and without meetings)
- Meeting detail (with and without recording)
- Calendar view
- Graph view
- Settings
- Onboarding flow

Look for:
- Inconsistent spacing/padding
- Hard-coded colors not using CSS variables
- Missing hover states
- Rough transitions
- Text overflow/truncation issues

**Step 2: Fix any issues found**

Address anything discovered during the sweep.

**Step 3: Update MANIFEST.md**

Regenerate `MANIFEST.md` to reflect new files:
- `src/lib/assets/logo.svg`
- `src/lib/stores/toasts.ts`
- `src/lib/stores/selection.ts`
- `src/lib/components/ToastContainer.svelte`
- `src/lib/components/SkeletonLoader.svelte`
- `src/lib/components/BulkActionBar.svelte`
- `src/lib/components/BulkSpeakerModal.svelte`
- `src/lib/components/SettingsTooltip.svelte`
- `src/lib/components/RelinkNotesModal.svelte`

**Step 4: Update future-phases.md**

Mark Phase 8 items as complete (except light mode, which remains deferred).

**Step 5: Final commit**

```bash
git add -A
git commit -m "docs: update MANIFEST.md and future-phases.md for Phase 8"
```
