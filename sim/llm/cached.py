"""sim.llm.cached — Real LLM with deterministic response caching.

First run: calls real LLM, caches response keyed by context hash.
Subsequent runs: returns cached response. Perfectly reproducible.

Cache key is built from message content + system prompt structure
(with drive values stripped) + call site + variant. Drive values are
excluded from the hash because they change every cycle but don't
meaningfully alter the LLM's behavioral mode — they cause catastrophic
cache collapse where 85%+ of cycles return the same cached response.

A max-reuse cap (default 3) breaks feedback loops by forcing a cache
miss after a response has been served N times, even if the hash matches.

Usage:
    from sim.llm.cached import CachedCortex
    cached = CachedCortex(variant="full")
    result = await cached.complete(messages=[...], system="...")
    cached.report()  # Cache: 45/50 hits (90%), Cost: ~$0.02
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


class CachedCortex:
    """Wraps real LLM with deterministic caching.

    First run: calls real LLM via llm.client.complete(), caches response
    keyed by context hash. Subsequent runs: returns cached response.
    Max reuse cap prevents feedback loops on identical idle prompts.
    """

    def __init__(
        self,
        cache_dir: str = "sim/cache",
        model: str | None = None,
        variant: str = "full",
        max_reuse: int = 3,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model_override = model
        self.variant = variant
        self.max_reuse = max_reuse
        self.hits = 0
        self.misses = 0
        self.forced_misses = 0
        self.total_cost = 0.0
        self._reuse_counts: Counter = Counter()

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

        if cache_file.exists() and self._reuse_counts[cache_key] < self.max_reuse:
            self.hits += 1
            self._reuse_counts[cache_key] += 1
            return json.loads(cache_file.read_text())

        # Cache miss (or max reuse exceeded)
        if cache_file.exists():
            self.forced_misses += 1
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

        # Cache the result (overwrites on forced miss — new response for same key)
        cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        self._reuse_counts[cache_key] = 1

        return result

    def _hash_context(
        self,
        messages: list[dict],
        system: str | None,
        call_site: str,
    ) -> str:
        """Hash the semantically relevant parts of context.

        Drives are stripped from the system prompt before hashing — they
        change every cycle but only shift behavior gradually. Including
        them (even quantized to 0.1 bins) collapses the state space and
        causes 85%+ cache hit rates where every idle cycle returns the
        same response.

        The variant name is included so ablation runs (no_drives,
        no_memory, etc.) don't share cache entries with the full pipeline.
        """
        # Strip drive values from system prompt before hashing
        clean_system = self._strip_drives(system or "")

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
            flat_messages.append({"role": msg["role"], "content": content})

        hashable = {
            "system": clean_system,
            "messages": flat_messages,
            "call_site": call_site,
            "variant": self.variant,
        }

        raw = json.dumps(hashable, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _strip_drives(text: str) -> str:
        """Remove drive values and feelings text from system prompt.

        Strips lines like "  social_hunger: 0.537" and the CURRENT FEELINGS
        block so they don't contribute to the cache key. The structural
        parts of the prompt (identity, voice rules, schema) still hash.
        """
        lines = text.split("\n")
        out = []
        skip_feelings = False
        for line in lines:
            # Skip drive value lines (e.g. "  social_hunger: 0.537")
            if re.match(r'^\s+(social_hunger|curiosity|expression_need|'
                        r'rest_need|energy|mood_valence|mood_arousal)\s*:', line):
                continue
            # Skip CURRENT FEELINGS block
            if line.strip().startswith("CURRENT FEELINGS:"):
                skip_feelings = True
                continue
            if skip_feelings:
                if line.strip() == "" or line.strip().startswith(("CONSTRAINTS:", "EXPRESS")):
                    skip_feelings = False
                else:
                    continue
            # Skip "Mood:" line and "Valence" line
            stripped = line.strip()
            if stripped.startswith("Mood:") or re.match(r'^Valence\s', stripped):
                continue
            # Skip visitor engagement line (turn count changes)
            if "VISITOR ENGAGED:" in line:
                continue
            out.append(line)
        return "\n".join(out)

    def report(self):
        """Print cache statistics."""
        total = self.hits + self.misses
        if total == 0:
            print("Cache: 0 calls")
            return
        hit_rate = self.hits / total * 100
        print(f"Cache: {self.hits}/{total} hits ({hit_rate:.0f}%), "
              f"{self.forced_misses} forced misses")
        print(f"Cost: ~${self.total_cost:.2f} ({self.misses} LLM calls)")

    def stats(self) -> dict:
        """Return cache statistics as dict."""
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "forced_misses": self.forced_misses,
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
        self.forced_misses = 0
        self.total_cost = 0.0
        self._reuse_counts.clear()
