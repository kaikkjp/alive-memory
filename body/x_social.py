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
from body.rate_limiter import check_rate_limit, record_action, is_channel_enabled
import db


@register('post_x')
async def execute_post_x(action: ActionRequest, visitor_id: str = None,
                         monologue: str = '') -> ActionResult:
    """Post to X live."""
    result = ActionResult(action='post_x', timestamp=clock.now_utc())

    if not await is_channel_enabled('x'):
        result.success = False
        result.error = 'X channel disabled'
        return result

    allowed, reason = await check_rate_limit('post_x')
    if not allowed:
        result.success = False
        result.error = reason
        return result

    text = (action.detail.get('text') or action.detail.get('content', '')).strip()
    if not text:
        result.success = False
        result.error = 'no post text'
        return result

    from body.x_client import post_tweet
    api_result = await post_tweet(text)

    await record_action('post_x', success=api_result.get('success', False),
                        channel='x', error=api_result.get('error'))

    if api_result.get('success'):
        result.payload = {'x_post_id': api_result['x_post_id']}
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

    allowed, reason = await check_rate_limit('reply_x')
    if not allowed:
        result.success = False
        result.error = reason
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
                        channel='x', error=api_result.get('error'))

    if api_result.get('success'):
        result.payload = {'x_post_id': api_result['x_post_id'], 'reply_to': reply_to_id}
        result.side_effects.append('x_reply_sent')
    else:
        result.success = False
        result.error = api_result.get('error', 'reply failed')

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

    allowed, reason = await check_rate_limit('post_x_image')
    if not allowed:
        result.success = False
        result.error = reason
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
                        channel='x', error=api_result.get('error'))

    if api_result.get('success'):
        result.payload = {'x_post_id': api_result['x_post_id']}
        result.side_effects.append('x_image_posted')
    else:
        result.success = False
        result.error = api_result.get('error', 'media post failed')

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

    def __init__(self, poll_interval: int = 120):
        self.poll_interval = poll_interval
        self._running = False
        self._since_id = None

    async def start_polling(self):
        """Background loop: fetch mentions every poll_interval seconds."""
        self._running = True
        print(f"  [XMentions] Polling started (every {self.poll_interval}s)")

        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                print(f"  [XMentions] Poll error: {type(e).__name__}: {e}")

            await asyncio.sleep(self.poll_interval)

    def stop(self):
        self._running = False
        print("  [XMentions] Polling stopped")

    async def _poll_once(self):
        """Fetch mentions and inject as visitor events."""
        from body.x_client import fetch_mentions

        mentions = await fetch_mentions(since_id=self._since_id)
        if not mentions:
            return

        for mention in mentions:
            # Always advance to highest ID to avoid re-processing
            if self._since_id is None or str(mention['id']) > str(self._since_id):
                self._since_id = mention['id']

            visitor_id = f'x_{mention["author_id"]}'

            # Ensure visitor exists
            try:
                visitor = await db.get_visitor(visitor_id)
                if not visitor:
                    await db.insert_visitor(visitor_id, name=f'@{mention["author_id"]}')
            except Exception:
                try:
                    await db.insert_visitor(visitor_id, name=f'@{mention["author_id"]}')
                except Exception:
                    pass

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
