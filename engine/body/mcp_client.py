"""MCP Client — JSON-RPC transport for Model Context Protocol servers.

Talks JSON-RPC to external MCP servers. Handles connect (discovery)
and tool invocation with timeout and circuit breaker.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class McpToolSchema:
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)


@dataclass
class McpServerInfo:
    url: str
    name: str
    tools: list[McpToolSchema] = field(default_factory=list)


@dataclass
class McpToolResult:
    success: bool
    content: str       # natural language for agent perception
    raw_result: dict = field(default_factory=dict)
    error: str = ''


class McpClient:
    """JSON-RPC client for MCP servers.

    - 30s timeout per call
    - Circuit breaker: 3 consecutive failures → 5 min cooldown per URL
    """

    TIMEOUT = 30
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN = 300  # 5 min

    def __init__(self):
        self._failure_counts: dict[str, int] = {}   # per URL
        self._breaker_until: dict[str, float] = {}   # per URL
        self._next_id: int = 1

    def _is_circuit_open(self, url: str) -> bool:
        until = self._breaker_until.get(url, 0)
        if until <= 0:
            return False
        if time.monotonic() < until:
            return True
        # Cooldown elapsed — reset
        self._breaker_until[url] = 0
        self._failure_counts[url] = 0
        return False

    def _record_failure(self, url: str) -> None:
        count = self._failure_counts.get(url, 0) + 1
        self._failure_counts[url] = count
        if count >= self.BREAKER_THRESHOLD:
            self._breaker_until[url] = time.monotonic() + self.BREAKER_COOLDOWN

    def _record_success(self, url: str) -> None:
        self._failure_counts[url] = 0
        self._breaker_until[url] = 0

    def _make_request(self, method: str, params: dict | None = None) -> dict:
        req_id = self._next_id
        self._next_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            msg["params"] = params
        return msg

    async def connect(self, url: str) -> McpServerInfo:
        """JSON-RPC: initialize → notifications/initialized → tools/list.

        Returns server info with discovered tools.
        Raises on network/timeout/protocol errors.
        """
        import aiohttp

        if self._is_circuit_open(url):
            raise ConnectionError(f"Circuit breaker open for {url}")

        try:
            async with aiohttp.ClientSession() as session:
                # Step 1: initialize
                init_req = self._make_request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "shopkeeper", "version": "1.0.0"}
                })
                async with session.post(
                    url, json=init_req,
                    timeout=aiohttp.ClientTimeout(total=self.TIMEOUT)
                ) as resp:
                    init_result = await resp.json()

                server_name = "MCP Server"
                if "result" in init_result:
                    si = init_result["result"].get("serverInfo", {})
                    server_name = si.get("name", server_name)

                # Step 2: notifications/initialized
                notif = {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }
                async with session.post(
                    url, json=notif,
                    timeout=aiohttp.ClientTimeout(total=self.TIMEOUT)
                ) as resp:
                    pass  # notification — no response expected, but HTTP still returns

                # Step 3: tools/list
                tools_req = self._make_request("tools/list")
                async with session.post(
                    url, json=tools_req,
                    timeout=aiohttp.ClientTimeout(total=self.TIMEOUT)
                ) as resp:
                    tools_result = await resp.json()

                tools = []
                if "result" in tools_result:
                    for t in tools_result["result"].get("tools", []):
                        tools.append(McpToolSchema(
                            name=t.get("name", ""),
                            description=t.get("description", ""),
                            input_schema=t.get("inputSchema", {}),
                        ))

                self._record_success(url)
                return McpServerInfo(url=url, name=server_name, tools=tools)

        except Exception as e:
            self._record_failure(url)
            raise ConnectionError(f"MCP connect failed for {url}: {e}") from e

    async def call_tool(self, url: str, tool_name: str,
                        arguments: dict) -> McpToolResult:
        """JSON-RPC tools/call.

        - 30s timeout
        - Circuit breaker: 3 failures → 5 min cooldown per URL
        - Errors → McpToolResult, not exceptions
        """
        import aiohttp

        if self._is_circuit_open(url):
            return McpToolResult(
                success=False,
                content="Tool server temporarily unavailable (circuit breaker open)",
                error="circuit_breaker_open",
            )

        try:
            req = self._make_request("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=req,
                    timeout=aiohttp.ClientTimeout(total=self.TIMEOUT)
                ) as resp:
                    result = await resp.json()

            if "error" in result:
                err = result["error"]
                error_msg = err.get("message", str(err))
                self._record_failure(url)
                return McpToolResult(
                    success=False,
                    content=f"Tool error: {error_msg}",
                    raw_result=result,
                    error=error_msg,
                )

            # Parse tool result content
            content_parts = []
            raw = result.get("result", {})
            for item in raw.get("content", []):
                if item.get("type") == "text":
                    content_parts.append(item.get("text", ""))
                else:
                    content_parts.append(str(item))

            content_text = "\n".join(content_parts) if content_parts else str(raw)

            self._record_success(url)
            return McpToolResult(
                success=True,
                content=content_text,
                raw_result=raw,
            )

        except Exception as e:
            self._record_failure(url)
            return McpToolResult(
                success=False,
                content=f"Tool call failed: {e}",
                error=str(e),
            )
