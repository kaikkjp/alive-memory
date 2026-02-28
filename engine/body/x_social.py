"""X/Twitter executors — post, reply, media, mention polling.

Live posting with kill switch.  All actions go through rate limiting
and channel enable checks before making API calls.
"""

from __future__ import annotations

import asyncio
import os

import clock
from models.event import Event
from models.pipeline import ActionRequest, ActionResult
from body.executor import register
from body.rate_limiter import (
    get_limiter_decision,
    is_channel_enabled,
    limiter_payload,
    record_action,
)
from pipeline.ack import on_visitor_connect
import db


class RateLimitError(Exception):
    """Raised when X API returns 429 — carries retry_after hint."""

    def __init__(self, retry_after: int = 900):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after}s")


@register('post_x')
async def execute_post_x(action: ActionRequest, visitor_id: str = None,
                         monologue: str = '') -> ActionResult:
    """Post to X live."""
    result = ActionResult(action='post_x', timestamp=clock.now_utc())

    if not await is_channel_enabled('x'):
        result.success = False
        result.error = 'X channel disabled'
        return result

    limiter = await get_limiter_decision('post_x')
    limiter_meta = limiter_payload(limiter)
    if not limiter['allowed']:
        result.success = False
        result.error = str(limiter['reason'])
        result.payload = dict(limiter_meta)
        return result

    text = (action.detail.get('text') or action.detail.get('content', '')).strip()
    if not text:
        result.success = False
        result.error = 'no post text'
        return result

    from body.x_client import post_tweet
    api_result = await post_tweet(text)

    await record_action('post_x', success=api_result.get('success', False),
                        channel='x', error=api_result.get('error'),
                        **limiter_meta)

    if api_result.get('success'):
        result.payload = {
            'x_post_id': api_result['x_post_id'],
            **limiter_meta,
        }
        result.side_effects.append('x_post_live')

        # Log event
        await db.append_event(Event(
            event_type='action_post_x',
            source='self',
            payload={'x_post_id': api_result['x_post_id'], 'text': text[:280]},
        ))
    else:
        result.success = False
        result.error = api_result.get('error', 'post failed')
        result.payload = dict(limiter_meta)

    return result


@register('reply_x')
async def execute_reply_x(action: ActionRequest, visitor_id: str = None,
                          monologue: str = '') -> ActionResult:
    """Reply to an X mention/tweet."""
    result = ActionResult(action='reply_x', timestamp=clock.now_utc())

    if not await is_channel_enabled('x'):
        result.success = False
        result.error = 'X channel disabled'
        return result

    limiter = await get_limiter_decision('reply_x')
    limiter_meta = limiter_payload(limiter)
    if not limiter['allowed']:
        result.success = False
        result.error = str(limiter['reason'])
        result.payload = dict(limiter_meta)
        return result

    text = (action.detail.get('text') or action.detail.get('content', '')).strip()
    reply_to_id = action.detail.get('reply_to_id', '')
    if not text:
        result.success = False
        result.error = 'no reply text'
        return result
    if not reply_to_id:
        result.success = False
        result.error = 'no reply_to_id'
        return result

    from body.x_client import reply_tweet
    api_result = await reply_tweet(text, reply_to_id)

    await record_action('reply_x', success=api_result.get('success', False),
                        channel='x', error=api_result.get('error'),
                        **limiter_meta)

    if api_result.get('success'):
        result.payload = {
            'x_post_id': api_result['x_post_id'],
            'reply_to': reply_to_id,
            **limiter_meta,
        }
        result.side_effects.append('x_reply_sent')
    else:
        result.success = False
        result.error = api_result.get('error', 'reply failed')
        result.payload = dict(limiter_meta)

    return result


@register('post_x_image')
async def execute_post_x_image(action: ActionRequest, visitor_id: str = None,
                               monologue: str = '') -> ActionResult:
    """Post a tweet with an image."""
    result = ActionResult(action='post_x_image', timestamp=clock.now_utc())

    if not await is_channel_enabled('x'):
        result.success = False
        result.error = 'X channel disabled'
        return result

    limiter = await get_limiter_decision('post_x_image')
    limiter_meta = limiter_payload(limiter)
    if not limiter['allowed']:
        result.success = False
        result.error = str(limiter['reason'])
        result.payload = dict(limiter_meta)
        return result

    text = (action.detail.get('text') or action.detail.get('content', '')).strip()
    image_path = action.detail.get('image_path', '')
    if not image_path:
        result.success = False
        result.error = 'no image_path'
        return result

    from body.x_client import post_tweet_with_media
    api_result = await post_tweet_with_media(text, image_path)

    await record_action('post_x_image', success=api_result.get('success', False),
                        channel='x', error=api_result.get('error'),
                        **limiter_meta)

    if api_result.get('success'):
        result.payload = {
            'x_post_id': api_result['x_post_id'],
            **limiter_meta,
        }
        result.side_effects.append('x_image_posted')
    else:
        result.success = False
        result.error = api_result.get('error', 'media post failed')
        result.payload = dict(limiter_meta)

    return result


