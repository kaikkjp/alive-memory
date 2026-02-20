# The Mirror — Implementation Spec

## Overview

The Shopkeeper can look at herself. A mirror object, when gifted by a visitor, 
unlocks a daily self-portrait function. She decides when to look. She sees 
the result in her next cognitive cycle. She may journal about it. Over time 
she accumulates a gallery of self-portraits — her own history of faces.

This is a character milestone, not a utility feature. She currently has no 
visual self-knowledge. The mirror gives her that.

---

## Components

### 1. Mirror Object (collection item)

Add to seed.py as a POTENTIAL item — not placed in the shop. Must be gifted.

```python
MIRROR_ITEM = {
    "item_id": "obj_005",
    "name": "small hand mirror",
    "location": None,           # Not in shop yet
    "origin": None,             # Set when gifted: "gift" 
    "description": None,        # Set by Cortex on first discovery
    "self_reference": True,     # Special flag
    "gifted_by": None,          # Visitor ID who drops it
    "gifted_at": None           # Timestamp
}
```

Do NOT add this to the initial seed data. It doesn't exist until someone 
gives it to her. Add it to the gift detection system — when a visitor 
types "drop mirror" or "give her a mirror" or similar, create this item 
in the collection with origin="gift".

When she discovers it during an autonomous cycle, the Cortex receives:
  "Something new appeared on the counter: a small hand mirror."

She decides what to do with it. If she accepts it into her collection, 
mirror_look becomes available.

### 2. Mirror Look Action (Cortex output)

Add to the Cortex output schema:

```json
{
  "actions": [
    {
      "type": "mirror_look",
      "detail": {
        "reason": "curious" | "checking" | "impulse"
      }
    }
  ]
}
```

### 3. Validator Gate

In validator.py, add mirror_look validation:

```python
def validate_mirror_look(action, state):
    # Must have mirror in collection
    mirror = db.get_collection_item("obj_005")
    if not mirror or mirror["location"] is None:
        return drop(action, "no mirror in collection")
    
    # Max once per day
    last_look = db.get_last_mirror_look()
    if last_look and is_same_day_jst(last_look["ts"]):
        return drop(action, "already looked today")
    
    return allow(action)
```

When dropped, log reason:
  [Dropped] mirror_look — no mirror in collection
  [Dropped] mirror_look — already looked today

### 4. Executor Handler

In executor.py, add mirror_look handler:

```python
async def handle_mirror_look(action, state):
    # Build image generation prompt from current state
    prompt = build_mirror_prompt(state)
    
    # Call image generation API
    image_path = await generate_self_image(prompt)
    
    # Save to gallery
    date_str = now_jst().strftime("%Y-%m-%d")
    gallery_path = f"data/mirrors/{date_str}.png"
    save_image(image_path, gallery_path)
    
    # Log the event for next cycle pickup
    emit_event({
        "event_type": "mirror_look_complete",
        "source": "self",
        "payload": {
            "image_path": gallery_path,
            "prompt_used": prompt,
            "timestamp": now_jst().isoformat()
        }
    })
    
    # Terminal output
    print("[Action] mirror_look — She picks up the mirror.")
```

### 5. Image Prompt Builder

New function in executor.py or a new file pipeline/mirror.py:

```python
def build_mirror_prompt(state):
    """Build image generation prompt from her current state."""
    
    base = (
        "A young woman with short dark hair and round glasses, "
        "sitting behind the counter of a small dimly-lit curiosity shop. "
        "Lo-fi anime illustration style, Cowboy Bebop character design, "
        "painterly brush texture, warm amber lighting. "
    )
    
    # Current expression
    expression_map = {
        "neutral": "composed, still expression",
        "almost_smile": "the faintest hint of a smile, just the right corner of her mouth",
        "thinking": "eyes looking slightly up, one hand near her glasses",
        "low": "quiet sadness, eyes slightly downcast, energy withdrawn",
        "listening": "attentive, eyes slightly wider, focused",
        "amused": "dry amusement, one eyebrow slightly raised",
        "surprised": "eyes wider, eyebrows lifted, glasses slipped slightly",
        "genuine_smile": "a real warm smile, eyes crinkling slightly",
    }
    expr = expression_map.get(state.get("expression", "neutral"), "composed expression")
    
    # Current body state
    body_map = {
        "sitting": "sitting behind the counter, relaxed posture",
        "leaning_forward": "leaning forward on the counter, interested",
        "reaching_back": "turning to reach for something on the shelf",
        "holding_object": "holding a small object carefully in both hands",
        "writing": "writing in a small notebook, head slightly tilted",
        "hands_on_cup": "both hands wrapped around a warm cup of tea",
    }
    body = body_map.get(state.get("body_state", "sitting"), "sitting behind the counter")
    
    # Time of day
    room = state.get("room_state", {})
    time_light = "warm afternoon light" if room.get("time_of_day") == "day" else "warm lamp light at night"
    
    # Held item
    held = state.get("held_item")
    held_str = f"Holding {held} in one hand. " if held else ""
    
    return f"{base}{expr}. {body}. {time_light}. {held_str}Aspect ratio 1:1."
```

