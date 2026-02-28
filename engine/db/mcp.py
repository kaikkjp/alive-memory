"""db.mcp — MCP server registration and tool usage tracking."""

import json
from typing import Optional

import db.connection as _connection


async def get_mcp_servers() -> list[dict]:
    """All servers with parsed discovered_tools."""
    conn = await _connection.get_db()
    cursor = await conn.execute("SELECT * FROM mcp_servers ORDER BY id")
    rows = await cursor.fetchall()
    results = []
    for row in rows:
        srv = dict(row)
        raw = srv.get('discovered_tools')
        try:
            srv['discovered_tools'] = json.loads(raw) if raw else []
        except (json.JSONDecodeError, TypeError):
            srv['discovered_tools'] = []
        results.append(srv)
    return results


async def get_mcp_server(server_id: int) -> Optional[dict]:
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM mcp_servers WHERE id = ?", (server_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    srv = dict(row)
    raw = srv.get('discovered_tools')
    srv['discovered_tools'] = json.loads(raw) if raw else []
    return srv


async def get_mcp_server_by_url(url: str) -> Optional[dict]:
    """For idempotent connect."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT * FROM mcp_servers WHERE url = ?", (url,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    srv = dict(row)
    raw = srv.get('discovered_tools')
    srv['discovered_tools'] = json.loads(raw) if raw else []
    return srv


async def create_mcp_server(name: str, url: str,
                            discovered_tools_json: str) -> int:
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """INSERT INTO mcp_servers (name, url, discovered_tools)
           VALUES (?, ?, ?)""",
        (name, url, discovered_tools_json)
    )
    await conn.commit()
    return cursor.lastrowid


async def update_mcp_server(server_id: int, **kwargs) -> None:
    """Toggle enabled, update discovered_tools JSON, etc."""
    if not kwargs:
        return
    allowed = {'name', 'url', 'enabled', 'discovered_tools', 'last_used_at'}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ', '.join(f'{k} = ?' for k in fields)
    values = list(fields.values()) + [server_id]
    conn = await _connection.get_db()
    await conn.execute(
        f"UPDATE mcp_servers SET {set_clause} WHERE id = ?", values
    )
    await conn.commit()


async def delete_mcp_server(server_id: int) -> None:
    """Cascade deletes usage rows via FK."""
    conn = await _connection.get_db()
    await conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
    await conn.commit()


async def update_mcp_tool_enabled(server_id: int, action_suffix: str,
                                  enabled: bool) -> None:
    """Modify single tool's enabled flag in discovered_tools JSON array.

    Match by action_suffix field.
    """
    conn = await _connection.get_db()
    cursor = await conn.execute(
        "SELECT discovered_tools FROM mcp_servers WHERE id = ?", (server_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return
    tools = json.loads(row['discovered_tools']) if row['discovered_tools'] else []
    updated = False
    for tool in tools:
        if tool.get('action_suffix') == action_suffix:
            tool['enabled'] = enabled
            updated = True
            break
    if updated:
        await conn.execute(
            "UPDATE mcp_servers SET discovered_tools = ? WHERE id = ?",
            (json.dumps(tools), server_id)
        )
        await conn.commit()


async def log_mcp_tool_usage(server_id: int, tool_name: str, cycle_id: str,
                             input_summary: str, output_summary: str,
                             success: bool) -> None:
    conn = await _connection.get_db()
    await conn.execute(
        """INSERT INTO mcp_tool_usage
           (server_id, tool_name, cycle_id, input_summary, output_summary, success)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (server_id, tool_name, cycle_id, input_summary, output_summary,
         1 if success else 0)
    )
    await conn.commit()


async def get_mcp_tool_usage_counts(server_id: int) -> dict[str, int]:
    """Returns {tool_name: count}."""
    conn = await _connection.get_db()
    cursor = await conn.execute(
        """SELECT tool_name, COUNT(*) as cnt
           FROM mcp_tool_usage WHERE server_id = ?
           GROUP BY tool_name""",
        (server_id,)
    )
    rows = await cursor.fetchall()
    return {row['tool_name']: row['cnt'] for row in rows}
