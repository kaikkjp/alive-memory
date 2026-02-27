"""MCP Registry — runtime-only injection of MCP tools into ACTION_REGISTRY.

Does NOT touch actions_enabled or identity YAML. Dashboard handlers own that sync.
load_from_db() is side-effect free on startup (runtime registry only).
"""

from __future__ import annotations

import re
from typing import Optional

from pipeline.action_registry import ACTION_REGISTRY, ActionCapability
from body.mcp_client import McpClient, McpToolSchema

_client: Optional[McpClient] = None
_servers: dict[int, dict] = {}
# server_id → {url, tools: {suffix: {raw_name, description, enabled}}}


def get_client() -> McpClient:
    """Lazy singleton. Shared so circuit breaker state persists across calls."""
    global _client
    if _client is None:
        _client = McpClient()
    return _client


def _normalize_tool_name(name: str) -> str:
    """Lowercase, replace non-alnum with _, strip edges. Empty → 'tool'."""
    result = re.sub(r'[^a-z0-9]', '_', name.lower()).strip('_')
    return result or 'tool'


def compute_action_suffixes(tools: list[McpToolSchema]) -> tuple[list[dict], list[str]]:
    """Compute stable action_suffix for each tool.

    Sort by raw name, normalize, deduplicate with _2/_3 suffixes.
    Called ONCE on first connect. Result persisted in DB.
    For reconnect, use merge_action_suffixes() instead to preserve existing IDs.
    """
    # Sort by raw name for deterministic suffix assignment
    sorted_tools = sorted(tools, key=lambda t: t.name)

    # Deduplicate raw names (last-wins, with warnings)
    seen_raw: dict[str, McpToolSchema] = {}
    warnings: list[str] = []
    for tool in sorted_tools:
        if tool.name in seen_raw:
            warnings.append(f"Duplicate tool name '{tool.name}' — using last definition")
        seen_raw[tool.name] = tool
    deduped = sorted(seen_raw.values(), key=lambda t: t.name)

    # Normalize and handle collisions
    suffix_counts: dict[str, int] = {}
    result = []
    for tool in deduped:
        base = _normalize_tool_name(tool.name)
        count = suffix_counts.get(base, 0)
        suffix_counts[base] = count + 1
        suffix = base if count == 0 else f"{base}_{count + 1}"
        result.append({
            'name': tool.name,
            'description': tool.description,
            'input_schema': tool.input_schema,
            'enabled': True,
            'action_suffix': suffix,
        })

    return result, warnings


def merge_action_suffixes(
    new_tools: list[McpToolSchema],
    existing_tools: list[dict],
) -> tuple[list[dict], list[str]]:
    """Merge new tool discovery with existing persisted suffixes.

    Preserves existing suffix + enabled state for tools that still exist.
    Only computes new suffixes for genuinely new tools (avoiding collisions).
    Tools no longer present on the server are dropped.
    """
    warnings: list[str] = []

    # Deduplicate new tools by raw name
    seen_raw: dict[str, McpToolSchema] = {}
    for tool in sorted(new_tools, key=lambda t: t.name):
        if tool.name in seen_raw:
            warnings.append(f"Duplicate tool name '{tool.name}' — using last definition")
        seen_raw[tool.name] = tool

    # Build lookup: raw_name → existing persisted entry
    existing_by_name: dict[str, dict] = {}
    existing_suffixes: set[str] = set()
    for t in existing_tools:
        name = t.get('name', '')
        suffix = t.get('action_suffix', '')
        if name and suffix:
            existing_by_name[name] = t
            existing_suffixes.add(suffix)

    result = []
    new_needing_suffix = []

    # Phase 1: preserve existing suffix + enabled state for tools still present
    for name in sorted(seen_raw.keys()):
        tool = seen_raw[name]
        if name in existing_by_name:
            old = existing_by_name[name]
            result.append({
                'name': tool.name,
                'description': tool.description,
                'input_schema': tool.input_schema,
                'enabled': old.get('enabled', True),
                'action_suffix': old['action_suffix'],
            })
        else:
            new_needing_suffix.append(tool)

    # Phase 2: compute suffixes for genuinely new tools, avoiding collisions
    used_suffixes = set(existing_suffixes)
    for tool in new_needing_suffix:
        base = _normalize_tool_name(tool.name)
        # Find first available suffix
        if base not in used_suffixes:
            suffix = base
        else:
            n = 2
            while f"{base}_{n}" in used_suffixes:
                n += 1
            suffix = f"{base}_{n}"
        used_suffixes.add(suffix)
        result.append({
            'name': tool.name,
            'description': tool.description,
            'input_schema': tool.input_schema,
            'enabled': True,
            'action_suffix': suffix,
        })

    return result, warnings


