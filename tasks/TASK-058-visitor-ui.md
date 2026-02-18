# TASK-058: Production Visitor UI — Full Redesign

## Overview

Replace the current `window/` Next.js app with a production-ready visitor experience. The concept is "Through the Glass" — you're standing outside a Tokyo antique shop at night, peering through the window. She's inside, living her life. Sometimes she notices you.

**This is NOT a chatbot interface.** It's a living scene you observe. Chat is secondary, gated, and on her terms.

## Architecture

### Tech Stack
- **Next.js 14+** (App Router)
- **TypeScript**
- **Tailwind CSS** for utility classes + CSS custom properties for atmospheric values
- **No component library** — everything is custom
- **WebSocket** via native browser API (not socket.io)

### Compositing Layers (back to front)

The visual system composites multiple PNG layers into a single scene. In the current backend, `compositing.py` does this server-side and broadcasts via WebSocket. The frontend receives either:
- **Option A:** A pre-composited image URL (current behavior)
- **Option B:** Individual layer URLs + positions for client-side canvas compositing

For v1, use **Option A** (pre-composited image from backend). The frontend just displays the image with crossfade transitions between states.

For character sprites specifically, composite client-side so expression changes don't require a full backend render:

```
Z-order (back to front):
1. Background scene image (from backend, covers full viewport)
2. Character sprite (client-side, positioned over the scene)
3. Dust particles (canvas overlay)
4. Glass reflection (CSS overlay)
5. UI elements (title, stream, chat)
```

### Assets

Character sprites are pre-generated PNGs with transparent backgrounds. They show the shopkeeper from roughly waist-up, behind the counter. Current set:

| Expression key | Description | Mapped from ALIVE body output |
|---|---|---|
| `smiling` | Warm smile, leaning slightly forward | `engaged`, `speaking`, `welcoming` |
| `thinking` | Looking down/away, contemplative | `idle`, `reading`, `reflecting`, `writing` |
| `curious` | Head tilted, looking at viewer | `curious`, `examining`, `listening` |
| `surprised` | Eyes wide, mouth slightly open | `startled`, `visitor_noticed` |

More expressions will be added. The system must handle unknown expression keys gracefully (fall back to `thinking`).

The background scene image includes the shop interior (shelves, lantern, plants, counter). Character sprite is composited on top of this.

**Shelf items** will be added later as individual sprites with x/y positions from the backend. Design the system to accommodate this — leave room in the compositing pipeline.

---

## Design Intent

