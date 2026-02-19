# 069-E: X/Twitter Client + Executors

## Goal
Implement X API v2 client (httpx, no tweepy dependency) and three executors: PostX, ReplyX, PostXImage. Plus a background mention-fetch timer that injects mentions as visitor events. Replace the existing `workers/x_poster.py` tweepy implementation.

## Context
Read these files first:
- `ARCHITECTURE.md` — system overview
- `tasks/TASK-069-real-body-actions.md` — full spec (Phase 4: X/Twitter)
- `body/executor.py` — executor interface (from 069-A, must be merged)
- `workers/x_poster.py` — current tweepy implementation (being replaced)
- `pipeline/action_registry.py` — action capability definitions
- `pipeline/sensorium.py` — event handling (for x_mention events)

## Dependencies
- **069-A must be merged** — you need the `BodyExecutor` base class

## X API v2 Reference
- Auth: OAuth 2.0 Bearer Token (for read) + OAuth 1.0a (for write/media)
- `POST https://api.x.com/2/tweets` — create tweet
  - Body: `{"text": "...", "reply": {"in_reply_to_tweet_id": "..."}, "media": {"media_ids": ["..."]}}`
- `GET https://api.x.com/2/users/:id/mentions` — get mentions
  - Query: `since_id`, `max_results`, `tweet.fields=author_id,created_at,in_reply_to_user_id`
- `POST https://upload.x.com/1.1/media/upload.json` — upload media (still v1.1)
  - Multipart form: `media_data` (base64) or `media` (binary)
  - Returns: `media_id_string`
- Rate limits: 100 tweets/24h (free tier), mentions polling: 10 req/15min

## Files to Create

### `body/x_client.py`
```python
class XClient:
    def __init__(self, bearer_token, api_key, api_secret, access_token, access_token_secret):
        # Bearer for read endpoints
        self.read_client = httpx.AsyncClient(
            base_url="https://api.x.com/2",
            headers={"Authorization": f"Bearer {bearer_token}"}
        )
        # OAuth 1.0a for write endpoints — use authlib or manual signing
        # (tweepy handled this, now we do it ourselves)
        self.write_auth = OAuth1Auth(api_key, api_secret, access_token, access_token_secret)
    
    async def post_tweet(self, content: str, reply_to: str = None, media_ids: list[str] = None) -> dict:
        payload = {"text": content}
        if reply_to:
            payload["reply"] = {"in_reply_to_tweet_id": reply_to}
        if media_ids:
            payload["media"] = {"media_ids": media_ids}
        resp = await self.write_client.post("/2/tweets", json=payload)
        resp.raise_for_status()
        return resp.json()["data"]
    
    async def upload_media(self, image_path: str) -> str:
        # v1.1 media upload endpoint
        with open(image_path, "rb") as f:
            resp = await self.write_client.post(
                "https://upload.x.com/1.1/media/upload.json",
                files={"media": f}
            )
        resp.raise_for_status()
        return resp.json()["media_id_string"]
    
    async def get_mentions(self, user_id: str, since_id: str = None, max_results: int = 20) -> list[dict]:
        params = {"max_results": max_results, "tweet.fields": "author_id,created_at,text"}
        if since_id:
            params["since_id"] = since_id
        resp = await self.read_client.get(f"/2/users/{user_id}/mentions", params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
    
    async def get_me(self) -> dict:
        resp = await self.read_client.get("/2/users/me")
        return resp.json()["data"]
```

Note on OAuth 1.0a: X API v2 write endpoints require OAuth 1.0a user context. Options:
1. Use `authlib` library (add to requirements.txt)
2. Use `requests-oauthlib` (sync, wrap in async)
3. Manual HMAC-SHA1 signing (complex but no deps)

Recommend option 1 (`authlib`) — it supports async httpx natively.

