# TASK-058: Production Visitor UI — Full Redesign (v2)

## Overview

Replace the current `window/` Next.js app with a production visitor experience. The concept is "Through the Glass" — a living scene of a Tokyo antique shop. She's inside, living her life. Visitors watch and chat like a livestream.

**This is NOT a 1:1 chatbot.** It's a livestream. Multiple visitors are in the shop at once. She reads chat when she wants, replies to whoever she wants (or no one), and tags people by name. Visitors see each other's messages. She's the streamer, they're the audience.

---

## Core Decisions

| Decision | Answer |
|---|---|
| Access model | **Open.** No tokens. Anyone can visit, pick a name, and chat. |
| Chat model | **Livestream.** All visitors share one chat. She sees all, replies selectively, tags by name. |
| Visitor identity | **Self-chosen name** on entry. No accounts. |
| Rate limiting | **None.** Sensorium buffers everything, she picks what to attend to. She can miss messages. Like a real streamer. |
| Chat history | **Scrollable, since she woke up.** New visitors see the full session. |
| Item display | **Dedicated panel slides in from the side.** |
| Visitor gifts | **URL input.** Visitors can send her links (articles, music, images). Goes to her inbox. |
| Outdoor scenery | **Real Tokyo feed** (webcam/photo, live). |
| Character sprites | **Generated on the fly.** Not a fixed sprite sheet. New pose combos get generated and cached. |

---

## Tech Stack

- **Next.js 14+** (App Router, TypeScript)
- **Tailwind CSS** + CSS custom properties for visual tuning
- **WebSocket** (native browser API) — broadcast room, not private channels
- **Canvas** for dust particles and optional compositing

---

## The Five Compositing Layers

Back to front:

```
┌─────────────────────────────────────────────────┐
│ 1. OUTDOOR SCENERY (real Tokyo feed)            │  ← Live/dynamic
│   ┌─────────────────────────────────────────┐   │
│   │ 2. SHOP INTERIOR (fixed PNG)            │   │  ← Static frame
│   │   ┌─────────────────────────────────┐   │   │
│   │   │ 3. SHELF ITEMS (dynamic sprites)│   │   │  ← Positions from DB
│   │   └─────────────────────────────────┘   │   │
│   │                                         │   │
│   │        4. CHARACTER (generated)         │   │  ← Expression + pose + mood
│   │                                         │   │
│   │   ┌─────────────────────────────────┐   │   │
│   │   │ 5. COUNTER (fixed PNG)          │   │   │  ← In front of her
│   │   └─────────────────────────────────┘   │   │
│   └─────────────────────────────────────────┘   │
│   + Dust particles + Glass reflection + UI      │
└─────────────────────────────────────────────────┘
```

### Layer 1: Outdoor Scenery (Real Tokyo)

The background visible through the shop window shows real Tokyo — live or near-live.

**Options (in order of feasibility):**

**A) YouTube live stream embed (fastest to ship)**
- Multiple 24/7 Tokyo live cams exist on YouTube
- Embed as a muted background video behind the shop interior
- The shop interior PNG has a transparent "window" area where the feed shows through
- Pros: zero infrastructure, always live, multiple angles available
- Cons: YouTube branding, potential stream downtime, no API control

**B) Webcam snapshot API**
- Services like Windy.com, webcamstravel.com expose Tokyo camera APIs
- Fetch a still image every 5-10 minutes
- Crossfade between snapshots
- Pros: clean, no video embed, controllable
- Cons: API limits, image quality varies

**C) Weather-mapped photo library (fallback)**
- Curated set: Tokyo × (morning/afternoon/evening/night) × (clear/rain/overcast/snow)
- ~16-24 images total
- Use real Tokyo weather API to select the right one
- Pros: always works, best visual quality, no external dependency
- Cons: not truly "live"

**Recommended: Start with C (reliable), add A or B as enhancement.** The shop interior PNG masks most of the outdoor layer anyway — only a window/door opening shows it.

