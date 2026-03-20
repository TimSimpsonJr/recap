# Animations & Transitions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add polished animations and transitions throughout the Recap desktop app for a refined, snappy feel.

**Architecture:** All animations use CSS transitions where possible, Svelte `transition:` directives for mount/unmount. A shared `reducedMotion` store drives duration to 0 when `prefers-reduced-motion` is active. No new dependencies.

**Tech Stack:** Svelte 5 (runes), Tailwind CSS 4, CSS transitions/keyframes

**Design doc:** `docs/plans/2026-03-20-animations-design.md`

---

### Task 1: Add `prefers-reduced-motion` support

This goes first because every subsequent task will use it.

**Files:**
- Modify: `src/app.css` (add media query after line 48)
- Create: `src/lib/reduced-motion.ts`

**Step 1: Add CSS reduced-motion override to `app.css`**

After the `button:active` rule (line 48), add:

```css
/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

**Step 2: Create the Svelte reduced-motion helper**

Create `src/lib/reduced-motion.ts`:

```typescript
import { readable } from "svelte/store";

function getReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export const reducedMotion = readable(getReducedMotion(), (set) => {
  if (typeof window === "undefined") return;
  const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
  const handler = (e: MediaQueryListEvent) => set(e.matches);
  mql.addEventListener("change", handler);
  return () => mql.removeEventListener("change", handler);
});

/** Returns transition params with duration: 0 when reduced motion is preferred. */
export function motionParams<T extends { duration?: number }>(
  params: T,
  reduced: boolean
): T {
  if (reduced) return { ...params, duration: 0, delay: 0 };
  return params;
}
```

**Step 3: Commit**

```
feat: add prefers-reduced-motion support
```

---

### Task 2: Directional page transitions

Replace the jumpy 150ms fade with directional slides based on tab order.

**Files:**
- Modify: `src/App.svelte` (lines 1-10 imports, lines 113-130 route logic, lines 344-356 route template)

**Step 1: Add route index tracking**

In the `<script>` block of `App.svelte`, add a route-order map and previous-route tracking:

```typescript
import { fly } from "svelte/transition";
import { reducedMotion, motionParams } from "./lib/reduced-motion";

const ROUTE_ORDER: Record<string, number> = {
  dashboard: 0,
  calendar: 1,
  graph: 2,
  settings: 3,
};

