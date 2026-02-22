"""sim.visitors.llm_visitor — Tier 2 LLM-generated visitor personas and dialogue.

Generates visitor personas via a single LLM call and produces per-turn
dialogue responses during visits.  All calls are cached through
VisitorCache for cross-run reproducibility.

Hard caps (from spec):
    - Persona call: 300 output tokens
    - Per-turn call: 150 output tokens
    - Total visitor token budget: 1500 tokens/visit
    - 3-8 exchanges per visit (exit early if goal met or frustration hit)

Usage:
    generator = LLMVisitorGenerator(llm=cached_cortex, cache=visitor_cache, seed=42)
    persona = await generator.generate_persona(visitor_id, archetype_hint)
    turn = await generator.generate_turn(visitor_id, persona, turn_num, history)
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from sim.visitors.visitor_cache import VisitorCache


# -- Persona generation prompt --

_PERSONA_SYSTEM = """\
You are generating a visitor persona for a vintage trading card shop simulation.
Return ONLY valid JSON matching this exact schema — no extra fields, no markdown:
{
  "name": "a Japanese or international name",
  "backstory": "1-2 sentences about who they are",
  "goal": "buy | sell | browse | learn | chat | appraise | trade",
  "budget_yen": 5000,
  "expertise": "novice | intermediate | expert",
  "temperament": "patient | eager | skeptical | shy",
  "emotional_state": "neutral | excited | frustrated | nostalgic | curious",
  "memory_anchor": "one detail they will remember if they return"
}"""

_PERSONA_USER_TEMPLATE = """\
Generate a unique visitor persona for a small vintage trading card shop in Tokyo.
The visitor should feel like a real person with a specific reason for visiting.

Archetype hint: {archetype_hint}
Goal hint: {goal_hint}
Visitor number: {visitor_number}

Be creative. Vary ages, backgrounds, and reasons for visiting. Some visitors
are collectors, some are casual, some have emotional connections to the cards."""


# -- Turn generation prompt --

_TURN_SYSTEM = """\
You are playing a visitor in a vintage trading card shop. Stay in character.
Return ONLY valid JSON:
{
  "text": "what the visitor says (1-3 sentences, max 50 words)",
  "intent": "greeting | asking | browsing | negotiating | deciding | leaving | chatting",
  "should_exit": false,
  "exit_reason": null
}

Rules:
- Keep responses short and natural (50 words max)
- Exit reasons: "goal_satisfied" | "patience_exhausted" | "budget_depleted" | "natural"
- Set should_exit=true when the visitor would naturally leave
- React to the shopkeeper's responses — don't ignore what she says"""

_TURN_USER_TEMPLATE = """\
PERSONA:
{persona_json}

CONVERSATION (last {window_size} turns):
{history_text}

VISIT STATE:
- Turn number: {turn_number} of {max_turns}
- Goal progress: {goal_progress}
- Patience remaining: {patience:.0%}