**Future: "Teleport" feature.** A visitor can invite her to their city. The outdoor layer swaps to that city's feed/photos. Her journal notes the change. This is a backend feature (city parameter in state), frontend just swaps the outdoor layer source.

### Layer 2: Shop Interior (Fixed)

Static PNG of the shop interior frame — walls, shelves (empty), ceiling, hanging plants, lantern fixtures. This has:
- A transparent window/door area (Layer 1 shows through)
- Empty shelf areas (Layer 3 fills in)
- A gap where the character stands (Layer 4)

**Asset needed:** Shop interior PNG with alpha channel for window and character areas.

### Layer 3: Shelf Items (Dynamic)

Individual item sprites positioned on the shelves. Positions come from the backend (`shelf_assignments` table).

```typescript
interface ShelfItem {
  id: string;
  sprite_url: string;
  x: number;          // % from left
  y: number;          // % from top
  width: number;      // px or % 
  height: number;
  name: string;       // For hover tooltip
  glow?: boolean;     // Highlight when she references it
}
```

When she rearranges items (`rearrange_shelf` action), the backend sends updated positions. Items crossfade/slide to new positions.

### Layer 4: Character (Generated On-the-fly)

**Not a fixed sprite sheet.** The ALIVE pipeline outputs a body state:

```json
{
  "posture": "leaning_forward",
  "gaze": "at_visitor",
  "gesture": "adjusting_glasses",
  "expression": "curious",
  "mood_color": "warm"
}
```

This combination is hashed into a sprite key (e.g., `leaning_forward-at_visitor-adjusting_glasses-curious`). 

**Sprite resolution:**
1. Check cache: does this combo's sprite already exist?
2. If yes → use it (instant)
3. If no → **generate it** (image gen pipeline), cache the result, use fallback sprite until ready

**Generation pipeline** (separate from this task, but the frontend must handle it):
- Backend generates the sprite (Stable Diffusion / Flux / LoRA fine-tuned on her character)
- Stores in `/assets/sprites/{hash}.png`
- Broadcasts the new sprite URL over WebSocket
- Frontend crossfades from fallback to new sprite

**Fallback logic:**
- Exact match → use it
- No match → find closest match (same expression, different pose) → use it
- Nothing close → use default "thinking" sprite

**For v1 launch:** Start with a fixed set of ~8-12 sprites mapped to the most common combos. The generation pipeline is a separate task. But the frontend architecture must support dynamic sprites from day one.

### Layer 5: Counter (Fixed)

Static PNG of the counter surface and front edge. Composited IN FRONT of the character, so she appears to be standing behind it. This creates depth.

**Asset needed:** Counter PNG with alpha channel (transparent above the counter surface).

---

## UI Layout

```
┌─────────────────────────────────────────────────────────────┐
│  The Shopkeeper    ● 3 watching · 😌 content · 6pm · rain  │  ← top bar
│                                                             │
│  ┌─ journal stream ────┐                                    │
│  │ …mono no aware.     │     [ SCENE VIEWPORT ]             │
│  │ The beauty of       │     BG + Shop + Items +            │
│  │ things passing.     │     Character + Counter             │
│  │                     │                                    │
│  │ adjusting lantern   │                                    │
│  └─────────────────────┘                                    │
│                                                             │
│  ┌─ threads ───────────────────┐  ┌─ energy ──────────┐    │
│  │ · Why do we name things?    │  │ ████████░░ 68%    │    │
│  │ · The weight of small gifts │  │                    │    │
│  └─────────────────────────────┘  └────────────────────┘    │
│                                                             │
│  ┌─ chat (livestream) ─────────────────────────────────┐    │
│  │ Yuki: What's the oldest thing in your shop?         │    │
│  │ Alex: I love the brass compass                      │    │
│  │ 🏷️ @Yuki: A camera from 1943. The lens is clouded  │    │
│  │ but it still clicks.                                │    │
│  │ Mika: Can I see it?                                 │    │
│  │                                                     │    │
│  │ [your name] type a message...              [send]   │    │
│  │ [📎 Send her a link]                                │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘

┌─ item panel (slides in from right when she shows an item) ──┐
│                                                              │
│  [large item image]                                          │
│                                                              │
│  Voigtländer Brilliant (1932)                                │
│  Twin-lens reflex. The viewfinder shows the world            │
│  upside down. I keep it because it reminds me that           │
│  perspective is a choice.                                    │
│                                                              │
│  Acquired: Day 12                                            │
│  Shown to: Yuki                                              │
│                                                    [close ×] │
└──────────────────────────────────────────────────────────────┘
```

