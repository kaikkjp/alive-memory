# TASK-069: Real-World Body Actions — Web Browse + Telegram Shopfront + X Social

## Overview

The Shopkeeper's body currently fakes all external actions — `browse_web` resolves to reading from a pre-loaded content pool, `post_x_draft` queues for human review, and visitors can only reach her through a custom web UI with token gates. This task makes her actions real and opens her shop to the world.

Three channels, one mind:
- **Web window** — existing visual experience (view + chat, stays as-is)
- **Telegram group** — the open shopfront. Anyone can walk in. She's present, living, talking.
- **X/Twitter** — her public voice. She posts, replies, builds an audience.

**Architectural principle:** The body is an API gateway. The cortex never touches external services. Body executors handle API calls, error handling, rate limits, and physical inhibitions. Channel adapters translate between platform-specific formats and the universal event/dialogue system. The cognitive pipeline is channel-agnostic.

---

## Architecture

### Channel-Agnostic Design

```
                    ┌─ Web WebSocket ─────┐
                    │                     │
Visitors arrive via ├─ Telegram Bot API ──┤──→ Event(type="visitor_message")
                    │                     │        source="web:token_abc"
                    └─ X Mentions ────────┘        source="tg:user_123"
                                                   source="x:handle_456"
                                                        │
                                                        ▼
                                              ┌─── Sensorium ───┐
                                              │  (channel-blind) │
                                              └────────┬────────┘
                                                       │
                                              Same pipeline as always
                                              (gates → affect → cortex → body)
                                                       │
                                                       ▼
                                              ┌─── Body Output ──┐
                                              │ Route reply back  │
                                              │ via source channel │
                                              └───────────────────┘
                                                       │
                                    ┌──────────────────┼──────────────────┐
                                    ▼                  ▼                  ▼
                              Web WebSocket    Telegram send_msg    X post_reply
```

**Key insight:** She doesn't know where visitors come from. A Telegram user, a web visitor, and an X reply all look identical to her sensorium — "someone said something to me." The body routes responses back through the originating channel.

### Current Flow
```
Cortex → intentions[] → Basal Ganglia (gates) → Body (fake execution) → Output
```

### New Flow
```
Cortex → intentions[] → Basal Ganglia (gates) → Body (real execution) → Output

Body executors:
  browse_web      → OpenRouter LLM + web_search tool → content experience
  post_x          → X API v2 → live tweet
  reply_x         → X API v2 → live reply
  post_x_image    → X API v2 + media upload → tweet with image
  fetch_mentions  → X API v2 → visitor events from replies/mentions
  tg_send         → Telegram Bot API → message to group/DM
  tg_send_image   → Telegram Bot API → image to group/DM
  tg_send_scene   → Telegram Bot API → sprite/scene composite to group
```

---

## Phase 1: Body Executor Framework

### New: `body/` package

Extract body execution from `pipeline/body.py` into a package with pluggable executors.

```
body/
  __init__.py          # re-exports for backward compat
  executor.py          # base executor interface + registry
  internal.py          # existing internal actions (dialogue, journal, room_state, etc.)
  web.py               # browse_web executor
  x_social.py          # X/Twitter executors (post, reply, image, fetch_mentions)
  x_client.py          # X API v2 httpx client
  telegram.py          # Telegram bot adapter (inbound + outbound)
  tg_client.py         # Telegram Bot API httpx client
  rate_limiter.py      # per-action rate limiting (separate from basal ganglia cooldowns)
  channels.py          # channel routing: source → reply method
```

### Executor Interface

```python
class BodyExecutor:
    """Base class for body action executors."""
    
    action_name: str              # registry key
    requires_energy: float        # minimum energy to execute
    cooldown_seconds: int         # minimum time between executions
    requires_online: bool = True  # needs network access
    
    async def can_execute(self, context: ActionContext) -> tuple[bool, str]:
        """Physical inhibition check. Returns (can_do, reason_if_not)."""
        ...
    
    async def execute(self, intention: ActionDecision, context: ActionContext) -> ActionResult:
        """Execute the action. Returns result with success/failure + data."""
        ...
```

