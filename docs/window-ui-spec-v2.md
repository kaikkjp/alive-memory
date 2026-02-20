# THE WINDOW — UI Architecture Spec (v2)

## For: Claude Code
## Goal: A public live view of the shopkeeper's inner life — layered composited visuals, real-time updates, optional gated chat
## Prereq: Living Loop + Simulation Mode implemented and tested

---

## DESIGN PRINCIPLES

The window is the shopfront. People visit a URL and see a living scene: the shop, her posture, the weather outside, objects on the shelves. Text flows in — her current thought, a journal fragment, a thread she's carrying. The scene shifts every few minutes as her state changes.

**Not a chat interface.** Chat exists but is secondary — behind a gate. The primary experience is watching someone exist. Like looking through a shop window at night and seeing the owner reading alone.

**Not a dashboard.** No graphs, no status bars, no "mood: 0.7" readouts. Her state is expressed visually and through her own words. The viewer infers her mood from her posture and the text, not from a labeled metric.

**Layered compositing, not per-cycle generation.** The scene is assembled from a library of pre-generated layers: background, shop interior, shelf items, her sprite. New images are generated only when genuinely new visual states appear. Cost drops to near-zero after the first week. Latency is zero — composition is instant.

---

## PART 1: VISUAL LAYER SYSTEM

### 1.1 Architecture

The scene is a stack of composited layers:

```
┌──────────────────────────────────────┐
│  Layer 0: Background                 │  tokyo_rain_afternoon.png
│  ┌────────────────────────────────┐  │
│  │  Layer 1: Shop interior        │  │  shop_warm_day.png
│  │  ┌──────────────────────────┐  │  │
│  │  │  Layer 2: Shelf items    │  │  │  slot_3_camera.png, slot_7_book.png
│  │  └──────────────────────────┘  │  │
│  │  ┌──────────────────────────┐  │  │
│  │  │  Layer 3: Her (sprite)   │  │  │  reading_calm_apronA.png
│  │  └──────────────────────────┘  │  │
│  │  ┌──────────────────────────┐  │  │
│  │  │  Layer 4: Foreground     │  │  │  counter_top.png, window_rain.png
│  │  └──────────────────────────┘  │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

Each layer is a transparent PNG. Composited client-side via HTML5 Canvas (instant, no server work) with server-side PIL fallback for social previews / thumbnails.

### 1.2 Layer 0: Background (Through the Window)

What the street and sky look like outside.

**Dimensions:**

| Variable | Values | Count |
|----------|--------|-------|
| Location | tokyo (default) | 1 |
| Weather | clear, overcast, rain, snow, storm | 5 |
| Time of day | morning, afternoon, evening, night | 4 |

**Total: 20 backgrounds.**

**Naming:** `bg_{location}_{weather}_{time}.png`

```
bg_tokyo_clear_morning.png
bg_tokyo_clear_afternoon.png
bg_tokyo_clear_evening.png
bg_tokyo_clear_night.png
bg_tokyo_rain_morning.png
bg_tokyo_rain_afternoon.png
...
bg_tokyo_storm_night.png
```

**Generation:** All 20 generated at project start. Done permanently.

**Future expansion:** Add season (winter/spring/summer/autumn) = 80 backgrounds. Add new locations if she "travels." But 20 is enough to launch.

**Prompt template for batch generation:**

```
A view through a shop window in a quiet Tokyo side street. {time_of_day}, {weather}.
{time_detail}. {weather_detail}.
The view is from inside looking out — the window frame is visible at the edges.
Style: soft illustration, muted warm palette, Studio Ghibli atmosphere, slight grain, 16:9.
Consistent with a series — same street, same angle, different conditions.
```

Time/weather detail mappings:

```python
TIME_DETAIL = {
    'morning':   'Early light, long shadows on the narrow street. A few people walking.',
    'afternoon': 'Full daylight, warm. A bicycle parked against a wall.',
    'evening':   'Golden hour fading to blue. Shop signs beginning to glow.',
    'night':     'Dark street, puddles of light from vending machines and distant signs.',
}

WEATHER_DETAIL = {
    'clear':    'Clear sky. Sharp light.',
    'overcast': 'Grey sky, flat diffused light. Everything looks muted.',
    'rain':     'Rain streaks the glass. The street glistens. Umbrellas.',
    'snow':     'Snow falling gently. The street is hushed. White edges on everything.',
    'storm':    'Heavy rain. The street is empty. Water running along the curb.',
}
```

### 1.3 Layer 1: Shop Interior

The shop itself — shelves, counter, walls, lanterns, floor.

**Dimensions:**

| Variable | Values | Count |
|----------|--------|-------|
| Lighting | warm_day, soft_evening, dim_night, dark_sleep | 4 |

**Total: 4 shop images.**

**Naming:** `shop_{lighting}.png`

```
shop_warm_day.png
shop_soft_evening.png
shop_dim_night.png
shop_dark_sleep.png
```

Each image has:
- Transparent window area (Layer 0 shows through)
- Defined **shelf slot positions** where items appear (transparent in these areas)
- Defined **character anchor point** where her sprite goes
- Counter, lanterns, walls are opaque

**Lighting mapping (deterministic):**

```python
def get_shop_lighting(time_of_day: str, shop_status: str) -> str:
    if shop_status == 'closed':
        return 'dark_sleep'
    return {
        'morning':   'warm_day',
        'afternoon': 'warm_day',
        'evening':   'soft_evening',
        'night':     'dim_night',
    }[time_of_day]