### Atmosphere
- Dark, warm, nighttime Tokyo. Think: walking past a quiet shop on a side street in Daikanyama.
- Color palette: deep browns (#0d0b09, #12100c), warm amber accents, desaturated golds.
- Everything is low opacity and muted. You're peering through glass into a dimly lit space.

### Typography
- **Her voice:** A literary serif — something like Cormorant Garamond, EB Garamond, or Noto Serif JP. Warm, slightly old-fashioned.
- **System UI:** A clean sans — DM Sans, or similar. Small, high letter-spacing, uppercase for labels. Nearly invisible.
- **Japanese accent:** Noto Serif JP for the location label (代官山). Very light weight.

### The Three States

**1. AWAKE — Watching (default)**
- Full scene visible: background + character + atmosphere
- Activity stream at bottom: her thoughts, journal entries, actions drift in
- Status bar: time of day, weather, connection pulse
- "Enter the shop →" appears after ~10 seconds of watching (time-delayed)
- She may change expressions based on her internal state

**2. AWAKE — Inside (token-authenticated)**
- Chat panel slides up from bottom (covers bottom ~45% of screen)
- Scene still visible above the chat panel
- Her responses appear in both the chat panel and the activity stream
- Her expression responds to conversation (curious when you speak, smiling when she responds)
- Other window viewers (non-authenticated) can see the conversation happening in the stream

**3. SLEEPING**
- Scene shifts darker — either a dimmed/blue-tinted version of the background, or a separate sleep background
- Character sprite hidden or replaced with a "dark shop" image
- Activity stream shows sleep reflections (dream-like, italicized)
- No "Enter the shop" button — you can't enter while she sleeps
- Status shows "asleep"

---

## Components

### `app/page.tsx` — Main Window

The single public page. Full viewport, no scroll.

```
┌─────────────────────────────────────────────┐
│ The Shopkeeper          ● late afternoon · rain │  ← top bar (gradient overlay)
│                                                 │
│                                                 │
│              [  Scene + Character  ]            │  ← background + sprite
│              [  Dust particles     ]            │  ← canvas overlay
│              [  Glass reflection   ]            │  ← CSS overlay
│                                                 │
│                                                 │
│  ┌─ activity stream ──────────────────────┐    │
│  │ …I wonder what it felt like to         │    │  ← floating fragments
│  │ give a name to something that          │    │
│  │ disappears.                            │    │
│  │                                        │    │
│  │ rearranging the front display          │    │
│  └────────────────────────────────────────┘    │
│                                                 │
│  [ Enter the shop → ]                           │  ← appears after delay
│  代官山                                    ALIVE │  ← bottom bar
└─────────────────────────────────────────────────┘
```

### Component Tree

```
app/
  layout.tsx              — Root layout, fonts, meta tags, OG image
  page.tsx                — Main window page (full viewport)
  globals.css             — Tailwind + CSS custom properties

components/
  scene/
    SceneViewport.tsx     — Background image with crossfade transitions
    CharacterSprite.tsx   — Expression-based sprite with crossfade
    DustParticles.tsx     — Canvas particle system
    GlassOverlay.tsx      — CSS glass reflection + vignette
    SleepOverlay.tsx      — Dark overlay for sleep state

  stream/
    ActivityStream.tsx    — Container for floating text fragments
    Fragment.tsx          — Individual text fragment (thought/journal/action/speech)

  chat/
    ChatGate.tsx          — "Enter the shop" button (time-delayed appearance)
    ChatPanel.tsx         — Slide-up chat interface
    TokenAuth.tsx         — Token input gate
    ChatMessage.tsx       — Individual chat message bubble

  ui/
    TopBar.tsx            — Title + status indicators
    BottomBar.tsx         — Location label + ALIVE watermark
    ConnectionPulse.tsx   — WebSocket status indicator
    LoadingScreen.tsx     — Initial load (dark screen with breathing "…")

hooks/
  useShopkeeperSocket.ts  — WebSocket connection, reconnect, message parsing
  useExpression.ts        — Maps ALIVE body output to sprite key
  useDelayedReveal.ts     — Time-delayed element appearance
  useFragmentQueue.ts     — Manages the activity stream fragment buffer

lib/
  types.ts                — All TypeScript interfaces
  config.ts               — API URLs, WebSocket URL, timing constants
  auth.ts                 — Token validation client
```

---

## WebSocket Protocol

### Connection

```
URL: wss://{HOST}/ws/window
```

Reconnects automatically on disconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s). Shows disconnected state in ConnectionPulse.

### Server → Client Messages

```typescript
// Full state update (on connect + after each cycle)
interface SceneUpdate {
  type: "scene_update";
  scene: {
    image_url: string;        // Pre-composited background (or null if using layers)
    layers?: {                // Future: individual layers for client compositing
      background: string;
      shop: string;
      items: Array<{ sprite: string; x: number; y: number; w: number; h: number }>;
      foreground: string[];
    };
  };
  character: {
    expression: string;       // "thinking", "smiling", "curious", "surprised", etc.
    sprite_url: string;       // Direct URL to the character sprite PNG
    position?: {              // Optional override for sprite positioning
      x: number;              // % from left
      y: number;              // % from top
      scale: number;          // 1.0 = default
    };
  };
  text: {
    content: string;
    fragment_type: "journal" | "thought" | "action" | "speech" | "sleep_reflection";
  };
  state: {
    status: "awake" | "sleeping" | "resting";
    weather: string;          // "rain", "clear", "overcast", "snow"
    time_of_day: string;      // "morning", "afternoon", "evening", "night"
    visitor_present: boolean;
    active_threads: Array<{ id: string; title: string }>;
  };
  timestamp: string;
}

// Mid-cycle text fragment
interface TextFragment {
  type: "text_fragment";
  content: string;
  fragment_type: "journal" | "thought" | "action" | "speech" | "sleep_reflection";
  timestamp: string;
}

// Expression change (without full scene update)
interface ExpressionChange {
  type: "expression_change";
  expression: string;
  sprite_url: string;
}

// Status update
interface StatusUpdate {
  type: "status";
  status: "awake" | "sleeping" | "resting";
  message?: string;
}

// Chat response (when visitor is authenticated)
interface ChatResponse {
  type: "chat_response";
  content: string;
  expression: string;       // Her expression while responding
  timestamp: string;
}
```