### Channel Router

```python
# body/channels.py
class ChannelRouter:
    """Routes dialogue output back to the originating channel."""
    
    async def send_dialogue(self, visitor_source: str, text: str, image_path: str = None):
        prefix, channel_id = visitor_source.split(":", 1)
        
        if prefix == "web":
            await self.web_broadcast(text, image_path)
        elif prefix == "tg":
            await self.tg_client.send_message(channel_id, text)
            if image_path:
                await self.tg_client.send_photo(channel_id, image_path)
        elif prefix == "x":
            # X replies handled by reply_x executor, not channel router
            pass
    
    async def broadcast_activity(self, text: str, image_path: str = None):
        """Broadcast non-dialogue activity (monologue, scene changes) to all channels."""
        await self.web_broadcast(text, image_path)
        await self.tg_broadcast(text, image_path)  # to the public group
```

---

## Phase 2: Web Browse — OpenRouter + Web Search

### How It Works

1. Cortex outputs intention: `browse_web` with parameters `{"query": "vintage 1998 Bandai Carddass pricing"}`
2. Basal ganglia gates pass (energy, cooldown, not inhibited)
3. Body executor `WebBrowseExecutor.execute()`:
   a. Calls OpenRouter with a **cheap/fast model** (e.g., `google/gemini-2.0-flash`) + `web_search` tool enabled
   b. System prompt: "You are a research assistant. Search the web for the given query. Return a concise summary (max 500 words) of what you found, including key facts, prices, dates. Include source URLs."
   c. Parse response → structured `BrowseResult(summary, sources[], key_facts[])`
4. Output stage:
   a. Log to journal: "I looked up {query} and learned: {summary}"
   b. Update drives: `curiosity` decreases (satisfied), `energy` decreases (cost of browsing)
   c. Store in `browse_history` table for future reference
   d. If epistemic curiosity matches → mark as partially/fully resolved

### OpenRouter Web Search Call

```python
# body/web.py
async def execute(self, intention, context):
    response = await llm_client.call(
        model="google/gemini-2.0-flash",       # cheap, fast, has web search
        call_site="body.browse_web",
        messages=[{
            "role": "user",
            "content": f"Search the web for: {intention.parameters['query']}\n\n"
                       f"Context: I'm curious about this because: {intention.parameters.get('reason', 'general interest')}\n\n"
                       f"Return a concise summary (max 500 words) with key facts and source URLs."
        }],
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search"
        }],
        max_tokens=1000,
    )
    
    summary = extract_text(response)
    sources = extract_urls(response)
    
    return ActionResult(
        success=True,
        action_name="browse_web",
        data={
            "query": intention.parameters["query"],
            "summary": summary,
            "sources": sources,
            "model": "google/gemini-2.0-flash",
        }
    )
```

### Cost Control

