"""RequestContext — thin adapter for route handlers.

Wraps the server instance so that handlers (and tests) can depend
on a minimal interface instead of the full ShopkeeperServer.

Opt-in for new handlers; existing ``(server, writer, ...)`` signatures
remain unchanged.  Gateway RPC handlers (Phase 3) will use this as
their primary dependency.
"""


class RequestContext:
    """Thin wrapper that delegates to server. Tests can mock this directly."""

    def __init__(self, server):
        self._server = server

    async def http_json(self, writer, status: int, body: dict):
        """Send an HTTP JSON response."""
        await self._server._http_json(writer, status, body)

    @property
    def heartbeat(self):
        """Access the Heartbeat instance."""
        return self._server.heartbeat

    @property
    def bus(self):
        """Access the EventBus instance."""
        return self._server._bus

    @property
    def server(self):
        """Access the underlying server (escape hatch for migration)."""
        return self._server
