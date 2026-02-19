"""Channel router — route replies to originating channel.

Visitors can reach the shop via web, TCP terminal, Telegram, or X.
When the cortex generates dialogue, the channel router sends the reply
back through whichever channel the visitor arrived on.

Web/TCP replies are handled by the existing broadcast/TCP write paths
in heartbeat_server.py — the channel router only handles external
channels (Telegram, X) where an API call is needed.
"""

from __future__ import annotations

import db.connection as _connection


CHANNELS = {'web', 'tcp', 'telegram', 'x'}


async def get_visitor_channel(visitor_id: str) -> str:
    """Look up the connection type for a visitor from visitors_present."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT connection_type FROM visitors_present WHERE visitor_id = ?",
        (visitor_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else 'web'


async def route_reply(visitor_id: str, text: str, image_path: str = None,
                      channel: str = None) -> dict:
    """Send reply via the visitor's originating channel.

    Returns ``{'routed': True, 'channel': ...}`` on success or
    ``{'routed': False, 'reason': ...}`` on failure.

    Web/TCP channels return immediately — those replies are handled by
    heartbeat_server broadcast.  Only Telegram and X need explicit API calls.
    """
    channel = channel or await get_visitor_channel(visitor_id)

    if channel in ('web', 'tcp', 'websocket'):
        # Handled by existing heartbeat_server broadcast/TCP write
        return {'routed': True, 'channel': channel, 'method': 'broadcast'}

    if channel == 'telegram':
        try:
            from body.telegram import send_reply
            result = await send_reply(visitor_id, text, image_path=image_path)
            success = result.get('success', True)
            return {'routed': success, 'channel': 'telegram', **result}
        except Exception as e:
            print(f"  [ChannelRouter] Telegram reply failed: {e}")
            return {'routed': False, 'channel': 'telegram', 'reason': str(e)}

    if channel == 'x':
        try:
            from body.x_social import reply_to_visitor
            result = await reply_to_visitor(visitor_id, text)
            success = result.get('success', True)
            return {'routed': success, 'channel': 'x', **result}
        except Exception as e:
            print(f"  [ChannelRouter] X reply failed: {e}")
            return {'routed': False, 'channel': 'x', 'reason': str(e)}

    return {'routed': False, 'channel': channel, 'reason': f'unknown channel: {channel}'}