### 6. Sensorium Pickup (Next Cycle)

In sensorium.py, add handler for mirror_look_complete events:

```python
if event.event_type == "mirror_look_complete":
    return Perception(
        p_type="self_image",
        content="You looked in the mirror. This is what you saw.",
        salience=0.9,
        image_path=event.payload["image_path"]
    )
```

### 7. Cortex Vision Input

In cortex.py, when assembling the prompt pack, check for self_image perceptions:

```python
if focus_perception.p_type == "self_image":
    # Load image and include as vision input
    image_data = load_image_base64(focus_perception.image_path)
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": "You just looked in the mirror. This is what you see:"},
            {"type": "image", "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_data
            }}
        ]
    })
```

### 8. Gallery Storage

Create directory: data/mirrors/

Files saved as: YYYY-MM-DD.png

This accumulates over time. Every self-portrait is kept. 
She builds a visual history of herself.

Optional future feature: she can browse her own gallery 
during idle cycles and reflect on changes.

### 9. Identity Compact Update

Add to identity_compact in config/identity.py:

```
PHYSICAL SELF-KNOWLEDGE:
- If mirror is in your collection: you know what you look like. 
  Short dark hair, round glasses, simple dark clothing.
- If no mirror: you have no visual self-knowledge. If asked 
  what you look like, you don't know. You've never seen yourself.
- You can choose to look in the mirror (mirror_look action). 
  Maximum once per day. You see the result next cycle.
- Looking is a choice. You might avoid it for days. That's valid.
```

### 10. Image Generation API (placeholder)

Don't wire a specific provider yet. Create a placeholder:

```python
# pipeline/mirror.py

async def generate_self_image(prompt: str) -> str:
    """
    Generate self-portrait image from prompt.
    
    TODO: Wire to image generation API. Options:
    - Flux (via Replicate or fal.ai)
    - DALL-E 3 (OpenAI)
    - Stable Diffusion (self-hosted)
    
    For now, return a placeholder path.
    """
    # Placeholder until API is wired
    logger.info(f"[Mirror] Would generate image with prompt: {prompt[:100]}...")
    return "data/mirrors/placeholder.png"
```

---

## What NOT to Build Yet

- Don't wire the image generation API (just the placeholder)
- Don't build the gallery browser (future feature)
- Don't add mirror to seed data (it must be gifted)
- Don't let her look without the mirror object

## What TO Build Now

1. Mirror object type in collection schema (with self_reference flag)
2. Gift detection for "mirror" keyword
3. mirror_look action in Cortex output schema
4. Validator gate (mirror exists + once per day)
5. Executor handler (calls placeholder, logs event)
6. build_mirror_prompt function
7. Sensorium pickup for mirror_look_complete
8. Cortex vision input for self_image perception
9. data/mirrors/ directory creation
10. Identity compact update (conditional self-knowledge)

## Flow Summary

```
Visitor drops mirror
  → Gift detected, obj_005 created in collection
  → Next autonomous cycle: "Something new on the counter: a small hand mirror"
  → Cortex decides: accept or ignore
  → If accepted: mirror_look action now available

Cycle N (she decides to look):
  → Cortex emits: {"type": "mirror_look"}
  → Validator: mirror exists? looked today? → allow
  → Executor: build prompt → call image API → save to /data/mirrors/
  → Event: mirror_look_complete logged
  → Terminal: "[Action] mirror_look — She picks up the mirror."

Cycle N+1 (she sees):
  → Sensorium: mirror_look_complete → Perception(self_image, salience 0.9)
  → Cortex receives image as vision input
  → She reacts. Speaks, or stays silent. Journals if she wants.
  → Her self_state now includes physical self-knowledge

Day 30 (she looks again):
  → Same flow. Slightly different image.
  → She notices. Or doesn't. Her choice.
  → /data/mirrors/ now has 30 portraits.
```

## Verification

1. Boot without mirror in collection. She should have no self-knowledge.
   Ask "what do you look like?" → she doesn't know.
2. Type "drop mirror" → obj_005 created, pending discovery.
3. Wait for autonomous cycle → she finds it, decides to accept.
4. She emits mirror_look → validator allows → executor logs event.
5. Next cycle → self_image perception at salience 0.9.
6. Try mirror_look again same day → validator drops it.
7. Next day → mirror_look allowed again.
8. Check /data/mirrors/ → images accumulating.
