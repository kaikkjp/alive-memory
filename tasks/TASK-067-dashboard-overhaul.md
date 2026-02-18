# TASK-067: Dashboard Overhaul

**Priority: High — operator tool is unusable**

## Problem

The operator dashboard has critical usability issues that make it non-functional for monitoring the Shopkeeper's state. The page doesn't scroll, sections are cut off, tags overlap, and there may be data the system emits that the dashboard doesn't display.

## Fixes

### 1. Scrollable layout

The page must scroll. Most likely cause:
- CSS `overflow: hidden` on body or a container element
- Missing viewport meta tag
- Fixed-height container without scroll

Fix: ensure the page body scrolls naturally, and individual panels scroll if they have bounded height.

### 2. Behavioral section cut off

The behavioral section is partially visible — content is clipped. This is likely related to the scroll issue (#1) but may also be a panel-specific height constraint. Ensure the full section is visible when scrolled to.

### 3. Habit tags overlapping

Colored labels/tags for habits are overlapping each other — they need:
- Proper spacing (margin/gap between tags)
- Flex-wrap so they flow to the next line instead of overflowing
- Consistent sizing so labels don't collide

### 4. Visual hierarchy

The dashboard needs to be functional and scannable, not beautiful. Fixes:
- Clear section headers (larger font, bottom border, or background differentiation)
- Consistent spacing between sections
- Card-style containers for related data groups
- Readable font sizes (nothing below 12px)

### 5. Data completeness audit

Audit what data the system emits (via WebSocket and REST endpoints in `heartbeat_server.py`) versus what the dashboard actually displays. Flag any gaps where:
- Data is emitted but not shown
- Dashboard has a panel but no data source
- Data format mismatch (e.g., server sends array, dashboard expects object)

Document gaps as sub-tasks or inline TODO comments.

## Scope

**Files you may touch:**
- `window/` — dashboard HTML/CSS/JS (all dashboard-related files)
- `heartbeat_server.py` — data emission for dashboard endpoints

**Files you may NOT touch:**
- `pipeline/*`
- `db.py`
- `heartbeat.py`

## Approach

1. Fix scroll first (#1) — this unblocks visibility of all other issues
2. Fix tag layout (#3) — small CSS fix with high impact
3. Improve visual hierarchy (#4) — headers, spacing, cards
4. Verify behavioral section (#2) — likely resolved by #1
5. Data audit (#5) — compare server emission against dashboard consumption

## Verification

- Full page scrolls vertically
- All sections fully visible when scrolled to
- Habit tags readable with proper spacing, no overlaps
- All emitted data has a corresponding display element on the dashboard
- No horizontal overflow on any viewport width ≥ 1024px

## Definition of done

Dashboard is scrollable, all sections visible and readable, habit tags properly spaced, visual hierarchy is clear and scannable, all system-emitted data has a corresponding display element.