### Client → Server Messages

```typescript
// Visitor chat message (requires valid token)
interface VisitorMessage {
  type: "visitor_message";
  token: string;
  content: string;
}

// Token validation
interface TokenValidate {
  type: "token_validate";
  token: string;
}

// Token validation response
interface TokenResult {
  type: "token_result";
  valid: boolean;
  display_name?: string;
  error?: string;           // "expired", "exhausted", "invalid"
}
```

### REST Endpoints (existing backend)

```
GET /api/state          — Current full state (for initial load before WS connects)
GET /api/og             — OG image (server-side composited scene for social preview)
POST /api/token/validate — Validate a chat token
```

---

## State Management

Use React Context + useReducer. No external state library needed.

```typescript
interface ShopkeeperState {
  // Connection
  connected: boolean;
  
  // Scene
  sceneImageUrl: string | null;
  expression: string;               // Current sprite expression key
  spriteUrl: string | null;
  
  // Status
  status: "awake" | "sleeping" | "resting";
  weather: string;
  timeOfDay: string;
  visitorPresent: boolean;
  
  // Activity stream
  fragments: Fragment[];             // Last N fragments (keep ~8 max)
  
  // Chat
  chatOpen: boolean;
  chatAuthenticated: boolean;
  chatDisplayName: string | null;
  chatMessages: ChatMessage[];
  
  // UI
  enterButtonVisible: boolean;       // Time-delayed
}
```

---

## Expression Mapping

The ALIVE pipeline outputs a `body` object from Cortex:

```json
{
  "posture": "leaning_forward",
  "gaze": "at_visitor",
  "gesture": "adjusting_glasses",
  "expression_hint": "curious"
}
```

The `useExpression` hook maps this to a sprite key:

```typescript
function mapToSprite(body: BodyOutput): string {
  // Priority: expression_hint > gaze > posture
  if (body.expression_hint && SPRITES[body.expression_hint]) {
    return body.expression_hint;
  }
  if (body.gaze === "at_visitor") return "curious";
  if (body.gaze === "down" || body.gaze === "away") return "thinking";
  if (body.posture === "leaning_forward") return "smiling";
  return "thinking"; // default
}
```

**Unknown expression keys fall back to "thinking".** As new sprites are added, update the mapping without changing the hook interface.

---

## Token Auth Flow

1. Visitor watches the shop (no auth required)
2. After delay, "Enter the shop →" appears
3. Click → token input slides in
4. Visitor enters token → sends `token_validate` over WebSocket
5. Server responds with `token_result`
6. If valid → chat panel opens, display_name shown
7. If invalid → subtle error state on input, can retry
8. Token stored in sessionStorage (not localStorage) for the session only

Tokens have optional `uses_remaining` and `expires_at`. The server handles all validation. The frontend just sends the token and shows the result.

---

## Visual Tuning Guide

All visual positioning values are collected here. These are the values you'll adjust by eye:

### Character Sprite Positioning
```css
/* TUNE: Character position relative to viewport */
--char-bottom: 14%;        /* Distance from bottom */
--char-left: 50%;          /* Horizontal center */
--char-translate-x: -52%;  /* Fine-tune horizontal offset */
--char-width: 28%;         /* Sprite width relative to viewport */
--char-max-width: 280px;   /* Max pixel width */
--char-min-width: 140px;   /* Min pixel width on mobile */
```

### Gradient Overlays
```css
/* TUNE: Top bar gradient (darkens top for title readability) */
--top-gradient: linear-gradient(180deg, rgba(8,6,4,0.55) 0%, rgba(8,6,4,0.2) 65%, transparent 100%);

/* TUNE: Bottom gradient (darkens bottom for stream readability) */
--bottom-gradient: linear-gradient(0deg, rgba(8,6,4,0.75) 0%, rgba(8,6,4,0.5) 45%, rgba(8,6,4,0.12) 85%, transparent 100%);
```

