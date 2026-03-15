"""Server configuration from environment variables."""

from __future__ import annotations

import os


class ServerConfig:
    """Configuration for the alive-memory REST API server."""

    host: str = "0.0.0.0"
    port: int = 8100
    db_path: str = "memory.db"
    memory_dir: str = "memory_hot"
    config_path: str | None = None
    api_key: str | None = None
    cors_origins: list[str] = ["*"]

    def __init__(self) -> None:
        self.host = os.getenv("ALIVE_HOST", self.host)
        self.port = int(os.getenv("ALIVE_PORT", str(self.port)))
        self.db_path = os.getenv("ALIVE_DB", self.db_path)
        self.memory_dir = os.getenv("ALIVE_MEMORY_DIR", self.memory_dir)
        self.config_path = os.getenv("ALIVE_CONFIG") or None
        self.api_key = os.getenv("ALIVE_API_KEY") or None

        origins_env = os.getenv("ALIVE_CORS_ORIGINS")
        if origins_env:
            self.cors_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