- Model: cheapest that supports web search (Gemini Flash ~$0.10/1M input, $0.40/1M output)
- Max 20 browse actions per hour
- Max tokens: 1000 output (keeps cost per browse < $0.01)
- Energy cost: 0.15 per browse (she can't browse when exhausted)

### Browse History Table

```sql
CREATE TABLE browse_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    query TEXT NOT NULL,
    summary TEXT NOT NULL,
    sources TEXT,          -- JSON array of URLs
    cycle_id INTEGER,
    cost_usd REAL,
    model TEXT
);
```

---

## Phase 3: Telegram Shopfront

### Concept

The Telegram group IS the shop. Not a chatbot. Not a support channel. A living space where she exists, thinks out loud, reacts to visitors, browses the web, and shares what she finds. People join the group and they're in the shop.

### Bot Setup

- Create bot via @BotFather
- Bot joins a public group as admin (so it can read all messages)
- Bot token stored as env var: `TELEGRAM_BOT_TOKEN`
- Group chat ID stored as env var: `TELEGRAM_SHOP_GROUP_ID`

### Inbound: Messages → Events

```python
# body/telegram.py
class TelegramAdapter:
    """Bridges Telegram Bot API ↔ Shopkeeper event system."""
    
    def __init__(self, bot_token: str, group_id: str, event_queue):
        self.client = TelegramClient(bot_token)
        self.group_id = group_id
        self.event_queue = event_queue
        self.offset = 0
    
    async def poll_updates(self):
        """Long-poll Telegram for new messages. Run in background task."""
        updates = await self.client.get_updates(offset=self.offset, timeout=30)
        
        for update in updates:
            self.offset = update["update_id"] + 1
            message = update.get("message")
            if not message or not message.get("text"):
                continue
            
            if message["from"]["id"] == self.bot_id:
                continue
            
            user = message["from"]
            visitor_name = user.get("first_name", "Anonymous")
            visitor_source = f"tg:{user['id']}"
            
            await self._ensure_visitor(user)
            
            await self.event_queue.push_event(Event(
                type="visitor_message",
                source=visitor_source,
                payload={
                    "content": message["text"],
                    "visitor_name": visitor_name,
                    "channel": "telegram",
                    "chat_id": message["chat"]["id"],
                    "message_id": message["message_id"],
                }
            ))
```

### Outbound: Dialogue → Telegram

When the cortex produces dialogue for a Telegram visitor, the channel router sends it:

```python
async def send_to_telegram(self, chat_id: str, text: str, reply_to: int = None):
    await self.tg_client.send_message(
        chat_id=chat_id,
        text=text,
        reply_to_message_id=reply_to,
        parse_mode="Markdown",
    )
```

### Activity Broadcasting

She's not just reactive — she lives in the group:

```python
# Triggered from pipeline/output.py after each cycle

# Inner monologue (when she chooses to think aloud)
await tg.send_message(group_id, f"💭 {monologue_text}")

# Scene changes (posture, mood shifts)  
await tg.send_message(group_id, f"*{scene_description}*")

# Browse results she wants to share
await tg.send_message(group_id, f"🔍 I just looked up something interesting...\n\n{browse_summary}")

# Sprite/scene updates
if new_sprite_generated:
    await tg.send_photo(group_id, sprite_path, caption=scene_caption)

# Generated art
if image_generated:
    await tg.send_photo(group_id, image_path, caption=art_caption)
```

### What the Group Looks Like

```
┌─────────────────────────────────────────┐
│  🏪 The Shopkeeper                       │
│                                          │
│  *She adjusts some items on the shelf,   │
│   humming quietly*                       │
│                                          │
│  💭 That Bandai Carddass set has been    │
│  on my mind all morning...               │
│                                          │
│  🔍 I just looked up vintage 1998       │
│  Carddass pricing — seems like the       │
│  Dragon Ball Z holographic set is going  │
│  for ¥45,000 on Yahoo Auctions now.     │
│                                          │
│  [User Tanaka]: Hey, I have some old     │
│  Carddass from my childhood!             │
│                                          │
│  Oh? What series? I'd love to hear       │
│  about them. The early Bandai prints     │
│  had such distinctive art...             │
│                                          │
│  [📷 Scene: Night, shopkeeper examining  │
│   a card under lamplight]                │
│                                          │
│  *She carefully places the card back     │
│   and stretches*                         │
│                                          │
│  💭 I should rest soon. It's getting     │
│  late...                                 │
│                                          │
│  [User Marco]: Is the shop still open?   │
│                                          │
│  Still here! Though I might close up     │
│  soon. What brings you in tonight?       │
└─────────────────────────────────────────┘
```

### Visitor Identity Mapping

```sql
ALTER TABLE visitors ADD COLUMN channel TEXT DEFAULT 'web';
ALTER TABLE visitors ADD COLUMN channel_id TEXT;
ALTER TABLE visitors ADD COLUMN display_name TEXT;
ALTER TABLE visitors ADD COLUMN avatar_url TEXT;
```

### Group Presence Model

- **Message in group** → visitor walks in (or is already in)
- **No message for 30 min** → visitor has left (idle timeout)
- **New member joins** → `visitor_connect` event, she can greet them
- **Member leaves** → `visitor_disconnect` event
- **She's sleeping** → bot still receives messages, queues them, she processes on wake

### Telegram Client

```python
# body/tg_client.py
class TelegramClient:
    BASE_URL = "https://api.telegram.org/bot{token}"
    
    def __init__(self, token: str):
        self.base_url = self.BASE_URL.format(token=token)
        self.client = httpx.AsyncClient()
    
    async def get_updates(self, offset=0, timeout=30) -> list[dict]: ...
    async def send_message(self, chat_id, text, reply_to_message_id=None, parse_mode="Markdown") -> dict: ...
    async def send_photo(self, chat_id, photo_path, caption=None) -> dict: ...
    async def get_me(self) -> dict: ...
```

### Integration with heartbeat_server.py

```python
if os.getenv("TELEGRAM_BOT_TOKEN"):
    tg_adapter = TelegramAdapter(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        group_id=os.getenv("TELEGRAM_SHOP_GROUP_ID"),
        event_queue=heartbeat.event_queue,
    )
    asyncio.create_task(tg_adapter.run_polling_loop())
    channel_router.register("tg", tg_adapter)
```

### What She Can Do in Telegram

| Action | Trigger | What happens in group |
|--------|---------|----------------------|
| Dialogue | Visitor speaks to her | She replies (quoting their message) |
| Monologue | Idle cycle, thinks aloud | 💭 emoji + thought text |
| Scene narration | Body state change | *Italic narration* |
| Browse result | She browses web | 🔍 Summary of findings |
| Share image | Generates art/sprite | Photo message with caption |
| Sleep announce | Sleep cycle starts | "Good night..." + scene image |
| Wake announce | Wake cycle | "Good morning..." + scene image |

### What She CANNOT Do in Telegram

- Delete messages (she said it, it's said)
- Pin messages (operator-only)
- Ban users (operator-only)
- Read message history before bot joined

---

## Phase 4: X/Twitter — Autonomous Social

### API Setup

- X API v2 with OAuth 2.0 (User Context)
- Pay-per-use: $0.01/post
- Endpoints: POST /2/tweets, GET /2/users/:id/mentions, POST /1.1/media/upload

### Replace tweepy with httpx

```python
# body/x_client.py
class XClient:
    def __init__(self, bearer_token: str):
        self.client = httpx.AsyncClient(
            base_url="https://api.x.com/2",
            headers={"Authorization": f"Bearer {bearer_token}"}
        )
    
    async def post_tweet(self, content, media_ids=None, reply_to=None) -> dict: ...
    async def upload_media(self, image_path) -> str: ...
    async def get_mentions(self, since_id=None, max_results=20) -> list[dict]: ...
```

### Executors

- `post_x` — cooldown 5 min, energy 0.10, 280 char limit enforced at body level
- `reply_x` — cooldown 2 min, energy 0.08, requires pending mention
- `post_x_image` — cooldown 10 min, energy 0.20, media upload + tweet

### Mention → Visitor Event Flow

```
X mention → fetch_mentions (timer) → Event(type="x_mention", source="x:username")
  → Sensorium → Thalamus → Cortex → Body → reply_x
```

---

## Phase 5: Cortex Prompt Updates

Tell her what's real:

```
## Real-World Actions

You can interact with the real world. These actions have real consequences.

### browse_web
Search the internet. Real search results from the live web.
Parameters: {"query": "search query", "reason": "why you're curious"}

### post_x
Post to your X/Twitter account. Your followers see this.
Parameters: {"content": "tweet text (max 280 chars)"}

### reply_x
Reply to an X mention.
Parameters: {"mention_id": "tweet_id", "content": "reply text"}

### post_x_image
Post a tweet with a generated image.
Parameters: {"content": "tweet text", "image_path": "path"}

### Visitors
People visit through your web shop window, the Telegram group, and X mentions.
You don't need to think about channels. Just talk to them.

The Telegram group is your open shopfront. People join and they're in the shop.
Think aloud, share findings, show images. It's your living space. Be present.

These are REAL. A tweet cannot be unsaid. A message is seen by everyone.
```

---

## Phase 6: Dashboard Controls

### External Actions Panel (new)

- Toggle each action + channel on/off
- Recent activity per channel
- Rate limit status + cost today
- Kill switch: disable all external actions immediately
- Telegram group link + member count
- X account link

---

## Scope

### Files to create:
- `body/__init__.py`
- `body/executor.py` — base executor + registry
- `body/internal.py` — extract existing internal actions
- `body/web.py` — WebBrowseExecutor
- `body/x_social.py` — PostX, ReplyX, PostXImage
- `body/x_client.py` — X API v2 httpx client
- `body/telegram.py` — Telegram adapter
- `body/tg_client.py` — Telegram Bot API client
- `body/channels.py` — channel router
- `body/rate_limiter.py` — per-action rate limiting
- `migrations/069_real_body_actions.sql`
- `window/src/components/dashboard/ExternalActionsPanel.tsx`
- `tests/test_web_browse.py`
- `tests/test_x_social.py`
- `tests/test_telegram_adapter.py`
- `tests/test_tg_client.py`
- `tests/test_body_executor.py`
- `tests/test_channel_router.py`
- `tests/test_rate_limiter.py`

### Files to modify:
- `pipeline/body.py` — delegate to body/executor.py
- `pipeline/action_registry.py` — add new actions
- `pipeline/output.py` — handle results, activity broadcast
- `pipeline/sensorium.py` — handle x_mention and tg_message events
- `pipeline/cortex.py` — update action prompt section
- `heartbeat_server.py` — TG polling, mention fetch, channel router init
- `api/dashboard_routes.py` — external actions endpoints
- `db/analytics.py` — extend cost logging
- `db/memory.py` — visitor channel columns
- `llm/client.py` — web_search tool support
- `requirements.txt`

### Files NOT to touch:
- `pipeline/basal_ganglia.py`
- `pipeline/hypothalamus.py`
- `pipeline/thalamus.py`
- `sleep.py`
- `simulate.py`

---

## Build Order

1. Body executor framework (`body/` package, registry, backward-compat)
2. Channel router (source-based reply routing)
3. Web browse executor (OpenRouter + web_search)
4. Telegram adapter (bot polling, event injection, messaging, images)
5. X client + executors (post, reply, media, mention fetch)
6. Cortex prompt update
7. Dashboard panel
8. Integration test (50 cycles, all channels)

---

## Safety / Rate Limits

| Action | Max/hour | Max/day | Energy | Cooldown |
|--------|----------|---------|--------|----------|
| browse_web | 20 | 100 | 0.15 | 3 min |
| post_x | 12 | 50 | 0.10 | 5 min |
| reply_x | 30 | 100 | 0.08 | 2 min |
| post_x_image | 6 | 20 | 0.20 | 10 min |
| tg_send | 60 | 500 | 0.02 | 5 sec |
| tg_send_image | 20 | 100 | 0.05 | 30 sec |

**Daily cost estimate: ~$0.75** (Telegram is free)

---

## Environment Variables

```bash
OPENROUTER_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_SHOP_GROUP_ID=...
X_BEARER_TOKEN=...
X_API_KEY=...
X_API_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...
```

---

## Definition of Done

1. `browse_web` performs real web search via OpenRouter + web_search tool
2. Browse results become immediate experience (journal, memory, drive update)
3. `post_x` posts real tweets
4. `reply_x` replies to real mentions
5. `post_x_image` posts tweets with generated images
6. X mentions auto-fetched as visitor events
7. Telegram bot polls group messages as visitor events
8. She replies in Telegram group with message quotes
9. Activity broadcasts (monologue, scenes, browse results) appear in Telegram group
10. Sprites/images sent to Telegram on visual state changes
11. Channel router correctly routes replies to originating channel
12. All external actions logged with cost tracking
13. Dashboard shows action status, channel status, cost, kill switch
14. Rate limits enforced at body level
15. 50-cycle integration test — no errors, costs tracked
16. Operator can disable any/all actions and channels via dashboard
