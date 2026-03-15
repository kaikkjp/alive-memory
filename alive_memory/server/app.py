"""FastAPI application factory and entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from alive_memory import AliveMemory, __version__
from alive_memory.server.config import ServerConfig


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Optional bearer token authentication."""

    def __init__(self, app, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        # Skip auth for health endpoint
        if request.url.path == "/health":
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != self.api_key:
            return Response(
                content='{"detail":"Invalid or missing API key"}',
                status_code=401,
                media_type="application/json",
            )
        return await call_next(request)


def create_app(config: ServerConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    config = config or ServerConfig()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        memory = AliveMemory(
            storage=config.db_path,
            memory_dir=config.memory_dir,
            config=config.config_path,
        )
        await memory.initialize()
        app.state.memory = memory
        app.state.config = config
        yield
        await memory.close()

    app = FastAPI(
        title="alive-memory",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Optional auth
    if config.api_key:
        app.add_middleware(BearerAuthMiddleware, api_key=config.api_key)

    # Routes
    from alive_memory.server.routes import router

    app.include_router(router)

    return app


def main() -> None:
    """CLI entry point: alive-memory-server."""
    import uvicorn

    config = ServerConfig()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
