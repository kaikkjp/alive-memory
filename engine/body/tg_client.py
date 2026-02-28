"""Low-level Telegram Bot API wrapper.

Thin async wrapper around python-telegram-bot for sending messages,
photos, and fetching updates.  All calls are non-blocking.
"""

from __future__ import annotations

import asyncio
import os


def _get_bot():
    """Lazy-init a telegram Bot instance."""
    try:
        import telegram
    except ImportError:
        raise RuntimeError(
            'python-telegram-bot not installed. '
            'Install with: pip install python-telegram-bot'
        )
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token:
        raise ValueError('TELEGRAM_BOT_TOKEN not set')
    return telegram.Bot(token=token)


async def send_message(chat_id: str | int, text: str,
                       reply_to_message_id: int = None) -> dict:
    """Send a text message to a Telegram chat."""
    bot = _get_bot()
    try:
        msg = await bot.send_message(
            chat_id=int(chat_id),
            text=text[:4096],  # TG message limit
            reply_to_message_id=reply_to_message_id,
        )
        return {
            'success': True,
            'message_id': msg.message_id,
            'chat_id': msg.chat.id,
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'{type(e).__name__}: {e}',
        }


async def send_photo(chat_id: str | int, photo_path: str,
                     caption: str = None) -> dict:
    """Send a photo to a Telegram chat."""
    bot = _get_bot()
    try:
        with open(photo_path, 'rb') as f:
            msg = await bot.send_photo(
                chat_id=int(chat_id),
                photo=f,
                caption=caption[:1024] if caption else None,
            )
        return {
            'success': True,
            'message_id': msg.message_id,
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'{type(e).__name__}: {e}',
        }


async def get_updates(offset: int = 0, timeout: int = 30) -> list:
    """Fetch new updates from Telegram (long polling)."""
    bot = _get_bot()
    try:
        updates = await bot.get_updates(offset=offset, timeout=timeout)
        return updates
    except Exception as e:
        print(f"  [TGClient] get_updates error: {type(e).__name__}: {e}")
        return []