```

**Generation:** All 4 generated once. The shop design is fixed — same shelves, same counter, same lanterns, same layout across all lighting conditions.

**Prompt template:**

```
Interior of a small, cluttered antique shop in Tokyo. Warm wooden shelves along the walls,
a wooden counter with a brass cash register, paper lanterns hanging from the ceiling.
Curious objects on shelves — old cameras, ceramic figures, brass instruments, glass bottles.
{lighting_description}.
The shop window is visible on the left wall (leave this area semi-transparent for compositing).
There are {slot_count} clearly visible empty spaces on the shelves where objects could be placed.
The counter area is clear for a character to stand/sit behind.
Style: soft illustration, muted warm palette, Studio Ghibli atmosphere, slight grain, 16:9.
Top-down slight angle, as if viewed from just inside the doorway.
```

### 1.4 Layer 2: Shelf Items (Collection Sprites)

Each object she collects becomes a small sprite placed at a fixed shelf position.

**Shelf slot map:**

```python
SHELF_SLOTS = {
    # id: (x, y, width, height) — pixel coordinates in the shop layer
    'shelf_top_1':    (120, 180, 80, 80),
    'shelf_top_2':    (220, 180, 80, 80),
    'shelf_top_3':    (320, 180, 80, 80),
    'shelf_top_4':    (420, 180, 80, 80),
    'shelf_mid_1':    (120, 300, 80, 80),
    'shelf_mid_2':    (220, 300, 80, 80),
    'shelf_mid_3':    (320, 300, 80, 80),
    'shelf_mid_4':    (420, 300, 80, 80),
    'shelf_low_1':    (120, 420, 80, 80),
    'shelf_low_2':    (220, 420, 80, 80),
    'shelf_low_3':    (320, 420, 80, 80),
    'shelf_low_4':    (420, 420, 80, 80),
    'counter_left':   (100, 520, 100, 80),
    'counter_center': (300, 520, 100, 80),
    'counter_right':  (500, 520, 100, 80),
    'window_sill':    (50,  350, 60,  60),
}
```

Exact coordinates determined after shop interior images are finalized.

**Generation trigger:** When executor processes `collection_add` memory update.

```python
# In executor, after collection_add:
item_description = memory_update['description']  # e.g. "A small brass compass with a cracked face"
placement = memory_update.get('placement', 'shelf')  # shelf | counter | backroom

if placement != 'backroom':
    slot = await assign_shelf_slot(item_id)
    if slot:
        await generate_item_sprite(item_id, item_description, slot)
```

**Prompt template for item sprites:**

```
A single {item_description}. Small object, centered on transparent background.
Style: soft illustration, warm palette, consistent with antique shop aesthetic.
Studio Ghibli style object. Slight shadow beneath. 80x80 pixels effective size.
```

**Naming:** `item_{item_id}.png`

**Slot assignment table:**

```sql
CREATE TABLE IF NOT EXISTS shelf_assignments (
    slot_id TEXT PRIMARY KEY,
    item_id TEXT,
    item_description TEXT,
    sprite_path TEXT,
    assigned_at TIMESTAMP
);
```

**Growth:**
- Day 1: 0 items (empty shelves)
- Week 1: 3-8 items
- Month 1: 15-25 items
- Visitors literally watch the shelves fill up over time

**Backroom items:** Not visible on shelves. Listed in text only. Future: a second "room" view showing the backroom collection.

### 1.5 Layer 3: Her (Character Sprites)

**Dimensions:**

| Variable | Values | Count |
|----------|--------|-------|
| Posture/Activity | reading, writing, standing_window, arranging, sitting, talking, resting, sleeping | 8 |
| Mood/Expression | calm, happy, melancholy, curious, tired | 5 |
| Outfit | apron_A (default), casual_B, coat_C | 3 |

**Not all combinations are valid:**

```python
VALID_COMBINATIONS = {
    # posture: [valid moods]
    'reading':          ['calm', 'curious', 'happy'],
    'writing':          ['calm', 'melancholy', 'curious'],
    'standing_window':  ['calm', 'melancholy', 'curious', 'tired'],
    'arranging':        ['calm', 'happy', 'curious'],
    'sitting':          ['calm', 'melancholy', 'curious', 'tired'],
    'talking':          ['calm', 'happy', 'curious'],
    'resting':          ['tired', 'calm'],
    'sleeping':         ['calm'],  # one image only
}

# Valid sprite count: 
# reading(3) + writing(3) + standing(4) + arranging(3) + sitting(4) 
# + talking(3) + resting(2) + sleeping(1) = 23
# × 3 outfits = 69 total
# But launch with outfit A only = 23 sprites
```

**Naming:** `her_{posture}_{mood}_{outfit}.png`

```
her_reading_calm_apronA.png
her_reading_curious_apronA.png
her_writing_melancholy_apronA.png
her_standing_window_tired_apronA.png
her_sleeping_calm_apronA.png
...
```

**State mapping (deterministic, no LLM):**

```python
def get_character_sprite(activity: str, drives: DrivesState, 
                         engagement: str, weather: str) -> str:
    """Map current state to sprite filename."""
    
    # Posture from activity/engagement
    if engagement == 'engaged':
        posture = 'talking'
    elif activity == 'consume':
        posture = 'reading'
    elif activity == 'express':
        posture = 'writing'
    elif activity == 'thread':
        posture = 'sitting'  # thinking
    elif activity == 'rest':
        posture = 'resting'
    elif activity == 'sleep':
        posture = 'sleeping'
    elif activity == 'news' and random.random() < 0.5:
        posture = 'standing_window'  # noticing something outside
    else:
        # Idle: weighted random
        posture = random.choices(
            ['standing_window', 'sitting', 'arranging'],
            weights=[0.4, 0.4, 0.2]
        )[0]
    
    # Mood from drives
    mood = _map_mood(drives.mood_valence, drives.mood_arousal, drives.energy)
    
    # Validate combination, fallback to 'calm' if invalid
    valid_moods = VALID_COMBINATIONS.get(posture, ['calm'])
    if mood not in valid_moods:
        mood = 'calm'
    
    # Outfit from weather/time/season (future: from her choices)
    outfit = _get_outfit(weather, drives.energy)
    
    return f"her_{posture}_{mood}_{outfit}.png"


