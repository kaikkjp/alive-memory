"""API key authentication and rate limiting for public agent endpoints.

TASK-095 Phase 3: Provides API key validation and per-key rate limiting
for the public /api/chat and /api/state endpoints.

API keys are stored in {AGENT_CONFIG_DIR}/api_keys.json with format:
[
    {"key": "sk-live-...", "name": "My App", "rate_limit": 60},
    ...
]
"""

import json
import os
import time
from collections import defaultdict
from typing import Optional


class ApiKeyManager:
    """Manages API key validation and rate limiting.

    Auto-reloads api_keys.json when the file changes on disk (checked at
    most once per second to avoid stat() overhead on every request).
    """

    def __init__(self, keys_path: Optional[str] = None):
        self._keys: dict[str, dict] = {}  # key → metadata
        self._rate_counters: dict[str, list[float]] = defaultdict(list)
        self._default_rate_limit = 60  # requests per minute
        self._keys_path: Optional[str] = keys_path
        self._last_mtime: float = 0.0
        self._last_check: float = 0.0
        if keys_path and os.path.exists(keys_path):
            self._load_keys(keys_path)

    def _load_keys(self, path: str):
        """Load API keys from JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"api_keys.json must be a JSON array, got {type(data).__name__}")
        new_keys: dict[str, dict] = {}
        for entry in data:
            key = entry.get('key', '')
            if key:
                new_keys[key] = {
                    'name': entry.get('name', 'unnamed'),
                    'rate_limit': entry.get('rate_limit', self._default_rate_limit),
                }
        self._keys = new_keys
        try:
            self._last_mtime = os.path.getmtime(path)
        except OSError:
            pass

    def _maybe_reload(self):
        """Reload keys if the file changed. Checks mtime at most once/sec."""
        if not self._keys_path:
            return
        now = time.monotonic()
        if now - self._last_check < 1.0:
            return
        self._last_check = now
        try:
            mtime = os.path.getmtime(self._keys_path)
            if mtime != self._last_mtime:
                self._load_keys(self._keys_path)
        except OSError:
            pass

    def validate(self, key: str) -> Optional[dict]:
        """Validate an API key. Returns metadata dict or None if invalid."""
        self._maybe_reload()
        return self._keys.get(key)

    def check_rate_limit(self, key: str) -> bool:
        """Check if a key is within its rate limit. Returns True if allowed."""
        meta = self._keys.get(key)
        if not meta:
            return False

        limit = meta.get('rate_limit', self._default_rate_limit)
        now = time.monotonic()
        window = 60.0  # 1 minute sliding window

        # Clean old entries
        timestamps = self._rate_counters[key]
        self._rate_counters[key] = [t for t in timestamps if now - t < window]

        if len(self._rate_counters[key]) >= limit:
            return False

        self._rate_counters[key].append(now)
        return True

    @property
    def has_keys(self) -> bool:
        """Whether any API keys are configured."""
        return len(self._keys) > 0

    def add_key(self, key: str, name: str = 'unnamed', rate_limit: int = 60):
        """Add a key programmatically (useful for tests)."""
        self._keys[key] = {'name': name, 'rate_limit': rate_limit}