let prevRouteIndex = $state(0);
let slideDirection = $state(1); // 1 = right, -1 = left
```

**Step 2: Update the `updateRoute` function to track direction**

Inside `updateRoute()` (around line 113), before setting `currentRoute`, compute direction:

```typescript
const updateRoute = () => {
  const hash = window.location.hash.slice(1) || "dashboard";
  const meetingMatch = hash.match(/^meeting\/(.+)$/);
  const filterMatch = hash.match(/^filter\/participant\/(.+)$/);

  let nextRoute: string;
  if (meetingMatch) {
    nextRoute = "dashboard";
    meetingId = meetingMatch[1];
    filterParticipant = null;
  } else if (filterMatch) {
    nextRoute = "dashboard";
    meetingId = null;
    filterParticipant = decodeURIComponent(filterMatch[1]);
  } else {
    nextRoute = hash;
    meetingId = null;
    filterParticipant = null;
  }

  const nextIndex = ROUTE_ORDER[nextRoute] ?? 0;
  if (nextRoute !== currentRoute) {
    slideDirection = nextIndex > prevRouteIndex ? 1 : -1;
    prevRouteIndex = nextIndex;
  }
  currentRoute = nextRoute;
};
```

**Step 3: Replace the route template transition**

Replace lines 344-356:

```svelte
{#key currentRoute}
  <div
    class="flex-1 overflow-hidden flex flex-col"
    in:fly={motionParams({ x: slideDirection * 60, duration: 200, easing: cubicOut }, $reducedMotion)}
    out:fly={motionParams({ x: slideDirection * -60, duration: 200, easing: cubicOut }, $reducedMotion)}
  >
    {#if currentRoute === "settings"}
      <Settings />
    {:else if currentRoute === "calendar"}
      <Calendar />
    {:else if currentRoute === "graph"}
      <GraphView />
    {:else}
      <Dashboard initialMeetingId={meetingId} initialFilterParticipant={filterParticipant} />
    {/if}
  </div>
{/key}
```

Also add the easing import at the top:

```typescript
import { cubicOut } from "svelte/easing";
```

**Step 4: Remove the old `fade` import if no longer used**

Check if `fade` is used elsewhere in App.svelte. If not, remove it from imports.

**Step 5: Test manually**

Click between tabs — content should slide left when navigating forward (Meetings → Calendar → Graph → Settings) and right when navigating backward.

**Step 6: Commit**

```
feat: add directional slide transitions for page navigation
```

---

### Task 3: Dashboard split layout — always-on with slide-in detail

Eliminate the layout reflow by always rendering the split, and slide detail content in from the left.

**Files:**
- Modify: `src/routes/Dashboard.svelte` (lines 361-369 template, lines 382-417 styles)

**Step 1: Add imports**

```typescript
import { fly } from "svelte/transition";
import { reducedMotion, motionParams } from "../lib/reduced-motion";
```

**Step 2: Modify the template to always render the detail area**

Replace lines 361-369:

```svelte
<!-- Detail panel — always present, content slides in -->
{#if !$selectMode}
  <div class="detail-panel-wrapper" class:has-content={!!selectedMeetingId}>
    {#if selectedMeetingId}
      {#key selectedMeetingId}
        <div in:fly={motionParams({ x: -40, duration: 200 }, $reducedMotion)}>
          <DetailPanel
            meetingId={selectedMeetingId}
            onClose={handleCloseDetail}
          />
        </div>
      {/key}
    {:else}
      <div class="empty-detail">
        <span style="color: var(--text-faint); font-size: 14px;">Select a meeting to view details</span>
      </div>
    {/if}
  </div>
{/if}
```

**Step 3: Update the CSS**

Replace the `.detail-panel-wrapper` and `@keyframes slide-in` styles (lines 402-417):

```css
.detail-panel-wrapper {
  flex: 0 0 0px;
  overflow: hidden;
  transition: flex-basis 300ms cubic-bezier(0.4, 0, 0.2, 1);
}

.detail-panel-wrapper.has-content {
  flex: 1;
}

.empty-detail {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
```

Remove the `@keyframes slide-in` block entirely — the Svelte `fly` transition replaces it.

Also update `.meeting-list-panel.has-detail` (lines 395-400) — the `has-detail` class should still be applied when `selectedMeetingId` is set, no change needed there.

**Step 4: Test manually**

- Select a meeting: detail slides in from the left, list panel shrinks smoothly
- Switch meetings: detail content slides in again
- Deselect: detail area collapses smoothly

**Step 5: Commit**

```
feat: smooth split layout with slide-in meeting detail
```

---

### Task 4: EventPopover — fade + scale animation

**Files:**
- Modify: `src/lib/components/calendar/EventPopover.svelte` (lines 1-10 imports, lines 109-125 root div)

**Step 1: Add imports**

```typescript
import { scale, fade } from "svelte/transition";
import { reducedMotion, motionParams } from "../../reduced-motion";
```

**Step 2: Add transition to the popover root div**

On the root `<div>` (line 109), add the transition. The `transform-origin` is set via style to the anchor point:

```svelte
<div
  bind:this={popoverEl}
  in:scale={motionParams({ start: 0.9, duration: 150, easing: cubicOut }, $reducedMotion)}
  out:scale={motionParams({ start: 0.95, duration: 100 }, $reducedMotion)}
  style="
    position: fixed;
    top: {top}px;
    left: {left}px;
    min-width: 300px;
    max-width: 380px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 18px;
    z-index: 1000;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    font-family: 'DM Sans', sans-serif;
    transform-origin: {anchorRect.left < window.innerWidth / 2 ? 'top left' : 'top right'};
  "
>
```

Also add easing import:

```typescript
import { cubicOut } from "svelte/easing";
```

**Step 3: Ensure the parent conditionally renders with `{#if}`**

Check that `EventPopover` is rendered inside an `{#if}` block in `Calendar.svelte` so the out-transition fires. It should already be — the popover only exists when `popoverEvent` is set.

**Step 4: Test manually**

Click a calendar event — popover should scale up smoothly from the click point. Click away — it should scale down slightly and fade.

**Step 5: Commit**

```
feat: add fade+scale animation to calendar event popover
```

---

### Task 5: EventSidePanel — exit animation + z-index fix

**Files:**
- Modify: `src/lib/components/calendar/EventSidePanel.svelte` (lines 309-341 styles + root template)

**Step 1: Add imports**

```typescript
import { fly, fade } from "svelte/transition";
import { reducedMotion, motionParams } from "../../reduced-motion";
```

**Step 2: Replace CSS animation with Svelte transitions on the template**

The component's root has a backdrop div and a side-panel div. Add transitions to each:

On the backdrop div, add: `transition:fade={motionParams({ duration: 150 }, $reducedMotion)}`

On the side-panel div, add: `transition:fly={motionParams({ x: 400, duration: 200 }, $reducedMotion)}`

**Step 3: Update CSS — remove keyframe, fix z-index**

In `<style>`:

```css
.backdrop {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.3);
  z-index: 40;
}

.side-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: 400px;
  height: 100%;
  background: var(--surface);
  border-left: 1px solid var(--border);
  z-index: 41;
  font-family: 'DM Sans', sans-serif;
}
```

Remove the `@keyframes slide-in` block and the `animation:` property from `.side-panel`.

**Step 4: Test manually**

Open a side panel — should slide in from right with backdrop fading in. Close it — panel slides out, backdrop fades. The title bar should remain visible above the panel.

**Step 5: Commit**

```
feat: add exit animation to EventSidePanel, fix z-index layering
```

---

### Task 6: Meeting list stagger — initial load only

**Files:**
- Modify: `src/lib/components/MeetingList.svelte` (lines 1-10 imports, around line 158)

**Step 1: Add reduced-motion imports and initial-load flag**

```typescript
import { reducedMotion, motionParams } from "../reduced-motion";
import { onMount } from "svelte";

let initialLoad = $state(true);

onMount(() => {
  // Flip after first render so subsequent re-renders skip the stagger
  requestAnimationFrame(() => {
    initialLoad = false;
  });
});
```

**Step 2: Update the transition on line 158**

Replace:
```svelte
<div transition:fly={{ y: 10, duration: 200, delay: i * 30 }}>
```

With:
```svelte
<div
  in:fly={initialLoad
    ? motionParams({ y: 20, duration: 250, delay: Math.min(i, 10) * 50 }, $reducedMotion)
    : { duration: 0 }}
>
```

Note: use `in:fly` instead of `transition:fly` so the out-transition doesn't fire (we don't want meetings to animate out when filtering).

**Step 3: Test manually**

- Navigate to Meetings tab: rows should stagger in visibly
- Type in search: results should appear instantly (no stagger)
- Change filters: no stagger

**Step 4: Commit**

```
feat: meeting list stagger on initial load only
```

---

### Task 7: Toast exit animation

**Files:**
- Modify: `src/lib/components/ToastContainer.svelte` (line 27)

**Step 1: Add reduced-motion import**

```typescript
import { reducedMotion, motionParams } from "../reduced-motion";
```

**Step 2: Split the transition into in/out**

Replace line 27:
```svelte
transition:fly={{ x: 100, duration: 300 }}
```

With:
```svelte
in:fly={motionParams({ x: 100, duration: 300 }, $reducedMotion)}
out:fly={motionParams({ x: 100, duration: 200 }, $reducedMotion)}
```

The `transition:fly` should already work for both enter and exit since Svelte 5 handles keyed each blocks properly. But splitting to `in:/out:` gives us faster exit (200ms vs 300ms).

**Step 3: Test manually**

Trigger a toast (e.g. copy something). Watch it slide in from the right. Click dismiss — it should slide out to the right (200ms, faster than entry).

**Step 4: Commit**

```
feat: add toast exit animation
```

---

### Task 8: Graph sidebar exit animation

**Files:**
- Modify: `src/lib/components/GraphSidebar.svelte` (lines 151-173 styles, root div)
- Modify: `src/routes/GraphView.svelte` (lines 694-700, where GraphSidebar is rendered)

**Step 1: Move the transition from CSS to Svelte**

In `GraphView.svelte`, wrap the `GraphSidebar` in a transition:

```svelte
{#if sidebarNode}
  <div transition:fly={motionParams({ x: 340, duration: 200 }, $reducedMotion)}>
    <GraphSidebar ... />
  </div>
{/if}
```

Add imports to GraphView.svelte:
```typescript
import { fly } from "svelte/transition";
import { reducedMotion, motionParams } from "../lib/reduced-motion";
```

**Step 2: Remove CSS animation from GraphSidebar.svelte**

In the `<style>` block, remove `animation: sidebar-slide-in 200ms ease;` from `.graph-sidebar` and delete the `@keyframes sidebar-slide-in` block.

**Step 3: Test manually**

Click a node in the graph — sidebar slides in from the right. Click close or another node — sidebar slides back out.

**Step 4: Commit**

```
feat: add graph sidebar exit animation
```

---

### Task 9: Error/success banner animations

**Files:**
- Modify: `src/routes/Calendar.svelte` (around line 284, error banner)
- Modify: `src/lib/components/TodoistSettings.svelte` (lines 87-92, sync error/result)
- Modify: `src/lib/components/ParticipantPopover.svelte` (around line 215, "Copied!" text)

**Step 1: Calendar error banner — add slide transition**

In `Calendar.svelte`, add import:
```typescript
import { slide } from "svelte/transition";
import { reducedMotion, motionParams } from "../lib/reduced-motion";
```

On the error banner div (line 286), add:
```svelte
transition:slide={motionParams({ duration: 200 }, $reducedMotion)}
```

**Step 2: Todoist sync messages — add slide transition**

In `TodoistSettings.svelte`, add import:
```typescript
import { slide } from "svelte/transition";
import { reducedMotion, motionParams } from "../reduced-motion";
```

On the error `<p>` (line 87) and success `<p>` (line 90), add:
```svelte
transition:slide={motionParams({ duration: 200 }, $reducedMotion)}
```

**Step 3: "Copied!" tooltip — add fade transition**

In `ParticipantPopover.svelte`, add import:
```typescript
import { fade } from "svelte/transition";
import { reducedMotion, motionParams } from "../../reduced-motion";
```

On the "Copied!" span (line 215), add:
```svelte
transition:fade={motionParams({ duration: 100 }, $reducedMotion)}
```

**Step 4: Test manually**

- Calendar: trigger a sync error → banner should slide down. Dismiss → slides up.
- Todoist: trigger sync → success/error message slides in.
- Participant popover: copy an email → "Copied!" fades in.

**Step 5: Commit**

```
feat: animate error banners and copied tooltip
```

---

### Task 10: Final cleanup and verification

**Files:**
- All modified files from tasks 1-9

**Step 1: Verify `prefers-reduced-motion` works**

In browser DevTools, emulate reduced motion (Rendering tab → "Emulate CSS media feature prefers-reduced-motion"). Navigate the app — all animations should be instant.

**Step 2: Verify no regressions**

- Page transitions: slide correctly in both directions
- Dashboard: split layout smooth, no layout jump
- Calendar: popover scales, side panel slides in/out, stays below nav
- Meeting list: stagger on first load only
- Toasts: enter and exit both animated
- Graph sidebar: slides in/out
- Error banners: slide in/out

**Step 3: Remove leftover mockup files if any remain**

```bash
rm -f docs/mockups/calendar-assembly-*.html docs/mockups/popover-animation-comparison.html
```

**Step 4: Run dev build to check for errors**

```bash
npm run dev
```

**Step 5: Commit**

```
chore: animation cleanup and verification
```