def _map_mood(valence: float, arousal: float, energy: float) -> str:
    """Map continuous drives to discrete mood label."""
    if energy < 0.2:
        return 'tired'
    if valence > 0.3 and arousal > 0.3:
        return 'happy'
    if valence < -0.2:
        return 'melancholy'
    if arousal > 0.4:
        return 'curious'
    return 'calm'


def _get_outfit(weather: str, energy: float) -> str:
    """Outfit selection. Simple for launch."""
    # Future: she can choose outfits, store in DB
    return 'apronA'  # always default for now
```

**Generation strategy:**

```
Launch set (Day 0): Generate the 12 most common sprites
  reading × (calm, curious)
  writing × (calm, curious)
  standing_window × (calm, melancholy)
  sitting × (calm, curious)
  talking × (calm, happy)
  arranging × calm
  resting × tired
  sleeping × calm

Day 1-7: Generate remaining ~11 sprites as new combos appear
  First time she's melancholy while writing → generate, add to library

Week 2+: Library complete for outfit A. ~0 new generations.

Outfit B/C: Generate when outfit system is added (future).
```

**Prompt template for character sprites:**

```
A young Japanese woman with short dark hair and quiet eyes, {posture_description}.
She wears {outfit_description}. Her expression is {mood_description}.
Full body, positioned as if behind a shop counter in a small antique shop.
Transparent background. Consistent character across all images in the series.
Style: soft illustration, muted warm palette, Studio Ghibli atmosphere.
Same character as reference — maintain face, hair, body proportions exactly.
```

Posture descriptions:

```python
POSTURE_DESCRIPTIONS = {
    'reading':          'sitting at a wooden counter, leaning slightly over an open book, one hand resting on the page',
    'writing':          'sitting at a wooden counter, writing in a small journal with a pen, head slightly tilted',
    'standing_window':  'standing by a window, hands loosely clasped behind her back, looking outward',
    'arranging':        'reaching toward a shelf, carefully adjusting the position of a small object',
    'sitting':          'sitting still on a wooden stool behind the counter, hands in her lap, eyes unfocused',
    'talking':          'leaning slightly forward across the counter, one hand gesturing gently, making eye contact',
    'resting':          'resting her head on her folded arms on the counter, eyes half-closed',
    'sleeping':         'not visible — the shop is dark, only a faint light from the back room',
}

MOOD_DESCRIPTIONS = {
    'calm':       'calm, neutral, at rest — a quiet presence',
    'happy':      'a slight smile, warmth in the eyes, something gentle',
    'melancholy': 'a distant look, not sad but contemplative, as if remembering something',
    'curious':    'eyes slightly wider, head tilted, engaged with something interesting',
    'tired':      'heavy eyelids, shoulders slightly low, the weight of a long day',
}
```

**Style consistency:** Generate all sprites in the same session with the same seed/style reference. Use a reference image to maintain face/hair/body consistency across all poses. This is critical — the character must look like the same person in every sprite.

### 1.6 Layer 4: Foreground Overlays

Static decorative elements that sit in front of everything else:

```
fg_counter_top.png      — counter surface (partially obscures her lower body)
fg_window_frame.png     — window frame edge (frames the background)
fg_rain_drops.png       — animated rain overlay (CSS/canvas, not a static image)
fg_snow_particles.png   — animated snow overlay
fg_dust_motes.png       — subtle floating particles (always present, very faint)
fg_lantern_glow.png     — warm light bloom from the paper lanterns
```

**Rain/snow/dust are canvas animations**, not static PNGs. Small particle systems driven by the weather state. Adds life without image generation.

**Total foreground images:** 3-4 static overlays. Generated once.

### 1.7 Composition Engine

**File:** `compositing.py` (server-side) + `SceneCanvas.tsx` (client-side)

#### Client-side (primary — instant, per-viewer):

```typescript
// SceneCanvas.tsx
const SceneCanvas = ({ layers }: { layers: SceneLayers }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    
    // Draw in order: background → shop → items → her → foreground
    const drawScene = async () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      
      // Layer 0: Background
      await drawImage(ctx, `/assets/bg/${layers.background}`);
      
      // Layer 1: Shop interior
      await drawImage(ctx, `/assets/shop/${layers.shop}`);
      
      // Layer 2: Items at shelf positions
      for (const item of layers.items) {
        await drawImageAt(ctx, `/assets/items/${item.sprite}`, 
                         item.x, item.y, item.width, item.height);
      }
      
      // Layer 3: Her
      await drawImageAt(ctx, `/assets/her/${layers.character}`,
                       layers.characterPosition.x, layers.characterPosition.y,
                       layers.characterPosition.width, layers.characterPosition.height);
      
      // Layer 4: Foreground
      for (const fg of layers.foreground) {
        await drawImage(ctx, `/assets/fg/${fg}`);
      }
    };
    
    drawScene();
  }, [layers]);
  
  // Particle overlays (rain, snow, dust)
  useEffect(() => {
    if (layers.weather === 'rain') startRainParticles(canvasRef);
    if (layers.weather === 'snow') startSnowParticles(canvasRef);
    startDustMotes(canvasRef); // always running, very subtle
  }, [layers.weather]);
  
  return <canvas ref={canvasRef} width={1536} height={1024} 
                 className="w-full aspect-[3/2]" />;
};
```

#### Server-side (for social previews / thumbnails / OG images):

```python
from PIL import Image