What does the visitor say next?"""


@dataclass
class VisitorPersona:
    """Parsed LLM-generated persona with defaults for missing fields."""
    name: str = "Visitor"
    backstory: str = ""
    goal: str = "browse"
    budget_yen: int = 5000
    expertise: str = "novice"
    temperament: str = "patient"
    emotional_state: str = "neutral"
    memory_anchor: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "backstory": self.backstory,
            "goal": self.goal,
            "budget_yen": self.budget_yen,
            "expertise": self.expertise,
            "temperament": self.temperament,
            "emotional_state": self.emotional_state,
            "memory_anchor": self.memory_anchor,
        }

    @classmethod
    def from_dict(cls, data: dict) -> VisitorPersona:
        # Sanitize budget_yen — LLMs may return "5,000" or other non-int formats
        raw_budget = data.get("budget_yen", 5000)
        try:
            budget = int(str(raw_budget).replace(",", "").strip())
        except (ValueError, TypeError):
            budget = 5000

        return cls(
            name=data.get("name", "Visitor"),
            backstory=data.get("backstory", ""),
            goal=data.get("goal", "browse"),
            budget_yen=budget,
            expertise=data.get("expertise", "novice"),
            temperament=data.get("temperament", "patient"),
            emotional_state=data.get("emotional_state", "neutral"),
            memory_anchor=data.get("memory_anchor", ""),
        )


@dataclass
class VisitorTurn:
    """A single dialogue turn from the visitor."""
    text: str = ""
    intent: str = "chatting"
    should_exit: bool = False
    exit_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "intent": self.intent,
            "should_exit": self.should_exit,
            "exit_reason": self.exit_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> VisitorTurn:
        return cls(
            text=data.get("text", ""),
            intent=data.get("intent", "chatting"),
            should_exit=bool(data.get("should_exit", False)),
            exit_reason=data.get("exit_reason"),
        )


# Temperament → patience multiplier
_TEMPERAMENT_PATIENCE: dict[str, float] = {
    "patient": 1.0,
    "eager": 0.7,
    "skeptical": 0.6,
    "shy": 0.8,
}

# Max turns by temperament
_MAX_TURNS: dict[str, int] = {
    "patient": 8,
    "eager": 6,
    "skeptical": 5,
    "shy": 4,
}


class LLMVisitorGenerator:
    """Generates Tier 2 visitor personas and turn-by-turn dialogue.

    Uses an LLM backend (MockCortex or CachedCortex) for generation
    and VisitorCache for cross-run reproducibility.

    Args:
        llm: LLM backend with async complete() method.
        cache: VisitorCache instance for persona/turn storage.
        seed: Random seed for deterministic fallbacks.
    """

    # Sliding window for turn context (last N turns only)
    TURN_CONTEXT_WINDOW = 3

    def __init__(self, llm, cache: VisitorCache | None = None, seed: int = 42):
        self.llm = llm
        self.cache = cache or VisitorCache()
        self.seed = seed
        self.rng = random.Random(seed)
        self._token_budget_used: dict[str, int] = {}  # visitor_id -> tokens

    async def generate_persona(
        self,
        visitor_id: str,
        archetype_hint: str = "regular visitor",
        goal_hint: str = "browse",
        visitor_number: int = 0,
    ) -> VisitorPersona:
        """Generate or retrieve a cached visitor persona.

        Args:
            visitor_id: Unique visitor identifier.
            archetype_hint: Archetype name for prompt seeding.
            goal_hint: Goal from scheduler for prompt seeding.
            visitor_number: Counter for uniqueness.

        Returns:
            Parsed VisitorPersona.
        """
        # Check cache first
        cached = self.cache.get_persona(visitor_id, self.seed)
        if cached is not None:
            return VisitorPersona.from_dict(cached)

        # Generate via LLM
        user_msg = _PERSONA_USER_TEMPLATE.format(
            archetype_hint=archetype_hint,
            goal_hint=goal_hint,
            visitor_number=visitor_number,
        )

        response = await self.llm.complete(
            messages=[{"role": "user", "content": user_msg}],
            system=_PERSONA_SYSTEM,
            call_site="visitor_persona",
            max_tokens=300,
            temperature=0.8,
        )

        persona = self._parse_persona_response(response)

        # Cache it
        self.cache.put_persona(visitor_id, self.seed, persona.to_dict())

        return persona

    async def generate_turn(
        self,
        visitor_id: str,
        persona: VisitorPersona,
        turn_number: int,
        conversation_history: list[dict],
        shopkeeper_last_response: str = "",
    ) -> VisitorTurn:
        """Generate the visitor's next dialogue turn.

        Args:
            visitor_id: Unique visitor identifier.
            persona: The visitor's persona.
            turn_number: Current turn number (0-indexed).
            conversation_history: List of {speaker, text} dicts.
            shopkeeper_last_response: Most recent shopkeeper text.

        Returns:
            Parsed VisitorTurn with text, intent, and exit decision.
        """
        max_turns = _MAX_TURNS.get(persona.temperament, 6)

        # Check per-visitor token budget (1500 total, ~300 for persona)
        used = self._token_budget_used.get(visitor_id, 0)
        if used >= 1200:  # 1500 - 300 persona budget
            return VisitorTurn(
                text="Well, I should get going. Thank you.",
                intent="leaving",
                should_exit=True,
                exit_reason="budget_depleted",
            )

        # Force exit at max turns
        if turn_number >= max_turns:
            return VisitorTurn(
                text="I should head out. Thanks for your time.",
                intent="leaving",
                should_exit=True,
                exit_reason="patience_exhausted",
            )

        # Check turn cache
        cached = self.cache.get_turn(
            visitor_id, turn_number, shopkeeper_last_response
        )
        if cached is not None:
            return VisitorTurn.from_dict(cached)

        # Build sliding-window history
        window = conversation_history[-self.TURN_CONTEXT_WINDOW:]
        history_lines = []
        for entry in window:
            speaker = entry.get("speaker", "?")
            text = entry.get("text", "")
            history_lines.append(f"{speaker}: {text}")
        history_text = "\n".join(history_lines) if history_lines else "(conversation just started)"

        # Calculate patience
        patience_mult = _TEMPERAMENT_PATIENCE.get(persona.temperament, 0.7)
        patience = max(0.0, 1.0 - (turn_number / max_turns)) * patience_mult

        # Goal progress heuristic
        goal_progress = "not started"
        if turn_number >= 2:
            goal_progress = "in progress"
        if turn_number >= max_turns - 2:
            goal_progress = "wrapping up"

        user_msg = _TURN_USER_TEMPLATE.format(
            persona_json=json.dumps(persona.to_dict(), indent=2),
            window_size=len(window),
            history_text=history_text,
            turn_number=turn_number + 1,
            max_turns=max_turns,
            goal_progress=goal_progress,
            patience=patience,
        )

        response = await self.llm.complete(
            messages=[{"role": "user", "content": user_msg}],
            system=_TURN_SYSTEM,
            call_site="visitor_turn",
            max_tokens=150,
            temperature=0.7,
        )

        turn = self._parse_turn_response(response)

        # Track token usage (estimate from response)
        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        tokens_used = int(usage.get("output_tokens", 0)) or 50  # estimate
        self._token_budget_used[visitor_id] = used + tokens_used

        # Cache it
        self.cache.put_turn(
            visitor_id, turn_number, shopkeeper_last_response,
            turn.to_dict(),
        )

        return turn

    def _parse_persona_response(self, response: dict) -> VisitorPersona:
        """Parse LLM response into a VisitorPersona, with fallbacks."""
        try:
            text = response["content"][0]["text"].strip()
            # Strip markdown fences
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].rstrip()
            data = json.loads(text)
            return VisitorPersona.from_dict(data)
        except (json.JSONDecodeError, KeyError, IndexError):
            # Fallback to a deterministic persona
            return self._fallback_persona()

    def _parse_turn_response(self, response: dict) -> VisitorTurn:
        """Parse LLM response into a VisitorTurn, with fallbacks."""
        try:
            text = response["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].rstrip()
            data = json.loads(text)
            return VisitorTurn.from_dict(data)
        except (json.JSONDecodeError, KeyError, IndexError):
            # Fallback: extract raw text as dialogue
            try:
                raw = response["content"][0]["text"].strip()
            except (KeyError, IndexError):
                raw = "Hmm, interesting."
            return VisitorTurn(text=raw[:200], intent="chatting")

    def _fallback_persona(self) -> VisitorPersona:
        """Generate a deterministic fallback persona without LLM."""
        names = [
            "Yamada-san", "Suzuki", "Mika", "Kenji", "Sato-san",
            "Yuki", "Takeshi", "Aiko", "Ryo", "Haruka",
        ]
        goals = ["buy", "browse", "chat", "learn", "sell"]
        temperaments = ["patient", "eager", "skeptical", "shy"]

        return VisitorPersona(
            name=self.rng.choice(names),
            backstory="A local resident visiting the shop.",
            goal=self.rng.choice(goals),
            budget_yen=self.rng.choice([1000, 3000, 5000, 10000, 20000]),
            expertise=self.rng.choice(["novice", "intermediate", "expert"]),
            temperament=self.rng.choice(temperaments),
            emotional_state=self.rng.choice(["neutral", "curious", "excited"]),
            memory_anchor="the atmosphere of the shop",
        )

    def reset_token_budget(self, visitor_id: str) -> None:
        """Reset token budget for a visitor (e.g. on new visit)."""
        self._token_budget_used.pop(visitor_id, None)

    def stats(self) -> dict:
        """Return generation statistics."""
        return {
            "cache": self.cache.stats(),
            "token_budgets": dict(self._token_budget_used),
        }


class LLMVisitorEngine:
    """High-level Tier 2 visitor engine used by SimulationRunner.

    Wraps LLMVisitorGenerator with session management: tracks active
    visitors, their personas, conversation histories, and turn counts.

    The runner calls:
        greeting = await engine.on_arrive(visitor)
        response = await engine.on_shopkeeper_spoke(visitor_id, dialogue)
        engine.on_leave(visitor_id)
        engine.is_active(visitor_id)
        engine.stats()
    """

    def __init__(self, llm_mode: str = "mock", seed: int = 42):
        """Create the engine with an LLM backend and cache.

        Args:
            llm_mode: "mock" or "cached" — passed to sim LLM factory.
            seed: Random seed for reproducibility.
        """
        self._llm = self._init_llm(llm_mode, seed)
        self._cache = VisitorCache()
        self._generator = LLMVisitorGenerator(
            llm=self._llm, cache=self._cache, seed=seed,
        )
        self._seed = seed

        # Active visitor sessions: visitor_id -> {persona, conversation, turn}
        self._active: dict[str, dict] = {}

    @staticmethod
    def _init_llm(mode: str, seed: int):
        """Create the LLM backend matching SimulationRunner's factory."""
        if mode == "mock":
            from sim.llm.mock import MockCortex
            return MockCortex(seed=seed)
        elif mode == "cached":
            from sim.llm.cached import CachedCortex
            return CachedCortex()
        else:
            raise ValueError(f"Unknown LLM mode: {mode}")

    async def on_arrive(self, visitor) -> str:
        """Generate persona and first greeting when a Tier 2 visitor arrives.

        Args:
            visitor: VisitorInstance from the scheduler.

        Returns:
            Greeting text string.
        """
        persona = await self._generator.generate_persona(
            visitor_id=visitor.visitor_id,
            archetype_hint=visitor.archetype_id or "visitor",
            goal_hint=visitor.goal or "browse",
            visitor_number=0,
        )

        self._active[visitor.visitor_id] = {
            "persona": persona,
            "conversation": [],
            "turn": 0,
        }

        # Generate the visitor's opening turn
        turn = await self._generator.generate_turn(
            visitor_id=visitor.visitor_id,
            persona=persona,
            turn_number=0,
            conversation_history=[],
            shopkeeper_last_response="",
        )

        # Record in conversation history
        self._active[visitor.visitor_id]["conversation"].append({
            "speaker": "visitor",
            "text": turn.text,
        })
        self._active[visitor.visitor_id]["turn"] = 1

        return turn.text

    async def on_shopkeeper_spoke(
        self, visitor_id: str, dialogue: str
    ) -> str | None:
        """Generate visitor's next turn after shopkeeper speaks.

        Args:
            visitor_id: The active visitor's ID.
            dialogue: What the shopkeeper just said.

        Returns:
            Visitor's response text, or None if visit should end.
        """
        session = self._active.get(visitor_id)
        if not session:
            return None

        # Record shopkeeper's response
        session["conversation"].append({
            "speaker": "shopkeeper",
            "text": dialogue,
        })

        turn_num = session["turn"]
        persona = session["persona"]

        turn = await self._generator.generate_turn(
            visitor_id=visitor_id,
            persona=persona,
            turn_number=turn_num,
            conversation_history=session["conversation"],
            shopkeeper_last_response=dialogue,
        )

        if turn.should_exit:
            # Visitor is leaving — clean up
            del self._active[visitor_id]
            return None

        # Record visitor's response
        session["conversation"].append({
            "speaker": "visitor",
            "text": turn.text,
        })
        session["turn"] = turn_num + 1

        return turn.text

    def on_leave(self, visitor_id: str) -> None:
        """Clean up when a visitor leaves (scheduled or early)."""
        self._active.pop(visitor_id, None)
        self._generator.reset_token_budget(visitor_id)

    def is_active(self, visitor_id: str) -> bool:
        """Check if a visitor has an active session."""
        return visitor_id in self._active

    def stats(self) -> dict:
        """Return engine statistics."""
        gen_stats = self._generator.stats()
        gen_stats["active_visitors"] = len(self._active)
        return gen_stats
