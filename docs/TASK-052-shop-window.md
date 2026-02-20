# TASK-052: Shop Window — Scene Compositor + Character State Display

**Depends on:** TASK-050 (budget API for energy bar + state data)  
**Blocked by:** Nothing (can start asset pipeline immediately)  
**Priority:** High — this is the public face of The Shopkeeper

---

## Overview

Build the public-facing shop window page. Visitors see her in the shop, see what she's doing, and can enter to talk. The page is a live viewport into her ALIVE state — not a static landing page.

---

## A. Scene Compositor (3-Layer Canvas)

### Canvas
- 1440×900 viewport, responsive via CSS `aspect-ratio: 16/10`
- Scales down on mobile, never crops

### Layer Stack

| Layer | Asset | Behavior |
|-------|-------|----------|
| 0 | `shop_back.png` | Static background, never changes |
| 1 | Character sprite | Swapped based on ALIVE state (see Section B) |
| 2 | `counter_foreground.png` | Foreground occlusion — counter sits IN FRONT of her lower body |
| 3 | CSS vignette | Radial gradient overlay, subtle darkening at edges |
| 4 | CSS dust particles | `<canvas>` element, 35 particles, color `rgba(255,210,150)`, slow upward drift, `requestAnimationFrame` |

### Character Position (locked at 1440×900)
- x: 594px, y: 213px
- Scale: 55% of canvas height (495px tall)
- Color grade: red boost 1.05, blue reduce 0.92 (CSS filter)
- Drop shadow: offset (5,5), opacity 0.3, blur 6px

### Counter Foreground Generation
Script `scripts/slice_counter.py`:
- Load `shop_back.png`
- Make everything above y=72% (648px) transparent
- Apply 6px fade zone at the cut edge
- Save as RGBA PNG

### Responsive Rules
- All positions as percentages of viewport (594/1440 = 41.25%, 213/900 = 23.67%)
- No layout shift on sprite swap
- Dust particles capped at 35, no performance impact

---

## B. Character State Display

### 7 Sprites → 7 States

| File | State ID | Expression | Triggers |
|------|----------|------------|----------|
| `char-1-cropped.png` | `engaged` | Smiling, welcoming | In conversation, social_hunger satisfied |
| `char-2-cropped.png` | `tired` | Eyes down, contemplative | Energy < 30%, late night cycles |
| `char-3-cropped.png` | `thinking` | Hand on glasses, looking up | Processing, **default idle fallback** |
| `char-4-cropped.png` | `curious` | Neutral, slight head tilt | Visitor arrives, social_hunger high |
| `char-5-cropped.png` | `surprised` | Mouth open, wide eyes | Unexpected event, rare discovery |
| `char-6-cropped.png` | `focused` | Warm lean, direct gaze | Writing, journaling, reading, arranging |
| `char-7-cropped.png` | `sleeping` | TBD (eyes closed) | Sleep mode active |

### State Resolution Priority
```
1. sleeping   → sleep mode active
2. surprised  → unexpected_event flag (rare, brief)
3. tired      → energy < 30% (budget < $0.60 of $2.00)
4. engaged    → has_visitor AND in_conversation
5. curious    → visitor_just_arrived OR social_hunger > 0.7
6. focused    → last_action in [write_journal, express_thought, read_content]
7. thinking   → default fallback
```

### Sprite Transition
- CSS crossfade: opacity 0 → 1 over 0.5s
- Old sprite fades out while new fades in (both rendered briefly during transition)
- No position change during swap

### State Resolver (frontend)
```typescript
type SpriteState = 'sleeping' | 'surprised' | 'tired' | 'engaged' | 'curious' | 'focused' | 'thinking';

interface AliveDisplayState {
  is_sleeping: boolean;
  has_visitor: boolean;
  in_conversation: boolean;
  budget_remaining: number;
  budget_total: number;
  social_hunger: number;
  last_action: string;
  surprise_flag: boolean;
}

function resolveSprite(state: AliveDisplayState): SpriteState {
  if (state.is_sleeping) return 'sleeping';
  if (state.surprise_flag) return 'surprised';
  if (state.budget_remaining / state.budget_total < 0.30) return 'tired';
  if (state.has_visitor && state.in_conversation) return 'engaged';
  if (state.has_visitor || state.social_hunger > 0.7) return 'curious';
  if (['write_journal', 'express_thought', 'read_content'].includes(state.last_action)) return 'focused';
  return 'thinking';
}
```

---

## C. Frontend Layout — Info Panel

Alongside (or below on mobile) the scene canvas, display:

### 1. Energy Bar
- **$2 budget = 200 energy** displayed to visitors (abstracted, not raw dollars)
- Visual bar that drains as she acts, fills on sleep reset
- Source: `budget_remaining / budget_total * 200`
- Color: green > 50%, yellow 20-50%, red < 20%

