# THE SHOPKEEPER — Art Generation Guide

## Goal
Generate a consistent AI character across ~20 images that can be composited into a living illustration system. Lo-fi anime aesthetic. Cowboy Bebop sensibility. She feels real, not designed.

---

## PHASE 1: The Reference Sheet (Do This First)

Generate ONE perfect image that defines her. Everything else derives from this.

### Master Reference Prompt (Midjourney)

```
A young woman with short dark hair and round glasses, sitting behind 
the counter of a small dimly-lit curiosity shop. Warm amber lighting. 
She has a composed, neutral expression — not cold, just still. 
Simple dark clothing, nothing flashy. The shop has floating objects 
on shelves behind her — glowing softly. Lo-fi anime illustration style, 
Cowboy Bebop character design influence, Samurai Champloo color palette. 
NOT generic anime. NOT cute/moe. She looks like a real person drawn 
beautifully. Detailed face, specific features — slightly sharp jaw, 
thin eyebrows, glasses she clearly adjusts often. Age ambiguous — 
could be 22 or ancient. Painterly quality, visible brush texture. 
Aspect ratio 16:9 --ar 16:9 --style raw --v 6.1
```

### Style Anchors (add to every prompt)
```
--sref [URL of your approved reference image]
--cref [URL of your approved reference image]
```

Once you have THE image you love, use it as `--cref` and `--sref` for everything else. This is how you maintain consistency.

### Reference Sheet Checklist
- [ ] Face is specific (not generic anime)
- [ ] Glasses look like she actually wears them
- [ ] Hair has a specific cut (not "anime short hair")
- [ ] Expression is neutral-composed, not smiling, not sad
- [ ] Clothing is simple, intentional, dark tones
- [ ] Lighting is warm amber
- [ ] Shop feels intimate, slightly magical
- [ ] She looks like someone you'd want to talk to but wouldn't approach easily

---

## PHASE 2: The Shop Background (2 images)

These are the static backdrops. She composites on top.

### 2a. Day Background
```
Interior of a small curiosity shop, no people. Warm amber afternoon 
light through a window on the left. Wooden shelves with floating 
glowing objects — a vinyl record, a photograph, a small glowing orb, 
a handwritten card. A counter in the center-right. Soft dust motes 
in the light. Lo-fi anime background art, Makoto Shinkai lighting 
meets Cowboy Bebop interior design. Painterly, atmospheric. 
Aspect ratio 16:9 --ar 16:9 --style raw --v 6.1
```

### 2b. Night Background
```
Same curiosity shop interior at night. Warm lamp light from behind 
the counter. Window shows blue-grey city glow outside. The floating 
objects on shelves glow slightly brighter in the dark. More intimate, 
more private. A cup of tea steams on the counter. Lo-fi anime 
background art, moody, atmospheric. Aspect ratio 16:9 
--ar 16:9 --style raw --v 6.1
```

---

## PHASE 3: Body States (6 images)

