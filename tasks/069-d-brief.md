# 069-D: Telegram Adapter

## Goal
Implement the Telegram shopfront. Bot joins a public group, polls for messages, injects them as visitor events into the pipeline. Outbound dialogue and activity broadcasts sent back to the group. She lives in this Telegram group — it's her shop. People join and they're in the shop.

## Context
Read these files first:
- `ARCHITECTURE.md` — system overview
- `tasks/TASK-069-real-body-actions.md` — full spec (Phase 3: Telegram Shopfront)
- `body/bus.py` and `body/channels.py` — MessageBus + ChannelRouter (from 069-B, must be merged)
- `heartbeat_server.py` — where to start the polling loop
- `pipeline/sensorium.py` — event processing (verify visitor_message handling)
- `db/memory.py` — visitor table (needs channel columns)
- `models/event.py` — Event dataclass

## Dependencies
- **069-B must be merged** — you need MessageBus and ChannelRouter

## Telegram Bot API Reference
- `getUpdates` — long-poll for new messages (timeout=30s)
- `sendMessage` — send text (supports parse_mode="Markdown", reply_to_message_id)
- `sendPhoto` — send image with optional caption
- `getMe` — get bot info (id, username)
- Base URL: `https://api.telegram.org/bot{token}/`
- All responses: `{"ok": true, "result": ...}`

## Files to Create

### `body/tg_client.py`
Low-level Telegram Bot API client using httpx:
```python
class TelegramClient:
    BASE_URL = "https://api.telegram.org/bot{token}"
    
    def __init__(self, token: str):
        self.base_url = self.BASE_URL.format(token=token)
        self.client = httpx.AsyncClient(timeout=60)  # long-poll needs longer timeout
    
    async def get_updates(self, offset=0, timeout=30) -> list[dict]: ...
    async def send_message(self, chat_id, text, reply_to_message_id=None, parse_mode="Markdown") -> dict: ...
    async def send_photo(self, chat_id, photo_path, caption=None) -> dict: ...
    async def get_me(self) -> dict: ...
```

Handle Markdown escaping — Telegram Markdown v1 is finicky. Escape special chars or fall back to plain text on parse error.

### `body/telegram.py`
High-level adapter that bridges Telegram ↔ Shopkeeper event system:
```python
class TelegramAdapter(ChannelAdapter):
    channel_name = "telegram"
    
    def __init__(self, bot_token, group_id, bus: MessageBus, db):
        self.client = TelegramClient(bot_token)
        self.group_id = group_id
        self.bus = bus
        self.db = db
        self.bot_id = None  # set on startup via get_me
        self.offset = 0
    
    async def start(self):
        me = await self.client.get_me()
        self.bot_id = me["id"]
        # Start polling loop
        asyncio.create_task(self._poll_loop())
    
    async def _poll_loop(self):
        while True:
            try:
                updates = await self.client.get_updates(offset=self.offset, timeout=30)
                for update in updates:
                    self.offset = update["update_id"] + 1
                    await self._handle_update(update)
            except Exception as e:
                logger.error(f"Telegram poll error: {e}")
                await asyncio.sleep(5)  # backoff on error
    
    async def _handle_update(self, update):
        message = update.get("message")
        if not message or not message.get("text"):
            return
        if message["from"]["id"] == self.bot_id:
            return  # skip own messages
        
        user = message["from"]
        visitor_source = f"tg:{user['id']}"
        visitor_name = user.get("first_name", "Anonymous")
        
        # Ensure visitor exists in DB
        await self._ensure_visitor(user)
        
        # Publish to inbound bus
        await self.bus.publish_inbound(InboundMessage(
            source=visitor_source,
            content=message["text"],
            visitor_name=visitor_name,
            channel="telegram",
            metadata={
                "chat_id": message["chat"]["id"],
                "message_id": message["message_id"],
            },
            timestamp=datetime.utcnow().isoformat(),
        ))
    
    # Also handle: new_chat_member (visitor_connect), left_chat_member (visitor_disconnect)
    
    async def send_message(self, target_id, content, **kwargs):
        chat_id = self.group_id  # always send to group
        reply_to = kwargs.get("reply_to_message_id")
        await self.client.send_message(chat_id, content, reply_to_message_id=reply_to)
    
    async def send_image(self, target_id, image_path, caption=""):
        await self.client.send_photo(self.group_id, image_path, caption=caption)
    
    async def broadcast(self, msg: OutboundMessage):
        """Broadcast activity to the group."""
        prefix = {
            "monologue": "💭 ",
            "scene": "",       # italic via Markdown
            "activity": "🔍 ",
            "image": "",
        }.get(msg.message_type, "")
        
        if msg.message_type == "scene":
            text = f"_{msg.content}_"  # italic for narration
        else:
            text = f"{prefix}{msg.content}"
        
        if msg.image_path:
            await self.send_image(self.group_id, msg.image_path, caption=text)
        else:
            await self.send_message(self.group_id, text)
```