### `body/x_social.py`
```python
class PostXExecutor(BodyExecutor):
    action_name = "post_x"
    requires_energy = 0.10
    cooldown_seconds = 300
    requires_online = True
    
    async def execute(self, intention, context) -> ActionResult:
        content = intention.parameters["content"]
        if len(content) > 280:
            content = content[:277] + "..."
        tweet = await x_client.post_tweet(content)
        return ActionResult(
            success=True,
            action_name="post_x",
            data={"tweet_id": tweet["id"], "content": content}
        )

class ReplyXExecutor(BodyExecutor):
    action_name = "reply_x"
    requires_energy = 0.08
    cooldown_seconds = 120
    
    async def execute(self, intention, context) -> ActionResult:
        tweet = await x_client.post_tweet(
            content=intention.parameters["content"],
            reply_to=intention.parameters["mention_id"],
        )
        return ActionResult(success=True, ...)

class PostXImageExecutor(BodyExecutor):
    action_name = "post_x_image"
    requires_energy = 0.20
    cooldown_seconds = 600
    
    async def execute(self, intention, context) -> ActionResult:
        media_id = await x_client.upload_media(intention.parameters["image_path"])
        tweet = await x_client.post_tweet(
            content=intention.parameters["content"],
            media_ids=[media_id],
        )
        return ActionResult(success=True, ...)
```

### `tests/test_x_client.py`
- Mock httpx responses for post_tweet, get_mentions, upload_media, get_me
- Verify correct URL/payload construction
- Handle API errors (rate limit 429, auth failure 401)
- Character truncation at 280

### `tests/test_x_social.py`
- PostXExecutor: mock client → returns tweet_id
- ReplyXExecutor: reply_to included in payload
- PostXImageExecutor: media upload then tweet with media_ids
- Energy gate: can_execute fails when energy low
- Cooldown: can_execute fails during cooldown

## Files to Modify

### `pipeline/action_registry.py`
Add entries:
```python
"post_x": ActionCapability(name="post_x", energy_cost=0.10, cooldown_seconds=300, category="external", enabled=True),
"reply_x": ActionCapability(name="reply_x", energy_cost=0.08, cooldown_seconds=120, prerequisites=["has_pending_mention"], category="external", enabled=True),
"post_x_image": ActionCapability(name="post_x_image", energy_cost=0.20, cooldown_seconds=600, category="external", enabled=True),
```

### `pipeline/output.py`
Handle X action results:
```python
if result.action_name == "post_x" and result.success:
    drives.expression_need = max(0, drives.expression_need - 0.3)
    # Log cost: $0.01 per post
    await log_cost(service="x_api", cost_usd=0.01, ...)

if result.action_name == "reply_x" and result.success:
    drives.social_hunger = max(0, drives.social_hunger - 0.1)
```

### `pipeline/sensorium.py`
Handle `x_mention` event type:
```python
# In event classification
if event.type == "x_mention":
    return Perception(
        type="social",
        source=event.source,  # "x:username"
        content=event.payload["content"],
        salience=0.6,  # mentions are moderately salient
        channel="x",
    )
```

### `heartbeat_server.py`
Add mention fetch background timer:
```python
if os.getenv("X_BEARER_TOKEN"):
    x_client = XClient(...)
    x_user = await x_client.get_me()
    last_mention_id = None  # persist to DB or file
    
    async def fetch_mentions_loop():
        nonlocal last_mention_id
        while True:
            try:
                mentions = await x_client.get_mentions(x_user["id"], since_id=last_mention_id)
                for mention in mentions:
                    last_mention_id = mention["id"]
                    await heartbeat.push_event(Event(
                        type="x_mention",
                        source=f"x:{mention.get('author_username', mention['author_id'])}",
                        payload={"tweet_id": mention["id"], "content": mention["text"], "channel": "x"},
                    ))
            except Exception as e:
                logger.error(f"X mention fetch error: {e}")
            await asyncio.sleep(120)  # every 2 min
    
    asyncio.create_task(fetch_mentions_loop())
```

### `requirements.txt`
Add `authlib` for OAuth 1.0a signing (if not already present).
Remove `tweepy` if no other code uses it.

## Files NOT to Touch
- `pipeline/cortex.py` (069-F scope)
- `body/telegram.py` (069-D scope)
- `body/web.py` (069-C scope)
- `sleep.py`
- `window/*`

## Environment Variables Needed
```bash
X_BEARER_TOKEN=...
X_API_KEY=...
X_API_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...
```

## Done Signal
- XClient posts real tweets via API v2
- XClient fetches mentions
- XClient uploads media
- PostXExecutor, ReplyXExecutor, PostXImageExecutor all work with mocks
- Mentions injected as x_mention events into pipeline
- expression_need decreases after posting
- social_hunger decreases after replying
- Cost logged as service="x_api"
- All tests pass
- Manual test: post a real tweet, fetch real mentions (if credentials available)
