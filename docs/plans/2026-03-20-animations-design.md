# Animations & Transitions Design

## Principles

- **Snappy, not sluggish** — 150-250ms for most transitions, 350ms max for larger movements
- **Respect `prefers-reduced-motion`** — disable all non-essential animation when set to `reduce`
- **CSS transitions where possible** — Svelte `transition:` directives only for mount/unmount
- **No left-to-right staggering** — horizontal stagger feels unnatural in this layout

## Changes

### 1. Page transitions — directional slide

**Current:** 150ms fade via `{#key currentRoute}` + `transition:fade`. Causes jumpiness as old/new content briefly coexists.

**New:** Directional slide based on tab order (Calendar=0, Meetings=1, Graph=2, Settings=3). Navigating right slides content left and vice versa. Use Svelte `fly` with `x` direction determined by comparing old/new route index. Duration: 200ms with `cubic-bezier(0.16, 1, 0.3, 1)`.

The key change: use `in:fly` and `out:fly` separately (not `transition:`) so the outgoing view slides out while the incoming slides in from the opposite direction.

### 2. Dashboard split layout — slide-in detail panel

**Current:** Detail panel appears/disappears instantly, causing layout reflow. The flex container snaps between full-width list and split view.

**New:** Always render the split layout (list + detail area). When no meeting is selected, the detail area shows an empty state. When a meeting is selected, the detail content slides in from the left (200ms, ease-out). Switching between meetings also slides the new content in from the left. This eliminates the layout reflow entirely.

### 3. EventPopover — fade + scale

**Current:** No animation. Appears/disappears instantly.

**New:** On open: fade in + scale from 0.9 to 1.0, `transform-origin` set to the anchor point. Duration: 150ms, `cubic-bezier(0.16, 1, 0.3, 1)`. On close: fade out + scale to 0.95. Duration: 100ms, ease-out. Faster exit than entrance.

### 4. EventSidePanel — add exit animation, fix z-index

**Current:** Slide-in from right (CSS keyframe, 0.2s). No exit animation. Backdrop and panel overlay the nav bar.

**New:**
- **Exit:** Slide out to the right + backdrop fades out. Use Svelte `transition:fly={{ x: 400, duration: 200 }}` for the panel, `transition:fade={{ duration: 150 }}` for the backdrop.
- **Z-index fix:** Set backdrop and panel z-index below the title bar (title bar is ~z-index 50). Use z-index 40 for backdrop, 41 for panel. Alternatively, render the panel inside the main content area rather than as a fixed overlay on `<body>`.

### 5. Meeting list stagger — initial load only

**Current:** `transition:fly={{ y: 10, duration: 200, delay: i * 30 }}` on every render. Barely perceptible. Fires on filter/search changes too.

**New:** Increase to `y: 20, duration: 250, delay: i * 50` but only on initial mount. Track an `initialLoad` flag in the component — set it to `true` on mount, flip to `false` after the first render completes. When `initialLoad` is false, meetings appear instantly (no transition). Cap stagger at 10 items (delay: `Math.min(i, 10) * 50`) so long lists don't take forever.

### 6. Toast exit animation

**Current:** `transition:fly={{ x: 100, duration: 300 }}` on entrance only. Dismissal is instant.

**New:** The `transition:fly` directive already handles both in and out in Svelte — but the toast is likely being removed from the store array, which may bypass the out-transition. Ensure the toast element uses `out:fly={{ x: 100, duration: 200 }}` and that removal is deferred until the transition completes (use Svelte's `outroend` event or a short delay before store removal).

### 7. Graph sidebar exit animation

**Current:** `animation: sidebar-slide-in 200ms ease` (CSS keyframe). No exit animation.

**New:** Replace CSS keyframe with Svelte `transition:fly={{ x: 300, duration: 200 }}` so both entrance and exit are animated. The sidebar slides in from the right and slides back out on close.

### 8. Error/success banners

**Current:** Sync error banners and "Copied!" tooltips appear/disappear instantly.

**New:**
- **Error banners:** `transition:slide` (Svelte) for height animation on mount/unmount. Duration: 200ms.
- **"Copied!" tooltips:** Fade in (100ms), auto-dismiss with fade out (150ms) after 1.5s.

### 9. `prefers-reduced-motion` support

Add a global media query in `app.css`:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

This disables all CSS animations/transitions globally. For Svelte `transition:` directives, create a helper that returns `{ duration: 0 }` when reduced motion is preferred, and use it as the transition parameter.

## Out of scope

- Calendar assembly animation (decided against)
- Calendar event card stagger (instant render)
- Month view animations
- Button hover/press transitions (already handled globally in `app.css`)

## Easing reference

| Use case | Easing | Duration |
|----------|--------|----------|
| Page slides | `cubic-bezier(0.16, 1, 0.3, 1)` | 200ms |
| Popover scale | `cubic-bezier(0.16, 1, 0.3, 1)` | 150ms in, 100ms out |
| Panel slide | ease-out | 200ms |
| List item fly | ease | 250ms + stagger |
| Toast fly | ease | 300ms in, 200ms out |
| Fade (generic) | ease | 150ms |
| Button interactions | ease | 120-150ms (existing) |
