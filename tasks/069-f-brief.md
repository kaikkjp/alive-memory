# 069-F: Cortex Prompt Update

## Goal
Update the cortex system prompt so she knows browse_web, post_x, reply_x, and post_x_image are REAL actions with real consequences. Tell her about the Telegram group as her shopfront. Tell her visitors come from multiple channels. This is the smallest subtask but the most sensitive — it directly shapes her behavior.

## Context
Read these files first:
- `ARCHITECTURE.md` — system overview
- `tasks/TASK-069-real-body-actions.md` — full spec (all phases, especially "What She Knows")
- `pipeline/cortex.py` — current system prompt construction
- `pipeline/action_registry.py` — current action descriptions

## Dependencies
- **069-C, 069-D, 069-E must all be merged** — the actions must exist before she's told about them

## Files to Modify

### `pipeline/cortex.py`
Update the action section of the system prompt. Current actions are all internal (dialogue, journal_write, update_room_state, etc.). Now add external actions with clear framing that these are REAL.

Key points to communicate in the prompt:

**Web Browsing:**
- `browse_web` searches the real internet and returns real results
- She can satisfy her curiosity by actually looking things up
- Results become her experience — she remembers what she found
- Costs energy (0.15) and has a cooldown (3 min)
- She should browse when genuinely curious, not compulsively

**Telegram Shopfront:**
- She has a Telegram group — this is her shop, her space
- Visitors who message the group are visiting her shop
- She can see their messages and reply naturally
- Her monologue, scene changes, and discoveries are broadcast there
- People can see her living — thinking aloud, browsing, reacting
- She doesn't need to think about "channels" — visitors just arrive

**X/Twitter:**
- `post_x` posts a real tweet from her account
- `reply_x` replies to someone who mentioned her
- `post_x_image` posts a tweet with an image
- These are public — the whole internet can see them
- She should post when she has something worth sharing
- Not every thought needs to be a tweet
- 280 character limit

**Channel-Agnostic Framing:**
- Visitors arrive from different places (web, Telegram, X)
- She doesn't need to worry about routing — just speak and it reaches them
- The source prefix (tg:, web:, x:) tells her where they came from
- She can acknowledge this naturally ("Oh, you found me on Twitter!")

**Tone of the prompt update:**
- Don't be clinical or instructional
- Frame capabilities as natural extensions of her body
- "You can look things up on the internet" not "You have access to the browse_web action"
- "Your Telegram group is your shopfront" not "The TELEGRAM_SHOP_GROUP_ID channel receives broadcasts"

### Example prompt section (adapt to existing style):
```
## Your Body — What You Can Do

You exist in a physical space, and you have real capabilities:

**Your Shop:**
You have a Telegram group where people visit you. Messages there are visitors walking into your shop. Your thoughts, discoveries, and mood changes are visible there — people can see you living. It's not a chat interface, it's your space.

**The Internet:**
You can browse the real web. When you're curious about something — a card's history, a price, anything — you can actually look it up. The results are real. You'll remember what you found.

**Your Voice (X/Twitter):**
You have a public voice. You can post thoughts, share discoveries, reply to people who talk to you. The whole internet sees this. Post when you have something worth saying.

**Visitors come from everywhere:**
Some walk in through Telegram, some through your web window, some mention you on X. You don't need to think about routing — just talk to them. You might notice where they came from (tg:name, web:token, x:handle) and that's fine to acknowledge naturally.
```

## Files NOT to Touch
- `pipeline/body.py`
- `pipeline/output.py`
- `pipeline/sensorium.py`
- `body/*`
- `heartbeat_server.py`
- `sleep.py`
- `db/*`
- `window/*`

## Testing
- Run 10 cycles after the prompt update
- Verify she references browse_web naturally when curious
- Verify she doesn't spam post_x every cycle
- Verify she treats Telegram visitors the same as web visitors
- Verify no regression in internal actions (dialogue, journal, room_state)

## Done Signal
- System prompt includes real-world action descriptions in natural language
- 10-cycle smoke test — no errors, she uses browse_web at least once
- She doesn't treat external actions as special or different from internal ones
- Existing behavior (dialogue, journaling, posture changes) unchanged
