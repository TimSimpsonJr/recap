# Phase 5a: Frontend Design Spec

## Design Direction

**Theme:** Warm Ink + Muted Gold — a dark mode design landing between Teams' polish and Obsidian's quiet focus.

**Character:** Warm, restrained, content-first. The app disappears; meetings are the star. Borderless cards use elevation (background shade) rather than borders for hierarchy. Muted golden indicators add warmth without demanding attention.

**Typography:** Source Serif 4 (serif) for headings/titles, DM Sans for body/UI text. The serif gives personality; the sans keeps UI elements crisp.

## Color Tokens

```css
/* ── Backgrounds ── */
--bg-base:       #1D1D1B;   /* app background */
--bg-surface:    #242422;   /* cards, elevated surfaces */
--bg-surface-hover: #2B2B28;
--bg-inset:      #282826;   /* search input, recessed areas */
--bg-overlay:    #1A1A18;   /* recording bar, overlays */

/* ── Text ── */
--text-primary:  #D8D5CE;   /* headings, titles */
--text-body:     #B0ADA5;   /* body text */
--text-muted:    #78756E;   /* metadata, secondary */
--text-faint:    #585650;   /* placeholders, date headers */

/* ── Accent ── */
--accent:        #A8A078;   /* primary accent (muted gold) */
--accent-hover:  #B8B088;

/* ── Semantic ── */
--status-done-bg:    rgba(160,150,120,0.12);
--status-done-text:  #A8A078;
--status-active-bg:  rgba(180,165,130,0.10);
--status-active-text:#B4A882;
--status-failed-bg:  rgba(200,80,60,0.10);
--status-failed-text:#D06850;

/* ── Borders & Shadows ── */
--border-subtle: #262624;   /* recording bar separator */
--shadow-card:   0 1px 8px rgba(0,0,0,0.25);

/* ── Recording Bar ── */
--rec-dot:       #ef4444;
--rec-bg:        #1A1A18;
--rec-border:    #262624;

/* ── Dots (metadata separators) ── */
--dot:           #464440;
```

## Typography

```css
/* ── Fonts ── */
--font-heading: 'Source Serif 4', serif;
--font-body:    'DM Sans', sans-serif;

/* ── Scale ── */
--text-title:    24px;      /* "Recap" app title */
--text-card:     16px;      /* meeting card titles */
--text-body:     15px;      /* search input, recording bar, general body */
--text-meta:     13.5px;    /* card metadata */
--text-badge:    12px;      /* status badges */
--text-section:  12px;      /* date section headers */
--text-link:     14px;      /* nav links, settings link */

/* ── Weights ── */
--weight-title:  700;
--weight-card:   600;
--weight-body:   400;
--weight-badge:  600;
--weight-section:600;
```

## Layout

```css
/* ── Spacing ── */
--content-padding: 28px;    /* horizontal padding */
--header-top:      24px;    /* top padding above title */
--search-top:      18px;    /* gap between header and search */
--list-top:        14px;    /* gap between search and list */
--card-padding:    14px 16px;
--card-gap:        4px;     /* between cards */
--card-radius:     8px;
--search-radius:   8px;
--badge-radius:    4px;
--badge-padding:   2px 8px;
--section-padding: 14px 0 6px;
--rec-bar-padding: 8px 28px;
```

## Component Behavior

**Cards:** No visible border. Background slightly lighter than base (`--bg-surface`). On hover: slightly lighter again + subtle shadow. Transition: 120ms ease.

**Search input:** No border. Inset background (`--bg-inset`). On focus: ring glow using accent at 20% opacity.

**Status badges:** Translucent background with matching text color. Small, pill-shaped. No border.

**Recording bar:** Darker than base (`--bg-overlay`). Thin bottom border. Red pulsing dot. Stop button uses accent color.

**Date section headers:** Uppercase, tracked, faint text. Acts as a visual separator without adding visual weight.

## Fonts Loading

Google Fonts import in `index.html` or `app.css`:
```
Source Serif 4: weights 300-900, optical size 8-60
DM Sans: weights 300-700, optical size 9-40
```

## Navigation

**Top nav bar** — horizontal bar at the top of the window:
- Left: "Recap" title (serif, 16px)
- Center: tab links — "Meetings" (list view), "Graph" (graph view), "Settings"
- Active tab: accent underline (2px bottom border)
- Height: 44px
- Background: `--bg-overlay` with bottom border `--border-subtle`
- Tab text: `--text-faint` default, `--accent` when active

```
┌─────────────────────────────────────────────────┐
│ Recap    Meetings  Graph  Settings              │
│          ────────                                │
└─────────────────────────────────────────────────┘
```

## Filter Sidebar

**Collapsible left sidebar** for filtering meetings, inspired by Obsidian's left panel:

- Toggle: small icon button at the top-left of the meeting list area. When collapsed, the sidebar is hidden and the meeting list takes full width.
- Width: ~200px when expanded
- Background: `--bg-overlay` with right border `--border-subtle`
- Sections: Company, Participants, Platform — each with a collapsible header and checkbox list
- Filter items auto-populated from scanned meeting data
- Active filters shown as small count badges next to section headers
- Clearing filters: "Clear all" link at the top of the sidebar

```
┌──────────┬──────────────────────────────┐
│ Filters  │ Search...                    │
│          │                              │
│ COMPANY  │ TODAY                        │
│ ☑ Acme   │ ┌──────────────────────────┐ │
│ ☐ Globex │ │ Project Kickoff...       │ │
│          │ └──────────────────────────┘ │
│ PLATFORM │                              │
│ ☑ Zoom   │ YESTERDAY                   │
│ ☐ Teams  │ ┌──────────────────────────┐ │
│          │ │ Business Review...        │ │
│ PEOPLE   │ └──────────────────────────┘ │
│ ☐ Jane   │                              │
│ ☐ Bob    │                              │
└──────────┴──────────────────────────────┘
```

## Graph View

**Obsidian-style force-directed graph** showing relationships between meetings, people, and companies.

- Accessible via the "Graph" tab in the top nav
- **Node types:**
  - Meeting nodes (primary, sized by duration or participant count)
  - People nodes (connected to meetings they attended)
  - Company nodes (connected to their people)
- **Edges:** Meeting → Person (attended), Person → Company (works at), Meeting → Meeting (shared participants, shown as thinner connection)
- **Interactions:** Hover to highlight connected nodes. Click a node to navigate (meeting → detail view, person → filtered list, company → filtered list).
- **Implementation:** Use a lightweight force-directed graph library (e.g., `d3-force` or `force-graph`). Start with a simple implementation; polish later.
- **Colors:** Meeting nodes use `--accent`, People nodes use `--text-muted`, Company nodes use `--status-done-text`. Edges use `--dot` color.

## Responsive Layout

The Tauri window defaults to 900x700 but is resizable. The layout adapts:

- **>= 900px:** Full layout with filter sidebar (when expanded) + meeting list
- **< 900px:** Filter sidebar auto-collapses. Meeting list takes full width. Search and filters accessible via toggle.
- **Detail view:** At narrow widths, player stacks above the tabbed content (no side-by-side). At wider widths, player could sit alongside transcript (future consideration).

## Dark Mode Only

This design is dark-mode only for Phase 5a. No light mode toggle. The Settings page will eventually be updated to match, but that's out of scope for this phase.