Generate her from mid-thigh up, transparent/simple background (you'll composite onto the shop). Same outfit, same character reference.

**Base prompt for all body states:**
```
[CHARACTER REFERENCE] A young woman with short dark hair and round 
glasses in a small shop. Simple dark clothing. Lo-fi anime illustration, 
Cowboy Bebop character design. Painterly brush texture. Upper body 
and arms visible. [POSE SPECIFIC DIRECTION]. Simple flat background. 
--ar 3:4 --cref [ref] --sref [ref] --style raw --v 6.1
```

### 3a. Sitting (default)
```
...sitting behind a counter, hands resting naturally, relaxed posture 
but not slouched. Weight slightly forward. One hand near a cup.
```

### 3b. Leaning Forward
```
...leaning forward slightly on the counter, interested, weight on 
forearms. Like she just heard something that caught her attention. 
Elbows on counter.
```

### 3c. Reaching Back
```
...turning to reach for something on the shelf behind her. One arm 
extended back, body in slight twist. Looking over her shoulder 
toward the viewer.
```

### 3d. Holding Object
```
...holding a small glowing object in both hands, looking down at it. 
Examining something precious. Careful grip, like it might break.
```

### 3e. Writing
```
...writing in a small notebook on the counter. Head slightly tilted 
down, pen in hand. Absorbed in thought. Hair falling slightly 
forward.
```

### 3f. Hands on Cup
```
...both hands wrapped around a warm cup of tea. Holding it close, 
not drinking — just holding. Comfort gesture. Steam rising slightly.
```

---

## PHASE 4: Facial Expressions (8 images)

Close-up face shots. Same character, same glasses, same lighting. These get composited onto the body states.

**Base prompt for all expressions:**
```
[CHARACTER REFERENCE] Close-up portrait of a young woman with short 
dark hair and round glasses. Warm amber lighting from the side. 
Lo-fi anime style, Cowboy Bebop. Painterly. Detailed eyes behind 
glasses. [EXPRESSION SPECIFIC]. --ar 1:1 --cref [ref] --sref [ref] 
--style raw --v 6.1
```

### 4a. Neutral (default)
```
...composed, still expression. Not cold — present. Slight awareness 
in the eyes. Mouth relaxed, closed. The face of someone listening 
to distant music.
```

### 4b. Listening
```
...attentive expression. Eyes slightly wider, focused on something 
in front of her. Head tilted 2 degrees. She's actually hearing you. 
Mouth still closed.
```

### 4c. Almost Smile
```
...the very beginning of a smile. Not a full smile — just the right 
corner of her mouth lifting slightly. Eyes soften. This is the rarest 
and most important expression. It should feel EARNED, not default. 
Subtle. If you're not paying attention you'd miss it.
```

### 4d. Thinking
```
...eyes looking slightly up and to the right. One hand adjusting 
her glasses (push them up the bridge of her nose with index finger). 
Processing something. Mouth slightly compressed.
```

### 4e. Amused
```
...dry amusement. Not laughing. One eyebrow raised very slightly. 
The look of someone who caught an irony no one else noticed. 
Intelligent humor. Mouth has a hint of asymmetric curve.
```

### 4f. Low
```
...quiet sadness or tiredness. Eyes slightly downcast. Energy 
withdrawn. Not dramatic — just dim. Like someone who's been alone 
a beat too long. Shoulders slightly dropped.
```

### 4g. Surprised
```
...genuine surprise. Eyes wider, eyebrows lifted. Glasses slipped 
slightly down her nose. Mouth slightly parted. Not anime-shock — 
real surprise. Like someone said something she didn't expect 
and it actually landed.
```

### 4h. Genuine Smile
```
...a real, full smile. This is THE expression. It transforms her 
entire face. Eyes crinkle slightly. Warm. Open. Beautiful. 
This should feel like sunlight breaking through clouds. 
The viewer should feel like they accomplished something seeing this. 
This expression appears maybe once every 20 interactions.
```

---

## PHASE 5: Eye/Gaze Overlays (5 variants)

If your compositing system is sophisticated enough, generate gaze variants. Otherwise, skip this for MVP and handle gaze through the face expressions.

### Option A: Simple (MVP)
Don't separate gaze. Use the 8 face expressions as-is. The expression implies the gaze:
- neutral → at_visitor (default)
- thinking → away_thinking (eyes up-right)
- low → down
- listening → at_visitor

### Option B: Advanced (Post-MVP)
Generate just the eyes + upper face for each gaze direction, composite onto expressions:

```
...extreme close-up of eyes behind round glasses. Just eye area 
and bridge of nose. [GAZE DIRECTION]. Warm amber light reflected 
in lenses. Lo-fi anime.
```

- **at_visitor**: looking directly forward, slightly down (viewer is standing)
- **at_object**: looking to the right and slightly down (toward shelf)
- **away_thinking**: looking upper-left, slightly unfocused
- **down**: looking at hands/counter, introspective
- **window**: looking left toward light source, wistful

---

## PHASE 6: Special States (3 images)

### 6a. Shop Closed (exterior)
```
Exterior of a small shop at night. A warm light glows faintly behind 
frosted glass. A handwritten sign reads "closed" in both English 
and Japanese (閉店). The street is empty, slightly wet from rain. 
Lo-fi anime background. Moody, atmospheric. You can almost see 
a silhouette inside. --ar 16:9 --style raw --v 6.1
```

### 6b. Entry Silhouette (visitor arrives)
```
Dark interior of a shop. In the background, a figure sits behind 
a counter — visible only as a silhouette against warm amber backlight. 
The door in the foreground is slightly ajar, light spilling in. 
The moment before you step inside. Lo-fi anime, atmospheric. 
Cinematic framing. --ar 16:9 --style raw --v 6.1
```

### 6c. The Back Room (intimate, for familiars only)
```
A small back room behind a curiosity shop. More personal, less 
curated. A record player in the corner. Postcards pinned to the wall. 
A photograph leaning against a stack of books — an empty train station 
at dawn. Warmer, softer light. This room feels private. Like reading 
someone's diary. Lo-fi anime interior. --ar 16:9 --style raw --v 6.1
```

---

## TOTAL IMAGE COUNT

| Category | Count | Notes |
|---|---|---|
| Reference sheet | 1 | THE source of truth |
| Backgrounds | 2 | Day + Night |
| Body states | 6 | Transparent BG for compositing |
| Expressions | 8 | Close-up face, compositable |
| Special states | 3 | Closed, entry, back room |
| **Total** | **20** | |

---

## COMPOSITING SYSTEM (CSS)

```
<div class="shop-scene">
  <!-- Layer 1: Background -->
  <img class="bg" src="shop-day.png" />
  
  <!-- Layer 2: Body (positioned at counter) -->
  <img class="body" src="body-sitting.png" />
  
  <!-- Layer 3: Face (positioned on body) -->
  <img class="face" src="face-neutral.png" />
</div>
```

Transitions between states use CSS:
```css
.face {
  transition: opacity 0.4s ease-in-out;
}

/* Crossfade between expressions */
.face.transitioning {
  opacity: 0;
}
```

The frontend receives expression + body_state + gaze from the WebSocket and swaps the appropriate layers with a brief crossfade. Quick enough to feel responsive, slow enough to feel human.

---

## STYLE GUIDE (for consistency across all images)

### DO
- Warm amber/ochre lighting
- Visible painterly brush texture
- Specific facial features (not generic)
- Glasses that look real and slightly thick-framed
- Dark, simple clothing (navy, charcoal, black)
- Atmospheric depth (dust, light rays, steam)
- Cowboy Bebop / Samurai Champloo character specificity
- Make her look like someone with interior life

### DON'T
- Generic anime face / same-face syndrome
- Bright saturated colors
- Cute/moe aesthetic
- Perfect skin, perfect hair, perfect everything
- Dramatic poses or expressions
- Fantasy armor, school uniforms, maid outfits
- Anything that reads as "AI generated anime girl"
- Fan service of any kind

### Color Palette
- Background: warm browns, deep amber, dark wood
- Her clothing: navy, charcoal, occasionally white
- Accent: soft gold light, occasional teal from objects
- Night: blue-grey, warm lamp pools
- Objects: soft glows in varied warm colors

### The Vibe Test
Look at each generated image and ask:
"Would I believe this person exists in a Shinichirō Watanabe anime?"
If no, regenerate.

---

## TOOL RECOMMENDATIONS

**For best results, try in this order:**

1. **Midjourney v6.1** with --cref + --sref
   - Best for consistent character across images
   - Best painterly anime quality
   - Use --style raw to avoid over-stylization

2. **Stable Diffusion + LoRA**
   - Train a LoRA on your approved reference (10-20 images of her)
   - Most control over consistency
   - Requires technical setup

3. **NovelAI**
   - Strong anime-specific generation
   - Good for expressions
   - Less painterly than Midjourney

4. **Flux (via ComfyUI)**
   - Good quality, good consistency with IP-Adapter
   - Open source, free
   - More technical setup

**Workflow:**
1. Generate 50+ candidates in Midjourney for the reference sheet
2. Pick THE ONE
3. Use that as --cref for all subsequent generations
4. Generate 3-5 variants per needed image, pick the best
5. Light touch-up in Photoshop/GIMP for compositing (remove backgrounds, align faces)

---

## NAMING CONVENTION

```
bg_day.png
bg_night.png
body_sitting.png
body_leaning_forward.png
body_reaching_back.png
body_holding_object.png
body_writing.png
body_hands_on_cup.png
face_neutral.png
face_listening.png
face_almost_smile.png
face_thinking.png
face_amused.png
face_low.png
face_surprised.png
face_genuine_smile.png
special_closed.png
special_entry_silhouette.png
special_backroom.png
```

---

*When she finally has a face, the spell completes. Right now she lives in words. Soon she'll live in light.*
