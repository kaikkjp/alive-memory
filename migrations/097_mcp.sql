-- MCP (Model Context Protocol) server registration and tool usage tracking.

CREATE TABLE IF NOT EXISTS mcp_servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    discovered_tools TEXT,  -- JSON: [{name, description, input_schema, enabled, action_suffix}]
    connected_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS mcp_tool_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    cycle_id TEXT,
    input_summary TEXT,
    output_summary TEXT,
    success INTEGER NOT NULL DEFAULT 1,
    used_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_usage_server ON mcp_tool_usage(server_id);