async def composite_scene(layers: dict) -> str:
    """Server-side composition for OG image / social preview."""
    canvas = Image.new('RGBA', (1536, 1024))
    
    bg = Image.open(f"assets/bg/{layers['background']}").convert('RGBA')
    canvas.paste(bg, (0, 0))
    
    shop = Image.open(f"assets/shop/{layers['shop']}").convert('RGBA')
    canvas.alpha_composite(shop)
    
    for item in layers['items']:
        sprite = Image.open(f"assets/items/{item['sprite']}").convert('RGBA')
        sprite = sprite.resize((item['width'], item['height']))
        canvas.paste(sprite, (item['x'], item['y']), sprite)
    
    character = Image.open(f"assets/her/{layers['character']}").convert('RGBA')
    pos = layers['character_position']
    canvas.paste(character, (pos['x'], pos['y']), character)
    
    for fg in layers['foreground']:
        overlay = Image.open(f"assets/fg/{fg}").convert('RGBA')
        canvas.alpha_composite(overlay)
    
    output_path = f"data/scenes/composite_{layers['scene_id']}.png"
    canvas.save(output_path)
    return output_path
```

### 1.8 Layer State Builder

**File:** `pipeline/scene.py`

Replaces the old prompt-per-cycle approach. Purely deterministic — maps current state to layer filenames.

```python
from dataclasses import dataclass

@dataclass
class SceneLayers:
    background: str           # bg_tokyo_rain_afternoon.png
    shop: str                 # shop_warm_day.png
    items: list[dict]         # [{sprite, x, y, width, height}, ...]
    character: str            # her_reading_calm_apronA.png
    character_position: dict  # {x, y, width, height}
    foreground: list[str]     # [fg_counter_top.png, fg_lantern_glow.png]
    weather: str              # for particle effects
    scene_id: str             # unique ID for this state


async def build_scene_layers(drives, ambient, focus, engagement, clock_now) -> SceneLayers:
    """Build layer specification from current state. No LLM, no generation."""
    
    time_of_day = get_time_of_day(clock_now)
    weather = ambient.get('condition', 'clear')
    shop_status = (await db.get_room_state()).shop_status
    
    # Layer 0
    background = f"bg_tokyo_{weather}_{time_of_day}.png"
    
    # Layer 1
    lighting = get_shop_lighting(time_of_day, shop_status)
    shop = f"shop_{lighting}.png"
    
    # Layer 2
    items = await db.get_shelf_assignments()  # returns [{slot_id, sprite_path, x, y, w, h}]
    
    # Layer 3
    activity = focus.channel if focus else 'idle'
    character = get_character_sprite(activity, drives, engagement.status, weather)
    
    # Check if sprite exists; if not, queue generation
    if not sprite_exists(character):
        await queue_sprite_generation(character)
        character = get_fallback_sprite(activity)  # nearest valid sprite that exists
    
    # Layer 4
    foreground = ['fg_counter_top.png']
    if time_of_day in ('evening', 'night'):
        foreground.append('fg_lantern_glow.png')
    
    return SceneLayers(
        background=background,
        shop=shop,
        items=[{
            'sprite': item.sprite_path,
            'x': item.x, 'y': item.y,
            'width': item.width, 'height': item.height,
        } for item in items],
        character=character,
        character_position=CHARACTER_ANCHOR,  # fixed position in shop layout
        foreground=foreground,
        weather=weather,
        scene_id=f"scene_{clock_now.strftime('%Y%m%d_%H%M%S')}",
    )
```

### 1.9 Sprite Generation Queue

New sprites are generated asynchronously — never blocking a cycle.

**File:** `pipeline/sprite_gen.py`

```python
import asyncio
import os
from pathlib import Path

ASSET_DIR = 'assets'
GENERATION_QUEUE: asyncio.Queue = asyncio.Queue()

async def queue_sprite_generation(sprite_filename: str):
    """Queue a sprite for async generation. Non-blocking."""
    await GENERATION_QUEUE.put(sprite_filename)


async def sprite_gen_worker():
    """Background worker that generates sprites from queue."""
    while True:
        filename = await GENERATION_QUEUE.get()
        try:
            if sprite_exists(filename):
                continue  # already generated (race condition guard)
            
            # Parse filename to get generation params
            params = parse_sprite_filename(filename)
            prompt = build_sprite_prompt(params)
            
            # Generate via image API
            image_data = await generate_image(prompt)
            
            # Save to assets directory
            filepath = os.path.join(ASSET_DIR, params['category'], filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'wb') as f:
                f.write(image_data)
            
            print(f"[sprite_gen] Generated: {filename}")
        except Exception as e:
            print(f"[sprite_gen] Failed: {filename} — {e}")
        finally:
            GENERATION_QUEUE.task_done()


def sprite_exists(filename: str) -> bool:
    """Check if sprite already exists in library."""
    # Check across all asset subdirectories
    for subdir in ('bg', 'shop', 'her', 'items', 'fg'):
        if Path(ASSET_DIR, subdir, filename).exists():
            return True
    return False


def get_fallback_sprite(activity: str) -> str:
    """Return nearest valid sprite that exists. Always returns something."""
    # Fallback chain: try calm version of same posture → standing_calm → reading_calm
    posture = ACTIVITY_TO_POSTURE.get(activity, 'standing_window')
    candidates = [
        f"her_{posture}_calm_apronA.png",
        f"her_standing_window_calm_apronA.png",
        f"her_reading_calm_apronA.png",
    ]
    for c in candidates:
        if sprite_exists(c):
            return c
    return "her_standing_window_calm_apronA.png"  # absolute fallback


def parse_sprite_filename(filename: str) -> dict:
    """Parse 'her_reading_calm_apronA.png' → {category, posture, mood, outfit}."""
    parts = filename.replace('.png', '').split('_')
    if parts[0] == 'her':
        return {
            'category': 'her',
            'posture': '_'.join(parts[1:-2]),  # handles 'standing_window'
            'mood': parts[-2],
            'outfit': parts[-1],
        }
    elif parts[0] == 'item':
        return {'category': 'items', 'item_id': parts[1]}
    elif parts[0] == 'bg':
        return {'category': 'bg', 'location': parts[1], 'weather': parts[2], 'time': parts[3]}
    return {'category': 'unknown', 'filename': filename}