### Glass Effect
```css
/* TUNE: Vignette (window edge shadow) */
--vignette: inset 0 0 100px 30px rgba(0,0,0,0.35), inset 0 0 250px 60px rgba(0,0,0,0.15);

/* TUNE: Diagonal reflection streak */
--reflection-opacity: 0.035;
--reflection-angle: 152deg;
```

### Activity Stream
```css
/* TUNE: Max width of text stream */
--stream-max-width: 360px;

/* TUNE: Fragment fade mask (top edge fades out) */
--stream-mask: linear-gradient(to bottom, transparent 0%, black 25%, black 100%);
```

### Text Opacity (by fragment type)
```css
--text-thought: rgba(230,215,185, 0.55);    /* TUNE */
--text-journal: rgba(220,200,170, 0.70);    /* TUNE */
--text-action:  rgba(190,170,140, 0.38);    /* TUNE */
--text-speech:  rgba(240,225,195, 0.85);    /* TUNE */
--text-sleep:   rgba(140,150,180, 0.40);    /* TUNE */
```

### Timing
```css
--enter-button-delay: 10s;          /* TUNE: How long before "Enter" appears */
--sprite-crossfade: 900ms;          /* TUNE: Expression change transition */
--scene-crossfade: 2000ms;          /* TUNE: Background scene transition */
--fragment-animate-in: 1000ms;      /* TUNE: New text fragment entrance */
```

---

## Mobile Considerations

- **Full viewport, no scroll.** The window fills the screen.
- **Activity stream** takes up bottom ~30% of screen with gradient fade.
- **Chat panel** slides up to ~50% of screen height.
- **Character sprite** scales with viewport width (min 140px, max 280px).
- **Touch:** "Enter the shop" button is large enough to tap (minimum 44px touch target).
- **Orientation:** Portrait only for best experience. Landscape works but character gets cropped.
- **Safe areas:** Account for notch/home indicator on iOS (`env(safe-area-inset-bottom)`).

---

## OG / Social Preview

Meta tags for when the URL is shared:

```html
<meta property="og:title" content="The Shopkeeper" />
<meta property="og:description" content="A quiet shop in Tokyo. Someone is inside." />
<meta property="og:image" content="https://{HOST}/api/og" />
<meta property="og:type" content="website" />
<meta name="twitter:card" content="summary_large_image" />
```

The `/api/og` endpoint returns a server-side composited image (current scene state). Cached for 5 minutes.

---

## Performance

- **Background image:** Preload on mount. Show loading screen (dark with breathing "…") until loaded.
- **Sprite images:** Preload all expressions on mount so crossfades are instant.
- **WebSocket:** Connect immediately. Show disconnected state gracefully (connection pulse turns amber).
- **Fragments:** Keep max ~8 in the DOM. Older ones get removed (FIFO).
- **Particles:** Canvas-based, 20-25 particles max. Use requestAnimationFrame.
- **Fonts:** Preload the primary serif + sans-serif. Use `font-display: swap`.

---

## What This Task Does NOT Include

- **Operator dashboard** — remains as-is at `/dashboard`
- **Backend changes** — all WebSocket message types already exist or are trivial additions
- **Asset generation** — sprites, backgrounds, items are pre-made
- **Sleep background variant** — placeholder for now (dim the existing background with CSS)
- **Shelf item sprites** — future task, but the compositing pipeline should accommodate them

---

## Acceptance Criteria

1. Background scene displays full-bleed with character sprite composited on top
2. Expression changes produce smooth crossfade between sprites
3. Activity stream shows fragments from WebSocket in real-time
4. "Enter the shop" button appears after configurable delay
5. Token auth flow works (validate → open chat OR show error)
6. Chat panel slides up, messages send/receive over WebSocket
7. Sleep state changes UI appropriately (darker, no chat)
8. Connection loss shows visual indicator, auto-reconnects
9. OG meta tags render correct social preview
10. Works on mobile (iPhone Safari, Android Chrome)
11. All visual tuning values are in CSS custom properties or a single config object — easy to adjust by eye