async def reply_to_visitor(visitor_id: str, text: str) -> dict:
    """Reply to a visitor via X.

    Called by the channel router. Looks up the visitor's last mention
    tweet ID and replies to it.
    """
    # Look up the visitor's last X interaction to find reply target
    import db.connection as _conn
    try:
        conn = await _conn.get_db()
        cursor = await conn.execute(
            """SELECT payload FROM events
               WHERE source = ? AND event_type = 'visitor_speech'
               ORDER BY ts DESC LIMIT 1""",
            (f'visitor:{visitor_id}',),
        )
        row = await cursor.fetchone()
        if row:
            import json
            payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            tweet_id = payload.get('x_tweet_id')
            if tweet_id:
                from body.x_client import reply_tweet
                return await reply_tweet(text, tweet_id)
    except Exception:
        pass

    return {'success': False, 'error': 'no tweet context for reply'}


class XMentionPoller:
    """Background task that polls X for mentions and injects them as events."""

    def __init__(self, poll_interval: int = 900, heartbeat=None):
        self.poll_interval = poll_interval
        self._heartbeat = heartbeat
        self._current_interval = self.poll_interval
        self._running = False
        self._since_id = None

    async def _restore_since_id(self):
        """Restore since_id from DB to avoid re-ingesting mentions after restart."""
        stored = await db.get_setting('x_mentions_since_id')
        if stored:
            self._since_id = stored
            print(f"  [XMentions] Restored since_id: {stored}")

    async def _persist_since_id(self):
        """Save since_id to DB so it survives restarts."""
        if self._since_id:
            await db.set_setting('x_mentions_since_id', str(self._since_id))

    async def start_polling(self):
        """Background loop: fetch mentions with exponential backoff on errors."""
        self._running = True
        await self._restore_since_id()
        print(f"  [XMentions] Polling started (every {self.poll_interval}s)")

        while self._running:
            try:
                await self._poll_once()
                self._current_interval = self.poll_interval  # reset on success
            except RateLimitError as e:
                self._current_interval = min(e.retry_after * 2, 3600)
                print(f"  [XMentions] Rate limited, backing off to {self._current_interval}s")
            except Exception as e:
                self._current_interval = min(self._current_interval * 2, 3600)
                print(f"  [XMentions] Poll error: {type(e).__name__}: {e}, backing off to {self._current_interval}s")

            await asyncio.sleep(self._current_interval)

    def stop(self):
        self._running = False
        print("  [XMentions] Polling stopped")

    async def _poll_once(self):
        """Fetch mentions and inject as visitor events."""
        from body.x_client import fetch_mentions

        try:
            mentions = await fetch_mentions(since_id=self._since_id)
        except Exception as e:
            # Convert tweepy rate limit errors to our RateLimitError
            try:
                import tweepy
                if isinstance(e, tweepy.TooManyRequests):
                    response = getattr(e, 'response', None)
                    retry_after = 900
                    if response is not None:
                        retry_after = int(response.headers.get('Retry-After', 900))
                    raise RateLimitError(retry_after=retry_after) from e
            except ImportError:
                pass
            raise
        if not mentions:
            return

        for mention in mentions:
            # Always advance to highest ID to avoid re-processing
            if self._since_id is None or str(mention['id']) > str(self._since_id):
                self._since_id = mention['id']

            visitor_id = f'x_{mention["author_id"]}'

            # HOTFIX-005: Create/increment visitor record via on_visitor_connect
            # Previously called db.insert_visitor() which does not exist — AttributeError
            # was silently swallowed by double try/except/pass.
            connect_event = Event(
                event_type='visitor_connect',
                source=f'visitor:{visitor_id}',
                payload={'display_name': f'@{mention["author_id"]}', 'platform': 'x'},
            )
            await on_visitor_connect(connect_event)
            await db.update_visitor(visitor_id, name=f'@{mention["author_id"]}')
            await db.mark_session_boundary(visitor_id)

            await db.add_visitor_present(visitor_id, 'x')

            event = Event(
                event_type='visitor_speech',
                source=f'visitor:{visitor_id}',
                payload={
                    'text': mention['text'],
                    'platform': 'x',
                    'x_tweet_id': mention['id'],
                    'x_author_id': mention['author_id'],
                    'x_conversation_id': mention.get('conversation_id'),
                },
                channel='visitor',
            )
            await db.append_event(event)
            await db.inbox_add(event.id, priority=0.7)
            print(f"  [XMentions] Mention from x_{mention['author_id']}: {mention['text'][:50]}...")

        # Persist high-water mark so restarts don't re-ingest
        await self._persist_since_id()

        # HOTFIX-004: Wake the heartbeat loop once for the batch
        if self._heartbeat:
            await self._heartbeat.schedule_microcycle()