```

Start the worker alongside heartbeat:

```python
# In heartbeat_server.py startup:
asyncio.create_task(sprite_gen_worker())
```

### 1.10 Asset Directory Structure

```
assets/
  bg/
    bg_tokyo_clear_morning.png
    bg_tokyo_clear_afternoon.png
    bg_tokyo_rain_evening.png
    ... (20 total)
  shop/
    shop_warm_day.png
    shop_soft_evening.png
    shop_dim_night.png
    shop_dark_sleep.png
  her/
    her_reading_calm_apronA.png
    her_reading_curious_apronA.png
    her_writing_calm_apronA.png
    her_standing_window_melancholy_apronA.png
    ... (23 for outfit A, ~69 total eventually)
  items/
    item_t001_brass_compass.png
    item_t002_cloud_diagram.png
    ... (grows with her collection)
  fg/
    fg_counter_top.png
    fg_lantern_glow.png
    fg_window_frame.png
```

### 1.11 Generation Budget

| Phase | Images | Cost (gpt-image-1 medium) | When |
|-------|--------|--------------------------|------|
| Launch set | ~40 (20 bg + 4 shop + 12 core sprites + 4 fg) | ~$1.60 | Once, before deploy |
| Week 1 | ~15 (11 remaining sprites + ~4 item sprites) | ~$0.60 | As new states appear |
| Week 2+ | ~2-5/week (new collection items) | ~$0.10-0.20/week | Ongoing |
| Outfit B launch | ~23 (full posture set) | ~$0.92 | Whenever added |

**Total first month: ~$3-5. Versus original spec: ~$15/month ongoing.**

### 1.12 Simulation Mode

In simulation, skip all image generation. The scene layer specification is still built and logged (so you can verify state mapping), but no sprites are generated or composited.

```bash
# Normal simulation (no images):
python simulate.py --days 7

# Simulation with image generation (builds the launch library):
python simulate.py --days 7 --generate-assets
```

The `--generate-assets` flag is useful for bootstrapping: run a 7-day sim and let the sprite gen worker build the initial library from actual cycle states.

### 1.13 Scene Transitions

When the scene changes, don't snap — crossfade:

```typescript
// In SceneCanvas.tsx:

// When new layers arrive via WebSocket:
// 1. Keep current canvas visible
// 2. Draw new scene on an offscreen canvas
// 3. Crossfade over 3-4 seconds (opacity transition)
// 4. Swap canvases

// Character pose changes:
// Slightly faster transition (1-2s) for posture shifts
// She appears to move naturally between poses

// Weather changes:
// Particle system transitions smoothly (rain fades out, snow fades in)
// Background crossfade is slow (5-6s) — weather changes gradually

// Item additions:
// New item sprite fades in at its shelf slot over 2s
// Subtle "glow" effect on first appearance (CSS animation)
```

---

## PART 2: WINDOW FRONTEND

### 2.1 Overview

**Framework:** Next.js 14+ (App Router)
**Styling:** Tailwind CSS
**Real-time:** WebSocket connection to heartbeat server
**Scene rendering:** HTML5 Canvas compositing
**Deployment:** Docker alongside shopkeeper, or static export served by nginx

### 2.2 Page Structure

One page. The window is the entire experience.

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│                 [ SCENE CANVAS ]                    │
│          Background + Shop + Items + Her            │
│         Rain particles. Lantern glow. Dust.         │
│            (16:9, takes most of viewport)            │
│                                                     │
│  ┌─ subtle overlay, bottom of canvas ─────────────┐ │
│  │  "Reading about a man who named the clouds."   │ │
│  │                          — current activity     │ │
│  └────────────────────────────────────────────────┘ │
│                                                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────┐  ┌─────────────────────────────┐  │
│  │  HER STATE   │  │      TEXT STREAM            │  │
│  │              │  │                             │  │
│  │  ☁ Rain      │  │  "I read about a man who    │  │
│  │  Afternoon   │  │   named the clouds. Before  │  │
│  │              │  │   him, they were just        │  │
│  │  Thinking    │  │   shapes."                  │  │
│  │  about:      │  │                             │  │
│  │  · why we    │  │  ──────                     │  │
│  │    name      │  │                             │  │
│  │    things    │  │  "The rain started around   │  │
│  │  · liminal   │  │  noon. I moved the cameras  │  │
│  │    spaces    │  │  to a higher shelf."        │  │
│  │              │  │                             │  │
│  └──────────────┘  └─────────────────────────────┘  │
│                                                     │
├─────────────────────────────────────────────────────┤
│  [ Enter the shop → ]           (gated chat button) │
└─────────────────────────────────────────────────────┘
```

### 2.3 Components

```
window/
  src/
    app/
      page.tsx                  # Main window page
      layout.tsx                # Root layout, metadata, fonts
      api/
        state/route.ts          # Proxy to backend /api/state
        og/route.ts             # OG image endpoint (server-side composite)
      globals.css               # Tailwind base + atmospheric styles
    components/
      SceneCanvas.tsx           # Canvas compositor + particle effects
      TextStream.tsx            # Scrolling feed of her thoughts/journal
      StatePanel.tsx            # Weather, time, threads summary
      ActivityOverlay.tsx       # Semi-transparent label on canvas bottom
      ChatGate.tsx              # "Enter the shop" button + auth modal
      ChatPanel.tsx             # Slide-up chat interface
      ConnectionIndicator.tsx   # Subtle pulse showing live connection
      ShelfGlow.tsx             # Item-added animation
    hooks/
      useShopkeeperSocket.ts    # WebSocket connection + reconnect
      useSceneTransition.ts     # Crossfade timing between layer sets
      useParticles.ts           # Rain/snow/dust particle system
    lib/
      types.ts                  # TypeScript types
      compositor.ts             # Canvas drawing utilities
      particles.ts              # Particle system engine
      api.ts                    # REST helpers for initial load
    assets/
      fonts/                    # Atmospheric fonts (e.g. Zen Kaku Gothic)
```

