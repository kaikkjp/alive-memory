"""sim.llm.cached — Real LLM with deterministic response caching.

First run: calls real LLM, caches response keyed by context hash.
Subsequent runs: returns cached response. Perfectly reproducible.

Usage:
    from sim.llm.cached import CachedCortex
    cached = CachedCortex(model="anthropic/claude-haiku-4-5-20251001")
    result = await cached.complete(messages=[...], system="...")
    cached.report()  # Cache: 45/50 hits (90%), Cost: ~$0.02
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class CachedCortex:
    """Wraps real LLM with deterministic caching.

    First run: calls real LLM via llm.client.complete(), caches response
    keyed by context hash. Subsequent runs: returns cached response.
    """

    def __init__(
        self,
        cache_dir: str = "sim/cache",
        model: str | None = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model_override = model
        self.hits = 0
        self.misses = 0
        self.total_cost = 0.0

    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        call_site: str = "default",
        max_tokens: int = 4096,
        temperature: float = 0.0,  # deterministic by default
        timeout: float = 60.0,
        tools: list[dict] | None = None,
    ) -> dict:
        """Complete with caching. Checks cache first, calls real LLM on miss."""
        cache_key = self._hash_context(messages, system, call_site)
        cache_file = self.cache_dir / f"{cache_key}.json"

        if cache_file.exists():
            self.hits += 1
            return json.loads(cache_file.read_text())

        # Cache miss — call real LLM
        self.misses += 1

        # Import here to avoid requiring API keys when using cache-only mode
        from llm.client import complete as llm_complete

        result = await llm_complete(
            messages=messages,
            system=system,
            call_site=call_site,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            tools=tools,
        )

        # Track cost
        cost = result.get("usage", {}).get("cost_usd", 0.0)
        self.total_cost += cost

        # Cache the result
        cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2))

        return result

    def _hash_context(
        self,
        messages: list[dict],
        system: str | None,
        call_site: str,
    ) -> str:
        """Hash the semantically relevant parts of context.

        Quantizes drive values to 0.1 bins for cache stability — small
        floating point differences in drives shouldn't cause cache misses.
        """
        # Flatten message content for hashing
        flat_messages = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                content = "".join(text_parts)

            # Quantize any floating point numbers in content
            content = self._quantize_numbers(content)
            flat_messages.append({"role": msg["role"], "content": content})

        hashable = {
            "system": self._quantize_numbers(system or ""),
            "messages": flat_messages,
            "call_site": call_site,
        }

        raw = json.dumps(hashable, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _quantize_numbers(text: str) -> str:
        """Quantize floating point numbers in text to 0.1 bins.

        Turns "0.537" into "0.5", "0.849" into "0.8", etc.
        This prevents minor drive fluctuations from busting the cache.
        """
        import re

        def _round(match):
            try:
                val = float(match.group())
                return f"{round(val, 1)}"
            except ValueError:
                return match.group()

        return re.sub(r'-?\d+\.\d{2,}', _round, text)

    def report(self):
        """Print cache statistics."""
        total = self.hits + self.misses
        if total == 0:
            print("Cache: 0 calls")
            return
        hit_rate = self.hits / total * 100
        print(f"Cache: {self.hits}/{total} hits ({hit_rate:.0f}%)")
        print(f"Cost: ~${self.total_cost:.2f} ({self.misses} LLM calls)")

    def stats(self) -> dict:
        """Return cache statistics as dict."""
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total": total,
            "hit_rate": (self.hits / total * 100) if total > 0 else 0,
            "cost_usd": self.total_cost,
        }

    def clear_cache(self):
        """Remove all cached responses."""
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
        self.hits = 0
        self.misses = 0
        self.total_cost = 0.0