### Mobile Layout

On mobile, the scene viewport takes the top ~50%, and the bottom half is tabbed:

```
┌──────────────────────────┐
│    [ SCENE VIEWPORT ]    │  ← top half
│    BG + character etc    │
│                          │
├──────────────────────────┤
│ [Chat] [Journal] [Info]  │  ← tab bar
├──────────────────────────┤
│                          │
│  Chat tab (default):     │
│  livestream chat         │
│                          │
│  Journal tab:            │
│  her thoughts stream     │
│                          │
│  Info tab:               │
│  mood, threads, energy,  │
│  music, visitor count    │
│                          │
│ [name] type...    [send] │
│ [📎 link]                │
└──────────────────────────┘
```

---

## Visitor Experience Flow

### 1. Arrival

- Page loads → loading screen (dark, breathing "…")
- Scene fades in (outdoor → shop → character)
- Chat is immediately visible and scrollable (history since she woke up)
- Name input at bottom: "Pick a name to enter the shop"

### 2. Entering

- Visitor types a name → enters chat
- System message in chat: "Yuki entered the shop"
- This creates a `visitor_arrived` event in her inbox
- She may or may not acknowledge them (her choice, next cycle)

### 3. Chatting

- Visitor types messages → broadcast to all connected clients + buffered in her inbox
- Her replies appear with a distinct visual style (her serif font, tagged with @visitor_name)
- She may reply to no one, one person, or multiple people in a single cycle
- Messages she hasn't read yet have no indicator — visitors don't know if she's read them

### 4. Receiving a Gift (URL)

- Visitor clicks "📎 Send her a link" → URL input
- URL is validated (basic format check) and sent
- Appears in chat: "Yuki shared a link: [title or URL]"
- Goes into her inbox as a `visitor_gift` event with URL metadata
- She may reference it later: "Yuki sent me something interesting..."

### 5. Seeing an Item