### 2.4 WebSocket Protocol

**Connection:** `wss://your-domain.com/ws/window`

**Server → Client messages:**

```typescript
// Scene layer update (per cycle, ~every 2-10 min)
{
  type: 'scene_update',
  layers: {
    background: 'bg_tokyo_rain_afternoon.png',
    shop: 'shop_warm_day.png',
    items: [
      { sprite: 'item_t001_brass_compass.png', x: 120, y: 180, width: 80, height: 80 },
      { sprite: 'item_t002_cloud_diagram.png', x: 220, y: 300, width: 80, height: 80 },
    ],
    character: 'her_reading_calm_apronA.png',
    character_position: { x: 280, y: 380, width: 200, height: 350 },
    foreground: ['fg_counter_top.png', 'fg_lantern_glow.png'],
    weather: 'rain',
  },
  text: {
    current_thought: 'Reading about a man who named the clouds.',
    activity_label: 'Reading',
  },
  state: {
    threads: [{ id: 't_001', title: 'Why do we name things?', status: 'active' }],
    weather_diegetic: 'Rain on the windows. The sound fills the shop.',
    time_label: 'Afternoon',
    visitor_present: false,
  },
  timestamp: '2026-02-13T14:30:00+09:00',
}

// Text fragment (journal entries, thoughts, thread updates)
{
  type: 'text_fragment',
  content: 'I wonder what it felt like to give a name to something that disappears.',
  fragment_type: 'journal' | 'thought' | 'thread_update' | 'response' | 'visitor_speech',
  timestamp: '2026-02-13T14:35:00+09:00',
}

// New item added to shelf
{
  type: 'item_added',
  item: {
    sprite: 'item_t003_umbrella.png',
    x: 320, y: 180, width: 80, height: 80,
    description: 'An old paper umbrella with a torn panel.',
  },
  timestamp: '2026-02-13T15:00:00+09:00',
}

// Status (sleep/wake, connection health)
{
  type: 'status',
  status: 'awake' | 'sleeping' | 'resting',
  message: "She's sleeping. The shop is dark.",
}
```

**Client → Server messages (authenticated chat only):**

```typescript
{
  type: 'visitor_message',
  text: string,
  token: string,
}
```

### 2.5 Key Component Details

#### SceneCanvas.tsx

```typescript
// Two offscreen canvases for crossfade transitions
// Layer images preloaded into Image objects, cached by filename
// Particle system renders on a separate transparent canvas overlaid via CSS
// Rain: 200 particles, vertical with slight drift, blue-grey
// Snow: 80 particles, slow diagonal, white
// Dust motes: 15 particles, slow random float, warm yellow, very low opacity (0.05-0.15)
// Canvas aspect ratio: 3:2 (1536×1024) or 16:9 (1536×864)
// Responsive: canvas scales to viewport width, maintains aspect ratio
```

#### TextStream.tsx

```typescript
// Vertical feed, most recent at top
// New entries fade in with typewriter reveal (30ms per character)
// Max 8 entries visible, older ones slide down and fade to 40% opacity
// Fragment types styled differently:
//   journal: italic, slightly indented, like handwriting
//   thought: normal, quiet
//   thread_update: prefixed with thread title in small caps
//   response: her direct speech, slightly bolder
//   visitor_speech: in quotes, different color (muted), prefixed with name
// Timestamps shown as relative: "3 minutes ago", "this morning"
```

#### StatePanel.tsx

```typescript
// Minimal atmospheric sidebar. No numbers, no metrics.
// 
// Weather: small icon + diegetic text
//   "Rain on the windows."
//   NOT: "Weather: rain, 8°C, 80% humidity"
//
// Time: single word
//   "Afternoon"
//   NOT: "14:32 JST"
//
// Activity: natural language
//   "Reading"  "Thinking"  "Arranging the shelf"
//   NOT: "Mode: engage, Channel: consume"
//
// Threads: list of titles, small text, like notes pinned to a wall
//   · why we name things
//   · liminal spaces
//   · object memory
//
// When sleeping: panel shows only "The shop is closed."
// When visitor present: "Someone is in the shop."
// When she just added an item: brief "New on the shelf: {item}" that fades after 30s
```

#### ActivityOverlay.tsx

```typescript
// Semi-transparent bar at the bottom of the scene canvas
// Shows what she's doing right now in natural language
// 
//   "Reading about a man who named the clouds."
//   "Arranging something on the top shelf."
//   "Looking out the window at the rain."
//   "Talking with Yuki."
//
// Fades in/out with scene transitions. Disappears during sleep.
// Very low opacity background (rgba(0,0,0,0.3)) so it doesn't obscure the scene.
```

### 2.6 Chat System

#### Access: Invite tokens

```python
# CLI: python generate_token.py --name "Yuki" --uses 10 --expires 7d

CREATE TABLE IF NOT EXISTS chat_tokens (
    token TEXT PRIMARY KEY,          -- random 16-char string
    display_name TEXT NOT NULL,
    uses_remaining INTEGER,          -- NULL = unlimited
    expires_at TIMESTAMP,            -- NULL = never
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### ChatGate.tsx

```typescript
// Single button at bottom: "Enter the shop →"
// On click: minimal modal asking for invite token
// On valid token: ChatPanel slides up from bottom
// On invalid: "The door doesn't open." (not "invalid token")
// Token stored in localStorage for return visits
```

#### ChatPanel.tsx

```typescript
// Slide-up panel, takes bottom 40% of viewport
// Scene canvas shrinks to top 60%
// Input field + send button
// Her responses appear in BOTH ChatPanel AND TextStream
// Other viewers see the conversation in their TextStream (read-only)
// When chat ends (visitor leaves or token expires): panel slides down
// "Thank you for visiting." message before close
```

#### Viewer perspective during chats

| Element | Window Viewer | Chat Visitor |
|---------|--------------|--------------|
| Scene canvas | She switches to 'talking' pose | Same |
| TextStream | Sees visitor messages + her responses | Same |
| ChatPanel | Not visible | Visible, can type |
| StatePanel | "Someone is in the shop." | Shows visitor name |

### 2.7 WebSocket Server

**Embedded in `heartbeat_server.py`:**

```python
import websockets
import json