### 2. Recent Actions
- Feed showing last 5-10 actions
- Each shows energy cost: "Wrote in journal · 1.2 energy"
- Energy cost = `action_cost_usd / budget_total * 200` (converted to energy units)
- Timestamp relative ("3 min ago")

### 3. Recent Thoughts
- Latest 3-5 cortex monologue snippets
- Truncated to ~100 chars with expand option
- Updated each cycle

### 4. Train of Thought
- Renamed from "Threads" (visitor-facing terminology)
- Show current open train + 3 most recent closed ones
- Each shows title and brief summary

### 5. City + Time + Weather
- "Tokyo" (static)
- Live clock in JST
- Current weather (icon + temp) — fetch from weather API or static per-hour

### 6. Her State
- Text label: "Sleeping...", "Sitting quietly...", "Writing in her journal...", "Talking with a visitor..."
- Derived from same state resolver data
- Updates with each poll/push

### 7. CTA: Enter the Shop
- Prominent button
- Opens conversation interface (existing visitor chat)
- Disabled during sleep mode with tooltip "She's sleeping... come back later"

---

## D. Data Pipeline

### Backend API Endpoint
`GET /api/display-state`

Returns:
```json
{
  "is_sleeping": false,
  "has_visitor": false,
  "in_conversation": false,
  "budget_remaining": 1.37,
  "budget_total": 2.00,
  "social_hunger": 0.42,
  "last_action": "express_thought",
  "surprise_flag": false,
  "state_label": "Sitting quietly...",
  "recent_actions": [
    {"action": "express_thought", "cost_usd": 0.012, "timestamp": "2026-02-17T14:30:00Z", "summary": "Thinking about preservation"},
    {"action": "write_journal", "cost_usd": 0.014, "timestamp": "2026-02-17T14:25:00Z", "summary": "Entry about broken things"}
  ],
  "recent_thoughts": [
    {"text": "Museums hold broken things and call them whole...", "timestamp": "2026-02-17T14:30:00Z"}
  ],
  "trains_of_thought": [
    {"title": "porous vs. contained", "status": "open", "summary": "Where does the shop end and the world begin?"},
    {"title": "what closing means", "status": "closed", "summary": "Not shutting out — gathering in"}
  ],
  "current_time": "2026-02-17T23:30:00+09:00",
  "location": "Tokyo"
}
```

### Polling
- Frontend polls `/api/display-state` every 10 seconds
- Or WebSocket push if already available from visitor chat system
- Sprite state resolved client-side from this data

---

## E. Asset Pipeline

### File Locations
```
public/assets/
├── shop_back.png              # Background
├── counter_foreground.png     # Generated by slice_counter.py
└── sprites/
    ├── char-1-cropped.png     # engaged
    ├── char-2-cropped.png     # tired
    ├── char-3-cropped.png     # thinking
    ├── char-4-cropped.png     # curious
    ├── char-5-cropped.png     # surprised
    ├── char-6-cropped.png     # focused
    └── char-7-cropped.png     # sleeping (TBD)
```

### Preloading
- All 7 sprites preloaded on page load (they're small PNGs)
- Prevents flash on first state transition

---

## F. Quality Checks

- [ ] Viewport responsive, no crop on mobile
- [ ] Sprite swap: no layout shift, smooth crossfade
- [ ] Counter foreground perfectly occludes sprite lower body
- [ ] Dust particles: <35, requestAnimationFrame, no jank
- [ ] Energy bar updates in real-time with correct conversion
- [ ] Recent actions show correct energy costs
- [ ] State label matches sprite shown
- [ ] "Enter the Shop" disabled during sleep with clear messaging
- [ ] All z-indexes explicit and documented
- [ ] Works on Chrome, Safari, Firefox

---

## Files to Create/Modify

### New
- `scripts/slice_counter.py` — counter foreground generator
- `window/components/SceneCanvas.tsx` — scene compositor
- `window/lib/spriteResolver.ts` — state → sprite mapping
- `window/components/InfoPanel.tsx` — sidebar with energy, actions, thoughts, trains
- `api/display_state.py` (or route in existing API) — display state endpoint

### Modify
- `window/` page layout — integrate SceneCanvas + InfoPanel
- `api/dashboard_routes.py` — add display-state endpoint if not separate

### Assets
- 6 sprite PNGs (provided, char-1 through char-6)
- char-7 sleeping sprite (TBD)
- shop_back.png (existing)
- counter_foreground.png (generated)

---

## Definition of Done

- Scene compositor renders all 4 layers correctly at any viewport size
- Character sprite changes within 10s of state change in ALIVE pipeline
- Crossfade transition smooth (0.5s, no flash)
- Energy bar shows correct value, drains visibly during active period
- Recent actions feed updates with energy cost per action
- Train of thought shows current + recent closed
- "Enter the Shop" opens visitor chat
- Sleep mode: sleeping sprite, disabled CTA, energy bar full on wake
- Page loads in <2s, dust particles don't impact scroll performance