def register_server(server_id: int, server_info: dict) -> list[str]:
    """Inject enabled MCP tools into ACTION_REGISTRY.

    Builds _servers cache from ALL tools (enabled + disabled).
    Only enabled tools get ACTION_REGISTRY entries.
    Uses persisted action_suffix from discovered_tools JSON.
    Returns list of registered action names.
    DOES NOT touch actions_enabled — caller's responsibility.

    server_info: dict with keys 'url', 'discovered_tools' (list of dicts),
                 'enabled' (server-level).
    """
    url = server_info.get('url', '')
    tools_data = server_info.get('discovered_tools', [])
    server_enabled = bool(server_info.get('enabled', 1))

    # Build _servers cache entry (ALL tools, enabled + disabled)
    tools_cache: dict[str, dict] = {}
    for tool in tools_data:
        suffix = tool.get('action_suffix', '')
        if not suffix:
            continue
        tools_cache[suffix] = {
            'raw_name': tool.get('name', ''),
            'description': tool.get('description', ''),
            'enabled': bool(tool.get('enabled', True)),
        }
    _servers[server_id] = {'url': url, 'tools': tools_cache}

    # Only inject enabled tools from enabled servers into ACTION_REGISTRY
    registered = []
    if server_enabled:
        for suffix, info in tools_cache.items():
            if not info['enabled']:
                continue
            action_name = f"mcp_{server_id}_{suffix}"
            ACTION_REGISTRY[action_name] = ActionCapability(
                name=action_name,
                enabled=True,
                cooldown_seconds=0,
                description=info['description'],
            )
            registered.append(action_name)

    return registered


def unregister_server(server_id: int) -> list[str]:
    """Remove all mcp_{server_id}_* from ACTION_REGISTRY.

    Returns list of removed action names (for caller to sync actions_enabled).
    DOES NOT touch actions_enabled — caller's responsibility.
    """
    prefix = f"mcp_{server_id}_"
    removed = [k for k in ACTION_REGISTRY if k.startswith(prefix)]
    for name in removed:
        del ACTION_REGISTRY[name]
    _servers.pop(server_id, None)
    return removed


def resolve_mcp_action(action_name: str) -> Optional[tuple[int, str, str]]:
    """Parse mcp_{id}_{suffix} → (server_id, raw_tool_name, server_url).

    Uses _servers cache (covers enabled + disabled tools).
    Returns None if not found.
    """
    if not action_name.startswith('mcp_'):
        return None

    # Parse: mcp_{server_id}_{suffix}
    parts = action_name.split('_', 2)  # ['mcp', '{id}', '{suffix}']
    if len(parts) < 3:
        return None

    try:
        server_id = int(parts[1])
    except ValueError:
        return None

    suffix = parts[2]
    srv = _servers.get(server_id)
    if not srv:
        return None

    tool = srv['tools'].get(suffix)
    if not tool:
        return None

    return (server_id, tool['raw_name'], srv['url'])


def suffix_to_action_name(server_id: int, action_suffix: str) -> str:
    return f"mcp_{server_id}_{action_suffix}"


def get_tool_by_suffix(server_id: int, suffix: str) -> Optional[dict]:
    """Lookup from _servers cache."""
    srv = _servers.get(server_id)
    if not srv:
        return None
    return srv['tools'].get(suffix)


def get_mcp_action_names() -> list[str]:
    """All registered MCP action names (currently in ACTION_REGISTRY)."""
    return [k for k in ACTION_REGISTRY if k.startswith('mcp_')]


def get_mcp_action_descriptions() -> list[tuple[str, str]]:
    """(name, description) pairs for cortex prompt."""
    return [
        (k, v.description)
        for k, v in ACTION_REGISTRY.items()
        if k.startswith('mcp_')
    ]


def is_server_enabled(server_id: int) -> bool:
    """Check if server exists in cache and has registered actions."""
    if server_id not in _servers:
        return False
    # Check if any tool from this server is in ACTION_REGISTRY
    prefix = f"mcp_{server_id}_"
    return any(k.startswith(prefix) for k in ACTION_REGISTRY)


async def load_from_db():
    """Startup rehydration. Isolates per-server — one bad row doesn't block others.

    Runtime-only: injects into ACTION_REGISTRY, does NOT touch actions_enabled.
    """
    import db
    servers = await db.get_mcp_servers()
    for srv in servers:
        try:
            register_server(srv['id'], srv)
            tool_count = sum(
                1 for t in srv.get('discovered_tools', [])
                if t.get('enabled', True)
            )
            if tool_count > 0:
                print(f"  [MCP] Restored server {srv['id']} ({srv['name']}): "
                      f"{tool_count} tools")
        except Exception as e:
            print(f"  [MCP] Skipping server {srv['id']}: {e}")