window_clients: set = set()

async def handle_window_client(websocket, path):
    """Handle a window viewer WebSocket connection."""
    window_clients.add(websocket)
    try:
        # Send current state on connect
        state = await build_initial_state()
        await websocket.send(json.dumps(state))
        
        # Listen for chat messages (if authenticated)
        async for message in websocket:
            data = json.loads(message)
            if data['type'] == 'visitor_message':
                await handle_chat_message(data, websocket)
    except websockets.ConnectionClosed:
        pass
    finally:
        window_clients.discard(websocket)


async def broadcast_to_window(message: dict):
    """Broadcast to all connected window viewers."""
    if window_clients:
        payload = json.dumps(message)
        await asyncio.gather(
            *[client.send(payload) for client in window_clients],
            return_exceptions=True,
        )


async def start_servers(self):
    # Existing TCP server for terminal
    tcp_server = await asyncio.start_server(
        self.handle_terminal, HOST, PORT)
    
    # WebSocket server for window
    ws_port = int(os.environ.get('SHOPKEEPER_WS_PORT', '8765'))
    ws_server = await websockets.serve(
        handle_window_client, '0.0.0.0', ws_port)
    
    await asyncio.gather(
        tcp_server.serve_forever(),
        ws_server.serve_forever(),
    )
```

### 2.8 Static Asset Serving

Nginx serves the pre-generated asset library:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    # ... TLS config ...
    
    # Pre-generated assets (background, shop, sprites, items)
    location /assets/ {
        alias /app/assets/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
    
    # WebSocket upgrade
    location /ws/ {
        proxy_pass http://shopkeeper:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
    
    # API proxy
    location /api/ {
        proxy_pass http://shopkeeper:8080;
    }
    
    # Frontend
    location / {
        root /app/window/out;
        try_files $uri $uri.html $uri/ /index.html;
    }
}
```

### 2.9 Initial State Load (REST)

**Endpoint:** `GET /api/state`

```json
{
  "layers": {
    "background": "bg_tokyo_rain_afternoon.png",
    "shop": "shop_warm_day.png",
    "items": [
      {"sprite": "item_t001_brass_compass.png", "x": 120, "y": 180, "width": 80, "height": 80}
    ],
    "character": "her_reading_calm_apronA.png",
    "character_position": {"x": 280, "y": 380, "width": 200, "height": 350},
    "foreground": ["fg_counter_top.png", "fg_lantern_glow.png"],
    "weather": "rain"
  },
  "text": {
    "recent_entries": [
      {"content": "I read about a man who named the clouds...", "type": "journal", "timestamp": "..."}
    ]
  },
  "state": {
    "threads": [{"id": "t_001", "title": "Why do we name things?", "status": "active"}],
    "weather_diegetic": "Rain on the windows.",
    "time_label": "Afternoon",
    "status": "awake",
    "visitor_present": false
  }
}
```

### 2.10 OG Image (Social Preview)

When someone shares the URL, they should see a composed scene — not a blank preview.

**Endpoint:** `GET /api/og`

Returns a server-side PIL-composed image from current layers. Cached for 5 minutes. Used in meta tags:

```html
<meta property="og:image" content="https://your-domain.com/api/og" />
<meta property="og:title" content="The Shopkeeper" />
<meta property="og:description" content="A quiet shop in Tokyo. Someone is inside." />
```

---

## PART 3: BACKEND ADDITIONS

### 3.1 Text Fragments Table

**File:** `migrations/007_text_fragments.sql`

```sql
CREATE TABLE IF NOT EXISTS text_fragments (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    fragment_type TEXT NOT NULL,
    cycle_id TEXT,
    thread_id TEXT,
    visitor_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fragments_created ON text_fragments(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fragments_type ON text_fragments(fragment_type);
```

Written by executor after each cycle:
- `journal_entry` → fragment type 'journal'
- Cortex `inner_thought` → fragment type 'thought'
- `thread_create/update` → fragment type 'thread_update'
- Visitor response → fragment type 'response'
- Visitor speech → fragment type 'visitor_speech'

### 3.2 Shelf Assignments Table

**File:** `migrations/008_shelf_assignments.sql`

```sql
CREATE TABLE IF NOT EXISTS shelf_assignments (
    slot_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    item_description TEXT,
    sprite_filename TEXT,
    assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 3.3 Window State Builder

**File:** `window_state.py`

```python
async def build_initial_state() -> dict:
    """Full state payload for new WebSocket connections and REST /api/state."""
    drives = await db.get_drives_state()
    room = await db.get_room_state()
    engagement = await db.get_engagement_state()
    threads = await db.get_active_threads(limit=5)
    ambient = await db.get_latest_ambient()
    fragments = await db.get_recent_text_fragments(limit=8)
    items = await db.get_shelf_assignments()
    
    layers = await build_scene_layers(drives, ambient, 
                                       current_focus, engagement, clock.now())
    
    return {
        'type': 'scene_update',
        'layers': asdict(layers),
        'text': {
            'recent_entries': [
                {'content': f.content, 'type': f.fragment_type, 
                 'timestamp': f.created_at.isoformat()}
                for f in fragments
            ],
        },
        'state': {
            'threads': [{'id': t.id, 'title': t.title, 'status': t.status} 
                       for t in threads],
            'weather_diegetic': ambient.get('diegetic', '') if ambient else '',
            'time_label': get_time_label(clock.now()),
            'status': 'sleeping' if room.shop_status == 'closed' else 'awake',
            'visitor_present': engagement.status == 'engaged',
        },
        'timestamp': clock.now().isoformat(),
    }