### `migrations/069d_visitor_channels.sql`
```sql
ALTER TABLE visitors ADD COLUMN channel TEXT DEFAULT 'web';
ALTER TABLE visitors ADD COLUMN channel_id TEXT;
ALTER TABLE visitors ADD COLUMN display_name TEXT;
ALTER TABLE visitors ADD COLUMN avatar_url TEXT;
```

### `tests/test_tg_client.py`
- Mock httpx responses for getUpdates, sendMessage, sendPhoto, getMe
- Verify correct URL construction and payload
- Handle API error responses ({"ok": false, "description": "..."})
- Long timeout on getUpdates

### `tests/test_telegram_adapter.py`
- Message received → InboundMessage published to bus with correct source/channel
- Bot's own messages skipped
- New member join → visitor_connect event
- Member leave → visitor_disconnect event
- send_message routes to group with correct chat_id
- broadcast formats monologue with 💭, scene with italic, activity with 🔍
- Visitor created in DB on first message

## Files to Modify

### `heartbeat_server.py`
In the server startup section, add:
```python
if os.getenv("TELEGRAM_BOT_TOKEN"):
    from body.telegram import TelegramAdapter
    tg_adapter = TelegramAdapter(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        group_id=os.getenv("TELEGRAM_SHOP_GROUP_ID"),
        bus=message_bus,  # or however the bus is accessible
        db=db,
    )
    await tg_adapter.start()
    channel_router.register("tg", tg_adapter)
    logger.info(f"Telegram bot connected to group {os.getenv('TELEGRAM_SHOP_GROUP_ID')}")
```

Also need to bridge InboundMessage → Event for the existing pipeline:
```python
# Background task: consume from bus.inbound, push to heartbeat event queue
async def inbound_bridge():
    while True:
        msg = await message_bus.consume_inbound()
        await heartbeat.push_event(Event(
            type="visitor_message",
            source=msg.source,
            payload={
                "content": msg.content,
                "visitor_name": msg.visitor_name,
                "channel": msg.channel,
                **msg.metadata,
            }
        ))
```

### `pipeline/sensorium.py`
Verify that `visitor_message` events with `channel="telegram"` are handled correctly. The sensorium should be channel-agnostic — it processes the event regardless of source. If there's any web-specific assumption, fix it.

### `db/memory.py`
Add visitor channel columns (migration above). Update `create_visitor()` and `get_visitor()` to use channel + channel_id.

### `pipeline/output.py`
When dialogue is emitted, publish to outbound bus instead of (or in addition to) the existing WebSocket broadcast:
```python
# After she speaks to a visitor
await message_bus.publish_outbound(OutboundMessage(
    target=visitor_source,  # "tg:12345"
    content=dialogue_text,
    message_type="dialogue",
    metadata={"reply_to_message_id": original_message_id},
))
```

For activity broadcasts (monologue, scene changes):
```python
await message_bus.publish_outbound(OutboundMessage(
    target="broadcast",
    content=monologue_text,
    message_type="monologue",
))
```

## Files NOT to Touch
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `pipeline/hypothalamus.py`
- `body/web.py` (069-C scope)
- `body/x_*.py` (069-E scope)
- `sleep.py`

## Environment Variables Needed
```bash
TELEGRAM_BOT_TOKEN=...              # from @BotFather
TELEGRAM_SHOP_GROUP_ID=...          # group chat ID (negative number for groups)
```

The operator (Heo) will create the bot and group before you start. Ask if these aren't in .env.

## Presence Model
- Message in group → visitor is present (or reconnects if idle timeout passed)
- No message for 30 min → visitor_disconnect (use existing idle timeout logic)
- New member joins → visitor_connect event
- She's sleeping → messages queue in the bus, processed on wake

## Done Signal
- Bot connects to Telegram (getMe succeeds)
- Messages in group → InboundMessage on bus → Event in pipeline → she responds
- Response sent back to group (sendMessage with reply_to)
- Activity broadcasts appear in group (monologue with 💭, scene with italic)
- Images/sprites sent via sendPhoto
- Visitor records created with channel="telegram"
- Mock tests pass
- Manual test: send message in real Telegram group, she responds
