# 069-B: Channel Router + MessageBus

## Goal
Create the channel routing infrastructure. A MessageBus with inbound/outbound asyncio queues, and a ChannelRouter that dispatches outbound messages to the correct channel based on visitor source prefix (`web:`, `tg:`, `x:`). This is infrastructure only — no actual Telegram/X implementations yet, just the routing layer they'll plug into.

## Context
Read these files first:
- `ARCHITECTURE.md` — system overview
- `tasks/TASK-069-real-body-actions.md` — full spec (Architecture section, Channel-Agnostic Design)
- `heartbeat_server.py` — current WebSocket broadcast (this is the existing "web" channel)
- `window_state.py` — current state broadcast
- `models/event.py` — Event dataclass

## Inspiration
nanobot's `bus/queue.py` pattern: two asyncio.Queue (inbound + outbound), typed message envelopes. Simple and proven at scale across 8+ channels. But ours is simpler — we don't need a full pub-sub, just queue + dispatch.

## Files to Create

### `body/bus.py`
```python
@dataclass
class InboundMessage:
    source: str          # "tg:12345", "web:token_abc", "x:cardlover99"
    content: str
    visitor_name: str
    channel: str         # "telegram", "web", "x"
    metadata: dict       # channel-specific (tg: message_id, chat_id; x: tweet_id)
    timestamp: str

@dataclass
class OutboundMessage:
    target: str          # "tg:12345" or "broadcast" for activity
    content: str
    message_type: str    # "dialogue", "monologue", "scene", "image", "activity"
    image_path: str | None = None
    metadata: dict       # channel-specific (tg: reply_to_message_id)

class MessageBus:
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
    
    async def publish_inbound(self, msg: InboundMessage): ...
    async def consume_inbound(self) -> InboundMessage: ...
    async def publish_outbound(self, msg: OutboundMessage): ...
    async def consume_outbound(self) -> OutboundMessage: ...
```

### `body/channels.py`
```python
class ChannelAdapter:
    """Base class for channel implementations (Telegram, Web, X)."""
    channel_name: str
    
    async def send_message(self, target_id: str, content: str, **kwargs): ...
    async def send_image(self, target_id: str, image_path: str, caption: str = ""): ...

class ChannelRouter:
    """Routes outbound messages to the correct channel adapter."""
    
    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.adapters: dict[str, ChannelAdapter] = {}
    
    def register(self, prefix: str, adapter: ChannelAdapter): ...
    
    async def run_dispatcher(self):
        """Background task: consume outbound queue, route to correct adapter."""
        while True:
            msg = await self.bus.consume_outbound()
            if msg.target == "broadcast":
                # Send to ALL active channels
                for adapter in self.adapters.values():
                    await adapter.broadcast(msg)
            else:
                prefix = msg.target.split(":")[0]
                adapter = self.adapters.get(prefix)
                if adapter:
                    await adapter.send_message(msg.target.split(":", 1)[1], msg.content, **msg.metadata)
    
    async def send_dialogue(self, visitor_source: str, text: str, image_path: str = None): ...
    async def broadcast_activity(self, text: str, message_type: str, image_path: str = None): ...
```

### `tests/test_message_bus.py`
- Publish inbound → consume inbound returns same message
- Publish outbound → consume outbound returns same message
- Queue ordering (FIFO)
- Multiple producers/consumers

### `tests/test_channel_router.py`
- Register adapter → messages with matching prefix routed correctly
- Broadcast → all adapters receive message
- Unknown prefix → message logged as unroutable (not crash)
- Mock adapters verify send_message called with correct args

## Files NOT to Touch
- `pipeline/*`
- `heartbeat.py`
- `heartbeat_server.py` (integration comes in 069-D)
- `sleep.py`
- `db/*`
- `window/*`

## Notes
- The existing WebSocket broadcast in `heartbeat_server.py` is effectively a "web" channel adapter. Don't touch it now — 069-D will create a `WebChannelAdapter` that wraps the existing WebSocket broadcast and registers it with the ChannelRouter.
- Keep it simple. Two queues, typed messages, prefix-based dispatch. No pub-sub, no topics, no middleware.

## Done Signal
- MessageBus publishes and consumes messages correctly
- ChannelRouter dispatches by prefix to registered mock adapters
- Broadcast sends to all adapters
- All unit tests pass
- No integration with existing code yet (that's 069-D's job)