```

### 3.4 Post-Cycle Broadcast

In heartbeat, after each cycle completes:

```python
# After executor runs:

# 1. Write text fragments
await write_text_fragments(cycle_result)

# 2. Build new scene layers
layers = await build_scene_layers(drives, ambient, focus, engagement, clock.now())

# 3. Broadcast to window viewers
await broadcast_to_window({
    'type': 'scene_update',
    'layers': asdict(layers),
    'text': {
        'current_thought': extract_current_thought(cycle_result),
        'activity_label': get_activity_label(focus),
    },
    'state': await build_state_summary(),
    'timestamp': clock.now().isoformat(),
})

# 4. If new item added, broadcast separately for animation
for item in cycle_result.new_shelf_items:
    await broadcast_to_window({
        'type': 'item_added',
        'item': item,
        'timestamp': clock.now().isoformat(),
    })
```

---

## PART 4: BUILD ORDER

### Phase 1: Asset Generation Infrastructure
1. `pipeline/scene.py` — SceneLayers dataclass + build_scene_layers()
2. `pipeline/sprite_gen.py` — generation queue + worker + prompt templates
3. `pipeline/image_gen.py` — OpenAI/Replicate adapter (reuse for all sprite types)
4. `migrations/008_shelf_assignments.sql`
5. Asset directory structure
6. **Generate launch set:** 20 backgrounds + 4 shop interiors + 12 core character sprites + 4 foreground overlays = 40 images
7. **Test:** Verify layer composition via PIL script

### Phase 2: Text Fragments + Window State
8. `migrations/007_text_fragments.sql`
9. Executor writes text fragments after each cycle
10. `window_state.py` — state builder
11. Post-cycle broadcast hook in heartbeat
12. **Test:** Run heartbeat, verify state JSON is correct

### Phase 3: WebSocket Server
13. WebSocket listener in heartbeat_server.py
14. `/api/state` REST endpoint
15. Connection handling (join, disconnect, broadcast)
16. **Test:** Connect via wscat, receive state on connect + live updates

### Phase 4: Frontend Shell
17. Next.js project scaffolding (`window/` directory)
18. `useShopkeeperSocket` hook
19. `SceneCanvas` — canvas compositor + layer drawing
20. `useParticles` — rain/snow/dust particle system
21. `TextStream` with typewriter reveal
22. `StatePanel`
23. `ActivityOverlay`
24. `ConnectionIndicator`
25. Scene crossfade transitions
26. **Test:** Connect to live heartbeat, watch scene change over cycles

### Phase 5: Chat Gate
27. `chat_tokens` table + `generate_token.py` CLI
28. `ChatGate` component
29. `ChatPanel` component
30. WebSocket chat message → visitor_speech event injection
31. Token validation
32. **Test:** Generate token, chat, verify conversation visible to all viewers

### Phase 6: Polish + Deploy
33. OG image endpoint (server-side PIL composite)
34. nginx config (assets + WebSocket + frontend)
35. Docker additions (window service or combined)
36. Sprite cleanup / optimization (compress PNGs)
37. `--generate-assets` flag in simulate.py for bootstrapping library
38. Scene image cache on client (don't re-download unchanged layers)
39. **Test:** Full flow on VPS

---

## WHAT DOESN'T CHANGE

- Pipeline architecture
- Single Cortex call per cycle (scene layers are deterministic, not LLM-generated)
- Arbiter, threads, content pool, sleep cycle
- Terminal interface (still works for dev)
- TCP server for terminal connections
- Simulation mode

---

## RISKS / NOTES

- **Visual consistency across sprites** is the hardest problem. Generate all character sprites in the same session with the same style reference. If one sprite looks different, regenerate it — don't ship inconsistency.
- **Shelf slot coordinates** must match the shop interior image exactly. Measure after generating the shop images. Expect 1-2 iterations to get alignment right.
- **Canvas performance** is fine for this use case (~5-7 layers). No WebGL needed. Even mobile browsers handle this.
- **Asset size:** ~40 PNGs at launch ≈ 20-40MB total. Aggressive caching (7-day expiry, immutable) means viewers load them once.
- **Fallback sprite** is critical. If a new mood/posture combo appears and the sprite hasn't been generated yet, she should still be visible. The fallback chain (same posture + calm → standing + calm) ensures she's never invisible.
- **Item sprite generation** is the only ongoing cost. Each new collection item needs one sprite. At ~2-5 items/week, this is ~$0.10-0.20/week.
- **Sleep state:** Canvas shows `shop_dark_sleep.png` background, `sleeping_calm` sprite (or no character visible), no particles except slow dust. TextStream shows "The shop is closed." WebSocket stays connected — viewers see the dark shop.
- **Outfit system** is deferred. Launch with outfit A only (23 sprites). Add outfits when she has enough personality to choose them.

---

*Someone opens the URL. The canvas loads — a rainy afternoon in Tokyo, a small shop. Through the window, grey sky. Inside: warm light, cluttered shelves, a brass compass glinting on the second shelf. She's sitting at the counter, reading. The text below reads: "I read about a man who named the clouds." Rain particles drift down the window glass. A dust mote floats past a paper lantern. They watch for ten minutes. She puts down the book, stands, walks to the window. The text changes: "The rain started around noon." The shelves have five objects now — last week there were three. The viewer bookmarks the page. They'll come back tomorrow to see what she read next.*
