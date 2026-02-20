"""Telegram adapter — polling loop, event injection, executors.

The adapter polls a Telegram group for messages, converts them to
visitor events, and injects them into the inbox.  Executors handle
sending replies and images back to the group.
"""

from __future__ import annotations

import asyncio
import os

import clock
from models.event import Event
from models.pipeline import ActionRequest, ActionResult
from body.executor import register
from body.rate_limiter import check_rate_limit, record_action, is_channel_enabled
from pipeline.ack import on_visitor_connect
import db


class TelegramAdapter:
    """Polls a Telegram group for messages and injects them as visitor events."""

    def __init__(self, group_chat_id: str, heartbeat=None):
        self.group_chat_id = int(group_chat_id)
        self._heartbeat = heartbeat
        self._running = False
        self._offset = 0

    async def start_polling(self):
        """Background task: poll for new messages, inject as visitor events."""
        self._running = True
        print(f"  [Telegram] Polling started for chat {self.group_chat_id}")

        while self._running:
            try:
                from body.tg_client import get_updates
                updates = await get_updates(offset=self._offset, timeout=30)

                for update in updates:
                    self._offset = update.update_id + 1

                    if not update.message:
                        continue
                    if not update.message.text:
                        continue
                    if update.message.chat.id != self.group_chat_id:
                        continue
                    # Skip bot's own messages
                    if update.message.from_user and update.message.from_user.is_bot:
                        continue

                    await self._handle_message(update.message)

            except Exception as e:
                print(f"  [Telegram] Polling error: {type(e).__name__}: {e}")
                await asyncio.sleep(5)  # backoff on error

            await asyncio.sleep(1)

    def stop(self):
        """Signal the polling loop to stop."""
        self._running = False
        print("  [Telegram] Polling stopped")

    async def _handle_message(self, message):
        """Convert a Telegram message into a visitor event."""
        user = message.from_user
        if not user:
            return

        visitor_id = f'tg_{user.id}'
        display_name = user.first_name or user.username or 'someone'

        # Only fire visitor_connect + session boundary on FIRST message.
        # Previously every message triggered both, which:
        # 1. Spammed visitor_connect events (incrementing visit count per msg)
        # 2. Inserted __session_boundary__ per message, wiping conversation
        #    context so cortex only saw the latest message.
        engagement = await db.get_engagement_state()
        already_engaged = engagement.is_engaged_with(f'visitor:{visitor_id}')

        if not already_engaged:
            connect_event = Event(
                event_type='visitor_connect',
                source=f'visitor:{visitor_id}',
                payload={'display_name': display_name, 'platform': 'telegram'},
            )
            await on_visitor_connect(connect_event)
            await db.update_visitor(visitor_id, name=display_name)
            await db.mark_session_boundary(visitor_id)
        else:
            await db.update_visitor(visitor_id, name=display_name)

        # Track presence
        await db.add_visitor_present(visitor_id, 'telegram')

        # Create and inject event
        event = Event(
            event_type='visitor_speech',
            source=f'visitor:{visitor_id}',
            payload={
                'text': message.text,
                'platform': 'telegram',
                'tg_message_id': message.message_id,
                'tg_chat_id': message.chat.id,
                'display_name': display_name,
            },
            channel='visitor',
        )
        await db.append_event(event)
        await db.inbox_add(event.id, priority=0.8)
        print(f"  [Telegram] Message from {display_name} ({visitor_id}): {message.text[:50]}...")

        # HOTFIX-004: Wake the heartbeat loop immediately
        if self._heartbeat:
            await self._heartbeat.schedule_microcycle()


async def send_reply(visitor_id: str, text: str,
                     image_path: str = None) -> dict:
    """Send a reply to a visitor via Telegram group.

    Called by the channel router when dialogue targets a TG visitor.
    """
    chat_id = os.environ.get('TELEGRAM_GROUP_CHAT_ID', '')
    if not chat_id:
        return {'success': False, 'error': 'TELEGRAM_GROUP_CHAT_ID not set'}

    from body.tg_client import send_message, send_photo

    if image_path:
        return await send_photo(chat_id, image_path, caption=text)
    return await send_message(chat_id, text)


# ── Executors ──

@register('tg_send')
async def execute_tg_send(action: ActionRequest, visitor_id: str = None,
                          monologue: str = '') -> ActionResult:
    """Send a message to the Telegram group."""
    result = ActionResult(action='tg_send', timestamp=clock.now_utc())

    if not await is_channel_enabled('telegram'):
        result.success = False
        result.error = 'telegram channel disabled'
        return result

    allowed, reason = await check_rate_limit('tg_send')
    if not allowed:
        result.success = False
        result.error = reason
        return result

    text = (action.detail.get('text') or action.detail.get('content', '')).strip()
    if not text:
        result.success = False
        result.error = 'no message text'
        return result

    chat_id = os.environ.get('TELEGRAM_GROUP_CHAT_ID', '')
    if not chat_id:
        result.success = False
        result.error = 'TELEGRAM_GROUP_CHAT_ID not set'
        return result

    from body.tg_client import send_message
    api_result = await send_message(chat_id, text)

    await record_action('tg_send', success=api_result.get('success', False),
                        channel='telegram',
                        error=api_result.get('error'))

    if api_result.get('success'):
        result.payload = {'message_id': api_result.get('message_id')}
        result.side_effects.append('tg_message_sent')
    else:
        result.success = False
        result.error = api_result.get('error', 'send failed')

    return result


@register('tg_send_image')
async def execute_tg_send_image(action: ActionRequest, visitor_id: str = None,
                                monologue: str = '') -> ActionResult:
    """Send an image to the Telegram group."""
    result = ActionResult(action='tg_send_image', timestamp=clock.now_utc())

    if not await is_channel_enabled('telegram'):
        result.success = False
        result.error = 'telegram channel disabled'
        return result

    allowed, reason = await check_rate_limit('tg_send_image')
    if not allowed:
        result.success = False
        result.error = reason
        return result

    image_path = action.detail.get('image_path', '')
    caption = action.detail.get('caption', '')

    if not image_path:
        result.success = False
        result.error = 'no image_path'
        return result

    chat_id = os.environ.get('TELEGRAM_GROUP_CHAT_ID', '')
    if not chat_id:
        result.success = False
        result.error = 'TELEGRAM_GROUP_CHAT_ID not set'
        return result

    from body.tg_client import send_photo
    api_result = await send_photo(chat_id, image_path, caption=caption)

    await record_action('tg_send_image', success=api_result.get('success', False),
                        channel='telegram',
                        error=api_result.get('error'))

    if api_result.get('success'):
        result.payload = {'message_id': api_result.get('message_id')}
        result.side_effects.append('tg_image_sent')
    else:
        result.success = False
        result.error = api_result.get('error', 'send failed')

    return result
