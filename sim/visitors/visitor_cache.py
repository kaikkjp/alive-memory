"""sim.visitors.visitor_cache — JSONL persona and turn cache.

Provides deterministic caching for LLM-generated visitor personas and
dialogue turns. Pre-generated personas are stored in JSONL format for
reproducibility across runs. Turn responses are cached by a composite
key of (visitor_id, turn_number, shopkeeper_response_hash).

Cache structure:
    sim/cache/personas/       — JSONL files keyed by seed
    sim/cache/visitor_turns/  — JSON files keyed by context hash

Usage:
    cache = VisitorCache(cache_dir="sim/cache")
    persona = cache.get_persona("visitor_0042", seed=42)
    if persona is None:
        persona = await generate_persona(...)
        cache.put_persona("visitor_0042", seed=42, persona=persona)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class VisitorCache:
    """JSONL-based cache for visitor personas and dialogue turns.

    Personas are stored in per-seed JSONL files for batch pre-generation.
    Turns are stored as individual JSON files keyed by context hash.
    """

    def __init__(self, cache_dir: str = "sim/cache"):
        self.cache_dir = Path(cache_dir)
        self.persona_dir = self.cache_dir / "personas"
        self.turn_dir = self.cache_dir / "visitor_turns"
        self.persona_dir.mkdir(parents=True, exist_ok=True)
        self.turn_dir.mkdir(parents=True, exist_ok=True)

        # In-memory index: seed -> {visitor_id -> persona_dict}
        self._persona_index: dict[int, dict[str, dict]] = {}
        self._stats = {"persona_hits": 0, "persona_misses": 0,
                       "turn_hits": 0, "turn_misses": 0}

    # -- Persona cache --

    def _persona_file(self, seed: int) -> Path:
        return self.persona_dir / f"seed_{seed}.jsonl"

    def _load_persona_index(self, seed: int) -> dict[str, dict]:
        """Load all personas for a seed into memory."""
        if seed in self._persona_index:
            return self._persona_index[seed]

        index: dict[str, dict] = {}
        path = self._persona_file(seed)
        if path.exists():
            for line in path.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                entry = json.loads(line)
                vid = entry.get("visitor_id", "")
                if vid:
                    index[vid] = entry

        self._persona_index[seed] = index
        return index

    def get_persona(self, visitor_id: str, seed: int) -> dict | None:
        """Look up a cached persona. Returns None on miss."""
        index = self._load_persona_index(seed)
        persona = index.get(visitor_id)
        if persona is not None:
            self._stats["persona_hits"] += 1
        else:
            self._stats["persona_misses"] += 1
        return persona

    def put_persona(self, visitor_id: str, seed: int, persona: dict) -> None:
        """Store a persona in the JSONL cache."""
        index = self._load_persona_index(seed)

        entry = {"visitor_id": visitor_id, **persona}
        index[visitor_id] = entry
        self._persona_index[seed] = index

        # Append to JSONL file
        path = self._persona_file(seed)
        with open(path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def list_personas(self, seed: int) -> list[dict]:
        """Return all cached personas for a seed."""
        return list(self._load_persona_index(seed).values())

    # -- Turn cache --

    @staticmethod
    def _turn_key(
        visitor_id: str,
        turn_number: int,
        shopkeeper_response: str,
    ) -> str:
        """Generate a deterministic cache key for a turn.

        Key = hash(visitor_id + turn_number + shopkeeper_response_hash).
        """
        content = f"{visitor_id}:{turn_number}:{shopkeeper_response}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def get_turn(
        self,
        visitor_id: str,
        turn_number: int,
        shopkeeper_response: str,
    ) -> dict | None:
        """Look up a cached turn response. Returns None on miss."""
        key = self._turn_key(visitor_id, turn_number, shopkeeper_response)
        path = self.turn_dir / f"{key}.json"
        if path.exists():
            self._stats["turn_hits"] += 1
            return json.loads(path.read_text())
        self._stats["turn_misses"] += 1
        return None

    def put_turn(
        self,
        visitor_id: str,
        turn_number: int,
        shopkeeper_response: str,
        turn_data: dict,
    ) -> None:
        """Store a turn response in the cache."""
        key = self._turn_key(visitor_id, turn_number, shopkeeper_response)
        path = self.turn_dir / f"{key}.json"
        path.write_text(json.dumps(turn_data, ensure_ascii=False, indent=2))

    # -- Stats --

    def stats(self) -> dict:
        """Return cache hit/miss statistics."""
        return dict(self._stats)

    def clear(self) -> None:
        """Clear all caches (in-memory and on disk)."""
        self._persona_index.clear()
        self._stats = {"persona_hits": 0, "persona_misses": 0,
                       "turn_hits": 0, "turn_misses": 0}
        # Clear turn files
        for f in self.turn_dir.glob("*.json"):
            f.unlink()
        # Clear persona files
        for f in self.persona_dir.glob("*.jsonl"):
            f.unlink()