- When she executes `show_item` action targeting a visitor, the item panel slides in from the right
- Shows: large item image, her description of it, provenance
- All visitors see it (it's a public action), but it's addressed to one person
- Panel has a close button, auto-closes after 30 seconds or on next scene update

### 6. She Falls Asleep

- Scene darkens (CSS filter or swap to night/dark background variant)
- Character sprite fades out or switches to "shop dark" image
- Chat stays visible but input is replaced with: "She's sleeping. Come back later."
- Journal stream shows sleep reflections (dream-like, different styling)
- Energy bar shows "recharging"

### 7. Leaving

- Visitor closes tab → `visitor_left` event
- System message: "Yuki left the shop"
- No explicit "leave" button needed

---

## Components

```
app/
  layout.tsx                — Root layout, fonts, meta, OG tags
  page.tsx                  — Main window (full viewport)
  globals.css               — Tailwind + CSS custom properties

components/
  scene/
    SceneViewport.tsx       — Container for all 5 compositing layers
    OutdoorLayer.tsx        — Real Tokyo feed (video embed or photo)
    ShopInterior.tsx        — Fixed shop frame PNG
    ShelfItems.tsx          — Dynamic item sprites with positions
    CharacterSprite.tsx     — Expression/pose sprite with crossfade
    Counter.tsx             — Fixed counter PNG
    DustParticles.tsx       — Canvas particle system
    GlassOverlay.tsx        — CSS glass reflection + vignette

  chat/
    ChatPanel.tsx           — Livestream chat container
    ChatMessage.tsx         — Single message (visitor or shopkeeper)
    ChatInput.tsx           — Name entry → message input
    GiftLink.tsx            — URL submission UI
    SystemMessage.tsx       — "Yuki entered/left the shop"

  stream/
    JournalStream.tsx       — Her thoughts/journal (read-only)
    Fragment.tsx             — Individual thought/journal/action entry

  info/
    TopBar.tsx              — Title + status (visitor count, mood, time, weather)
    EnergyBar.tsx           — Visual energy remaining
    ThreadsList.tsx         — Active thinking threads
    MusicIndicator.tsx      — Currently listening to (if any)
    MoodLabel.tsx           — Current emotional state

  items/
    ItemPanel.tsx           — Slide-in item detail view
    ItemCard.tsx            — Item image + description + provenance

  ui/
    ConnectionPulse.tsx     — WebSocket status
    LoadingScreen.tsx       — Initial load
    MobileTabBar.tsx        — Chat/Journal/Info tabs (mobile only)
    NameEntry.tsx           — "Pick a name to enter"

hooks/
  useShopkeeperSocket.ts   — WebSocket: connect, reconnect, message routing
  useVisitors.ts           — Visitor list, presence tracking
  useExpression.ts         — Body output → sprite key mapping
  useChatHistory.ts        — Message buffer (since wake), scroll management
  useItemPanel.ts          — Item show/hide state
  useMediaQuery.ts         — Mobile vs desktop layout

lib/
  types.ts                 — All TypeScript interfaces
  config.ts                — URLs, timing constants
  sprite-resolver.ts       — Sprite key → URL resolution with fallback
```

---

## WebSocket Protocol

### Architecture

One broadcast room. All connected clients receive all messages. The server manages the room.

```
                    ┌─────────────┐
  Visitor A ──WS──▶ │             │ ──▶ Visitor A
  Visitor B ──WS──▶ │   Server    │ ──▶ Visitor B
  Visitor C ──WS──▶ │  (broadcast)│ ──▶ Visitor C
                    │             │
  ALIVE pipeline ──▶│             │  (scene updates, her replies)
                    └─────────────┘
```

### Server → Client Messages

```typescript
// Full state (on connect)
interface InitialState {
  type: "initial_state";
  scene: SceneState;
  character: CharacterState;
  visitors: VisitorInfo[];         // Who's currently here
  chat_history: ChatMessage[];     // Since she woke up
  energy: EnergyState;
  mood: MoodState;
  threads: ThreadInfo[];
  music: MusicState | null;
  items_on_shelf: ShelfItem[];
  status: "awake" | "sleeping" | "resting";
  weather: WeatherState;           // Real Tokyo weather
  time: string;                    // Real Tokyo time
}

// Scene update (per cycle)
interface SceneUpdate {
  type: "scene_update";
  character: CharacterState;
  energy: EnergyState;
  mood: MoodState;
  threads: ThreadInfo[];
  music: MusicState | null;
  items_on_shelf: ShelfItem[];     // Full list (positions may have changed)
  outdoor: OutdoorState;           // Weather/time update
}

interface CharacterState {
  sprite_url: string;              // Current sprite (or fallback)
  sprite_generating: boolean;      // True if new sprite is being generated
  expression: string;
  posture: string;
  gaze: string;
}

interface EnergyState {
  current: number;                 // 0.0 - 1.0
  max: number;
  status: "active" | "resting" | "recharging";
}

interface MoodState {
  label: string;                   // "content", "curious", "melancholic", "excited"
  valence: number;                 // -1.0 to 1.0
}

// Chat message (from visitor or from her)
interface ChatBroadcast {
  type: "chat_message";
  message: ChatMessage;
}

interface ChatMessage {
  id: string;
  from: "visitor" | "shopkeeper" | "system";
  visitor_name?: string;           // Who sent it (if visitor)
  target_name?: string;            // Who she's replying to (if shopkeeper)
  content: string;
  gift_url?: string;               // If this is a link gift
  timestamp: string;
}

// Her journal/thought (for the journal stream)
interface JournalFragment {
  type: "journal_fragment";
  content: string;
  fragment_type: "journal" | "thought" | "action" | "sleep_reflection";
  timestamp: string;
}

// Expression/sprite change (mid-cycle, without full scene update)
interface SpriteUpdate {
  type: "sprite_update";
  sprite_url: string;
  sprite_generating: boolean;
  expression: string;
}

// Item show (she wants to show an item)
interface ItemShow {
  type: "item_show";
  item: {
    id: string;
    name: string;
    image_url: string;
    description: string;           // Her words about it
    provenance?: string;           // How/when she got it
    shown_to: string;              // Visitor name
  };
}

// Visitor presence
interface VisitorPresence {
  type: "visitor_presence";
  action: "joined" | "left";
  name: string;
  visitor_count: number;           // Current total
}

// Status change (sleep/wake)
interface StatusChange {
  type: "status_change";
  status: "awake" | "sleeping" | "resting";
  message?: string;                // "She's fallen asleep." etc.
}

// Weather/time update (real Tokyo data, every ~10 min)
interface WeatherUpdate {
  type: "weather_update";
  weather: WeatherState;
  time: string;
  outdoor_image_url?: string;      // New outdoor layer image
}

interface WeatherState {
  condition: string;               // "rain", "clear", "cloudy", "snow"
  temperature_c: number;
  description: string;             // "Light rain, 12°C"
  is_night: boolean;
}
```

### Client → Server Messages

```typescript
// Set visitor name (on entry)
interface SetName {
  type: "set_name";
  name: string;
}

// Response: name accepted or rejected (duplicate, too long, etc.)
interface NameResult {
  type: "name_result";
  accepted: boolean;
  name: string;
  error?: string;                  // "name_taken", "too_long", "inappropriate"
}

// Chat message
interface SendMessage {
  type: "send_message";
  content: string;
}

// Gift URL
interface SendGift {
  type: "send_gift";
  url: string;
}
```

---

## State Management

React Context + useReducer.

```typescript
interface AppState {
  // Connection
  connected: boolean;
  visitorName: string | null;       // null = hasn't entered yet
  nameError: string | null;

  // Scene
  sceneLoaded: boolean;
  character: CharacterState;
  itemsOnShelf: ShelfItem[];
  outdoorImageUrl: string | null;

  // Status
  status: "awake" | "sleeping" | "resting";
  weather: WeatherState;
  time: string;                     // Real Tokyo time

  // Visitors
  visitors: VisitorInfo[];
  visitorCount: number;

  // Her state (visible to visitors)
  energy: EnergyState;
  mood: MoodState;
  threads: ThreadInfo[];
  music: MusicState | null;

  // Chat
  chatMessages: ChatMessage[];      // Since she woke up
  chatScrollLocked: boolean;        // Auto-scroll to bottom

  // Journal stream
  journalFragments: JournalFragment[];

  // Item panel
  shownItem: ItemShowData | null;   // Currently displayed item (or null)

  // Mobile
  activeTab: "chat" | "journal" | "info";
}
```

---

## Visual Tuning Guide

All values that need eyeball adjustment:

### Scene Positioning
```css
/* TUNE: Character sprite position (behind counter) */
--char-bottom: 14%;
--char-left: 50%;
--char-translate-x: -52%;
--char-width: 28%;
--char-max-width: 280px;
--char-min-width: 140px;

/* TUNE: Counter layer position (in front of character) */
--counter-bottom: 0;
--counter-width: 100%;

/* TUNE: Outdoor layer visible area (through shop window) */
--outdoor-clip-path: /* matches the window opening in shop interior PNG */
```

### Atmosphere
```css
/* TUNE: Glass reflection */
--vignette: inset 0 0 100px 30px rgba(0,0,0,0.35);
--reflection-opacity: 0.035;

/* TUNE: Scene overlays */
--top-gradient: linear-gradient(180deg, rgba(8,6,4,0.5) 0%, transparent 100%);
--bottom-gradient: linear-gradient(0deg, rgba(8,6,4,0.6) 0%, transparent 100%);
```

### Text & UI Opacity
```css
--text-thought: rgba(230,215,185, 0.55);
--text-journal: rgba(220,200,170, 0.70);
--text-action:  rgba(190,170,140, 0.38);
--text-speech:  rgba(240,225,195, 0.85);

--chat-visitor: rgba(185,180,170, 0.6);
--chat-shopkeeper: rgba(225,210,180, 0.85);
--chat-system: rgba(160,155,145, 0.3);
```

### Timing
```css
--sprite-crossfade: 900ms;
--scene-crossfade: 2000ms;
--fragment-in: 1000ms;
--item-panel-slide: 400ms;
--chat-message-in: 200ms;
```

### Energy Bar
```css
/* TUNE: Energy bar colors */
--energy-high: rgba(140,175,125, 0.6);     /* > 60% */
--energy-mid:  rgba(200,175,100, 0.6);     /* 30-60% */
--energy-low:  rgba(190,110,90, 0.6);      /* < 30% */
--energy-bg:   rgba(255,255,255, 0.06);
```

---

## Backend Changes Required

This spec is frontend-focused, but the following backend changes are needed:

### WebSocket (heartbeat_server.py)
- **Broadcast room** instead of single-client WebSocket
- **Visitor tracking**: name registry, presence events, connection count
- **Chat relay**: visitor messages → broadcast to all + buffer in inbox
- **Chat history**: keep messages since last wake event, serve on connect

### Pipeline (minimal changes)
- **Cortex prompt**: include visitor names so she can tag replies
- **Cortex output**: `target_name` field in speech output
- **Sensorium**: buffer all visitor messages as a batch, not individual events

### New Endpoints
- `GET /api/weather` — Real Tokyo weather (cache 10 min)
- `GET /api/outdoor` — Current outdoor layer image URL

### Assets
- Shop interior PNG (with alpha for window area)
- Counter PNG (with alpha above counter surface)
- Initial set of 8-12 character sprites for common expression/pose combos
- Item sprites for collection items

---

## What This Task Does NOT Include

- **Character sprite generation pipeline** — separate task. Frontend handles fallback gracefully.
- **Teleport feature** — future. Frontend just swaps outdoor layer source.
- **Operator dashboard** — unchanged, still at `/dashboard`
- **Backend broadcast room implementation** — needs its own task or sub-task
- **Item acquisition/trading** — she can show items, visitors can't buy yet

---

## Acceptance Criteria

1. Five compositing layers render correctly with depth ordering
2. Multiple visitors can connect simultaneously, see each other's messages
3. She replies with @name tags, displayed distinctly in chat
4. Energy bar reflects her current energy from backend
5. Mood, threads, music, visitor count visible in UI
6. Real Tokyo time + weather displayed (API integration)
7. Journal stream shows her thoughts independently of chat
8. Item panel slides in when she shows an item, closes on dismiss/timeout
9. Gift URL input sends links to her inbox
10. Chat history scrollable since last wake
11. Sleep state: darkened scene, no chat input, sleep reflections in journal
12. Mobile layout: scene top, tabbed bottom (chat/journal/info)
13. Name entry works, rejects duplicates
14. WebSocket reconnects automatically on disconnect
15. All visual positioning values in CSS custom properties for tuning
16. Works on mobile Safari + Android Chrome
