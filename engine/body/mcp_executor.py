"""MCP Executor — executes MCP tool actions.

Same pattern as other body executors (web, telegram, x_social).
Routes mcp_* actions to external MCP servers via JSON-RPC.
"""

from __future__ import annotations

import json

import clock
from models.pipeline import ActionRequest, ActionResult
import db


async def execute_mcp_action(action: ActionRequest, visitor_id: str = None,
                             monologue: str = '') -> ActionResult:
    """Execute an MCP tool action.

    1. Resolve action name → (server_id, raw_tool_name, url)
    2. Build arguments from detail dict
    3. Call tool via McpClient
    4. Log usage
    5. Return ActionResult
    """
    from body.mcp_registry import resolve_mcp_action, get_client, is_server_enabled
    from pipeline.action_registry import ACTION_REGISTRY

    result = ActionResult(action=action.type, timestamp=clock.now_utc())

    # Guard: action must be registered (not disabled at tool level)
    if action.type not in ACTION_REGISTRY:
        result.success = False
        result.error = f"MCP tool {action.type} is disabled or not registered"
        return result

    # 1. Resolve
    resolved = resolve_mcp_action(action.type)
    if not resolved:
        result.success = False
        result.error = f"Unknown MCP action: {action.type}"
        return result

    server_id, raw_tool_name, url = resolved

    # Check server enabled
    if not is_server_enabled(server_id):
        result.success = False
        result.error = f"MCP server {server_id} is not available"
        return result

    # 2. Build arguments
    detail = action.detail or {}
    arguments = detail.get('arguments', {})
    if not arguments:
        # Fallback: map freeform content → query
        content = detail.get('content') or detail.get('text', '')
        if content:
            arguments = {'query': content}

    # 3. Call tool
    client = get_client()
    tool_result = await client.call_tool(url, raw_tool_name, arguments)

    # 4. Log usage
    cycle_id = detail.get('cycle_id', '')
    input_summary = json.dumps(arguments)[:500] if arguments else ''
    output_summary = (tool_result.content or '')[:500]
    try:
        await db.log_mcp_tool_usage(
            server_id, raw_tool_name, cycle_id,
            input_summary, output_summary, tool_result.success
        )
    except Exception as e:
        print(f"  [MCP] Failed to log usage: {e}")

    # 5. Return result
    result.success = tool_result.success
    if tool_result.success:
        result.content = tool_result.content
        result.payload = {'mcp_result': tool_result.content}
    else:
        result.error = tool_result.error or tool_result.content

    return result
