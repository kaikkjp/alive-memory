"""sim.llm.mock — Deterministic mock LLM for free, reproducible simulations.

Generates realistic CortexOutput without any LLM call. Uses templates
and drive-based rules to produce plausible behavior. Not as nuanced as
a real LLM but perfectly reproducible with a given seed.

Usage:
    from sim.llm.mock import MockCortex
    mock = MockCortex(seed=42)
    result = await mock.complete(messages=[...], system="...")
    # Returns Anthropic-compatible response dict
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field


@dataclass
class MockState:
    """Tracks mock LLM internal state for more realistic behavior."""
    topics_discussed: list[str] = field(default_factory=list)
    visitors_seen: set[str] = field(default_factory=set)
    browse_count: int = 0
    journal_count: int = 0
    post_count: int = 0
    cycle_count: int = 0


# Template dialogue responses by context
_DIALOGUE_TEMPLATES = {
    "greeting": [
        "Welcome. Take your time.",
        "Ah, hello. Come in.",
        "The door sticks a little. Push harder next time.",
        "You're here. I was just thinking about something.",
    ],
    "returning": [
        "Back again. I found something you might like.",
        "I was hoping you'd come back.",
        "Good timing. I just organized that shelf.",
        "You remembered where we are. That means something.",
    ],
    "card_question": [
        "That's a 1993 Bandai Carddass. The holographic ones are from the premium series.",
        "The art style changed after 1995. Before that, everything was hand-illustrated.",
        "Most people don't notice the difference between first and second printing.",
        "I have a few from that era. Let me see...",
    ],
    "general": [
        "Mm. That's interesting.",
        "I've been thinking about that too.",
        "Let me show you something.",
        "Tell me more.",
    ],
    "low_mood": [
        "...",
        "I'm not sure I have the energy for that right now.",
        "Maybe later.",
        "Mm.",
    ],
}

_MONOLOGUE_TEMPLATES = {
    "idle": [
        "The shop is quiet today.",
        "I should organize the back shelf.",
        "That record is skipping again.",
        "The light changes at this hour. Everything looks amber.",
    ],
    "curious": [
        "I wonder about the 1991 prism variants. There might be more.",
        "Something about that article is nagging at me.",
        "I should look into this further.",
        "There's a connection here I'm not seeing yet.",
    ],
    "social": [
        "It's been quiet. I miss having someone to talk to.",
        "The shop feels bigger when it's empty.",
        "Maybe I should post something. See who's out there.",
        "I keep thinking about what they said last time.",
    ],
    "content": [
        "Today felt full somehow.",
        "I learned something new about the market trends.",
        "That conversation stayed with me.",
        "The collection is coming together.",
    ],
    "tired": [
        "My thoughts are slowing down.",
        "I should rest soon.",
        "The words aren't coming easily right now.",
        "Maybe just a few more minutes...",
    ],
}

_BROWSE_TOPICS = [
    "vintage carddass pricing 2026",
    "bandai card art history 1990s",
    "toriyama illustration technique",
    "japanese tcg market trends",
    "card collecting community forums",
    "1993 dragon ball z card variants",
    "holographic printing techniques retro",
    "estate sale vintage collectibles tokyo",
    "card grading standards japan",
    "retro anime merchandise valuation",
]

_JOURNAL_TEMPLATES = [
    "Today I {activity}. {reflection}",
    "{reflection} I keep coming back to {topic}.",
    "The shop was {mood_word} today. {reflection}",
    "Something about {topic} stayed with me. {reflection}",
]

_EXPRESSIONS = ["neutral", "listening", "almost_smile", "thinking",
                "amused", "low", "surprised", "genuine_smile"]
_BODY_STATES = ["sitting", "reaching_back", "leaning_forward",
                "holding_object", "writing", "hands_on_cup"]
_GAZES = ["at_visitor", "at_object", "away_thinking", "down", "window"]


class MockCortex:
    """Deterministic mock that produces realistic cortex outputs.

    Uses templates + rules to generate outputs without any LLM call.
    Perfectly reproducible with a given seed.
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.state = MockState()
        self.call_count = 0

    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        call_site: str = "default",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
        tools: list[dict] | None = None,
    ) -> dict:
        """Generate a mock LLM response in Anthropic-compatible format.

        Parses the incoming messages to understand context, then generates
        a plausible CortexOutput JSON based on drive state and events.
        """
        self.call_count += 1
        self.state.cycle_count += 1

        # Parse context from messages
        context = self._parse_context(messages, system or "")

        # Route to appropriate handler
        if call_site in ("reflect", "sleep"):
            output = self._generate_reflect(context)
        elif call_site == "cortex_maintenance":
            output = self._generate_maintenance(context)
        elif call_site == "taste_eval":
            output = self._generate_taste_eval(context)
        else:
            output = self._generate_cortex(context)

        # Return Anthropic-compatible response
        text = json.dumps(output, ensure_ascii=False)
        return {
            "content": [{"type": "text", "text": text}],
            "usage": {
                "input_tokens": self._estimate_tokens(messages, system),
                "output_tokens": len(text) // 4,
                "cost_usd": 0.0,
            },
        }

    def _generate_cortex(self, ctx: dict) -> dict:
        """Generate a full cortex output based on parsed context."""
        has_visitor = ctx.get("has_visitor", False)
        visitor_message = ctx.get("visitor_message")
        drives = ctx.get("drives", {})

        valence = drives.get("mood_valence", 0.0)
        social_hunger = drives.get("social_hunger", 0.5)
        curiosity = drives.get("curiosity", 0.5)
        expression_need = drives.get("expression_need", 0.3)
        energy = drives.get("energy", 0.8)

        # Determine action based on drives + events
        intentions = []
        dialogue = None
        monologue_pool = "idle"

        if has_visitor and visitor_message:
            # Generate dialogue response
            dialogue = self._pick_dialogue(ctx)
            monologue_pool = "content"
            intentions.append({
                "action": "speak",
                "target": "visitor",
                "content": dialogue,
                "impulse": 0.8 + self.rng.uniform(-0.1, 0.1),
            })
        elif has_visitor:
            # Visitor present but no new message
            dialogue = self.rng.choice(_DIALOGUE_TEMPLATES["general"])
            monologue_pool = "content"
        elif valence < -0.5:
            # Low mood — withdrawn
            monologue_pool = "tired"
            if self.rng.random() < 0.3:
                intentions.append({
                    "action": "write_journal",
                    "target": "journal",
                    "content": self._generate_journal_text(ctx),
                    "impulse": 0.4,
                })
        elif expression_need > 0.35 and self.rng.random() < expression_need:
            # Expression fires proportional to drive strength — at 0.35
            # it has a 35% chance, at 0.6 a 60% chance. Checked before
            # curiosity so it can accumulate during idle stretches.
            monologue_pool = "content"
            intentions.append({
                "action": "post_x",
                "target": "x_timeline",
                "content": self._generate_post_text(ctx),
                "impulse": min(0.8, expression_need + 0.2),
            })
            self.state.post_count += 1
        elif curiosity >= 0.5 and self.rng.random() > 0.3:
            # Curious — check notifications first, fall back to random browse
            notifications = ctx.get("notifications", [])
            if notifications:
                # Pick a notification to read (prefer first = most recent)
                chosen = self.rng.choice(notifications)
                content_id = chosen["content_id"]
                monologue_pool = "curious"
                intentions.append({
                    "action": "read_content",
                    "target": "web",
                    "content": content_id,
                    "detail": {"content_id": content_id},
                    "impulse": min(0.9, curiosity + 0.1),
                })
            else:
                # No notifications — fall back to random browse topic
                topic = self.rng.choice(_BROWSE_TOPICS)
                monologue_pool = "curious"
                intentions.append({
                    "action": "read_content",
                    "target": "web",
                    "content": topic,
                    "impulse": min(0.9, curiosity + 0.1),
                })
            self.state.browse_count += 1
        elif social_hunger > 0.7:
            monologue_pool = "social"
        elif energy < 0.3:
            monologue_pool = "tired"
        else:
            # Default: journal or idle
            if self.rng.random() > 0.6:
                intentions.append({
                    "action": "write_journal",
                    "target": "journal",
                    "content": self._generate_journal_text(ctx),
                    "impulse": 0.4,
                })
                self.state.journal_count += 1
                monologue_pool = "content"

        # Generate expression based on mood
        if valence < -0.3:
            expression = "low"
        elif valence > 0.5:
            expression = self.rng.choice(["almost_smile", "genuine_smile", "amused"])
        elif has_visitor:
            expression = self.rng.choice(["listening", "almost_smile", "thinking"])
        else:
            expression = self.rng.choice(["neutral", "thinking"])

        # Body state
        if has_visitor:
            body_state = self.rng.choice(["sitting", "leaning_forward"])
        elif intentions and intentions[0]["action"] == "write_journal":
            body_state = "writing"
        else:
            body_state = self.rng.choice(["sitting", "hands_on_cup"])

        # Gaze
        if has_visitor:
            gaze = "at_visitor"
        else:
            gaze = self.rng.choice(["away_thinking", "window", "at_object"])

        monologue = self.rng.choice(_MONOLOGUE_TEMPLATES.get(monologue_pool, _MONOLOGUE_TEMPLATES["idle"]))

        # Secondary intention: consider journaling as expression builds.
        # Low impulse (0.3) — basal ganglia would normally filter this,
        # creating measurable divergence for the no_basal_ganglia ablation.
        chosen_action = intentions[0]["action"] if intentions else None
        if not has_visitor and expression_need > 0.2 and chosen_action != "write_journal":
            intentions.append({
                "action": "write_journal",
                "target": "journal",
                "content": self._generate_journal_text(ctx),
                "impulse": 0.3,
            })

        # Drive updates — gentle drift toward equilibrium
        # Pass the chosen action so drive updates distinguish expressive
        # actions (post, journal) from non-expressive ones (browse)
        new_drives = self._compute_drive_updates(drives, has_visitor, chosen_action)

        return {
            "internal_monologue": monologue,
            "dialogue": dialogue,
            "dialogue_language": "en",
            "expression": expression,
            "body_state": body_state,
            "gaze": gaze,
            "resonance": has_visitor and valence > 0.3 and self.rng.random() > 0.7,
            "intentions": intentions,
            "actions": [],
            "memory_updates": self._generate_memory_updates(ctx, dialogue),
            "new_drives": new_drives,
            "next_cycle_hints": [],
        }

    def _generate_reflect(self, ctx: dict) -> dict:
        """Generate a sleep reflection response."""
        return {
            "reflection": "Today had its own rhythm. The quiet moments felt necessary.",
            "connections": [],
            "memory_updates": [],
        }

    def _generate_maintenance(self, ctx: dict) -> dict:
        """Generate a maintenance/journal response."""
        return {
            "journal": self._generate_journal_text(ctx),
            "summary": {
                "moment_count": self.rng.randint(2, 8),
                "emotional_arc": "steady" if self.rng.random() > 0.5 else "rising",
            },
        }

    def _generate_taste_eval(self, ctx: dict) -> dict:
        """Generate a mock taste evaluation with structured scores."""
        # 7 dimension scores via gaussian
        dims = [
            "condition_accuracy", "rarity_authenticity", "price_fairness",
            "historical_significance", "aesthetic_quality", "provenance",
            "personal_resonance",
        ]
        scores = {}
        for dim in dims:
            score = max(0.0, min(10.0, self.rng.gauss(5.5, 1.8)))
            scores[dim] = round(score, 1)

        # Weighted average
        weights = [0.20, 0.20, 0.20, 0.15, 0.15, 0.05, 0.05]
        weighted = sum(scores[d] * w for d, w in zip(dims, weights))

        # Decision based on score
        if weighted > 6.5:
            decision = "accept"
        elif weighted < 4.0:
            decision = "reject"
        else:
            decision = self.rng.choice(["reject", "watchlist", "watchlist"])

        # Template features
        feature_keys = self.rng.sample(
            ["condition", "price_signal", "seller_history", "rarity_cue",
             "market_trend", "photo_quality"],
            k=self.rng.randint(3, 5),
        )
        features = {k: f"mock observation about {k}" for k in feature_keys}

        # Template rationale
        rationale_parts = [
            f"The listing shows {self.rng.choice(['promising', 'mixed', 'concerning'])} signals.",
            f"Price point {'aligns with' if weighted > 5 else 'diverges from'} expected range.",
            f"Seller history {'supports' if self.rng.random() > 0.4 else 'raises questions about'} authenticity.",
            f"Overall assessment: {'worth acquiring' if decision == 'accept' else 'pass for now'}.",
        ]

        return {
            "scores": scores,
            "weighted_score": round(weighted, 2),
            "decision": decision,
            "confidence": round(max(0.0, min(1.0, self.rng.gauss(0.65, 0.15))), 2),
            "features": features,
            "rationale": " ".join(rationale_parts),
        }

    def _pick_dialogue(self, ctx: dict) -> str:
        """Select appropriate dialogue based on context."""
        visitor_message = ctx.get("visitor_message", "")
        visitor_name = ctx.get("visitor_name")
        visit_count = ctx.get("visit_count", 0)
        valence = ctx.get("drives", {}).get("mood_valence", 0.0)

        # Low mood — terse responses
        if valence < -0.5:
            return self.rng.choice(_DIALOGUE_TEMPLATES["low_mood"])

        # Returning visitor
        if visit_count and visit_count > 1:
            return self.rng.choice(_DIALOGUE_TEMPLATES["returning"])

        # Card-related question
        msg_lower = visitor_message.lower()
        if any(w in msg_lower for w in ("card", "vintage", "bandai", "carddass", "dbz", "dragon ball")):
            return self.rng.choice(_DIALOGUE_TEMPLATES["card_question"])

        # First visit greeting
        if any(w in msg_lower for w in ("hello", "hey", "hi", "what is this")):
            return self.rng.choice(_DIALOGUE_TEMPLATES["greeting"])

        return self.rng.choice(_DIALOGUE_TEMPLATES["general"])

    def _generate_journal_text(self, ctx: dict) -> str:
        """Generate a journal entry."""
        activities = ["organized the shelves", "read about card history",
                      "sat quietly", "looked through the window"]
        reflections = ["There's something calming about routine.",
                       "I wonder if anyone will visit tomorrow.",
                       "The collection is growing.",
                       "Some thoughts take time to settle."]
        topics = ["the way light falls on the cards", "what that visitor said",
                  "the 1993 series", "why I keep this shop"]
        mood_words = ["quiet", "peaceful", "restless", "warm", "still"]

        template = self.rng.choice(_JOURNAL_TEMPLATES)
        return template.format(
            activity=self.rng.choice(activities),
            reflection=self.rng.choice(reflections),
            topic=self.rng.choice(topics),
            mood_word=self.rng.choice(mood_words),
        )

    def _generate_post_text(self, ctx: dict) -> str:
        """Generate an X post."""
        posts = [
            "Found a 1992 Carddass with the original backing. The ink hasn't faded at all.",
            "The shop is quiet tonight. Rain on the window.",
            "Someone asked about prism cards today. I pulled out the whole collection.",
            "Three decades and the art still holds up.",
            "Late night inventory. Every card has a story.",
        ]
        return self.rng.choice(posts)

    def _generate_memory_updates(self, ctx: dict, dialogue: str | None) -> list[dict]:
        """Generate memory updates based on the interaction."""
        updates = []
        if ctx.get("has_visitor") and dialogue:
            if self.rng.random() > 0.6:
                updates.append({
                    "type": "visitor_impression",
                    "content": {
                        "summary": "Seemed interested in the collection",
                        "emotional_imprint": "curious",
                    },
                })
        return updates

    def _compute_drive_updates(self, drives: dict, has_visitor: bool,
                               action: str | None) -> dict:
        """Compute action-responsive drive updates.

        TASK-088: Curiosity, arousal, and expression_need now respond
        meaningfully to actions instead of being pinned to equilibrium.
        Homeostatic pulls are weak so action deltas dominate.
        """
        social = drives.get("social_hunger", 0.5)
        curiosity = drives.get("curiosity", 0.5)
        expression = drives.get("expression_need", 0.3)
        energy = drives.get("energy", 0.8)
        valence = drives.get("mood_valence", 0.0)
        arousal = drives.get("mood_arousal", 0.3)

        if has_visitor:
            social = max(0.0, social - 0.05)
            arousal = min(1.0, arousal + 0.05)
            valence = min(1.0, valence + 0.03)
        else:
            social = min(1.0, social + 0.01)

        # ── Expression need: action-specific (TASK-088 Fix 3) ──
        expressive_actions = {"post_x", "write_journal", "speak", "post_x_image"}
        if action in expressive_actions:
            expression = max(0.0, expression - 0.15)
            energy = max(0.0, energy - 0.02)
            valence = min(1.0, valence + 0.02)
        elif action == "read_content":
            expression = min(1.0, expression + 0.04)
            energy = max(0.0, energy - 0.01)
        elif action is not None:
            expression = max(0.0, expression - 0.01)
            energy = max(0.0, energy - 0.02)
        else:
            growth = 0.01
            if social > 0.8:
                growth += 0.02
            expression = min(1.0, expression + growth)

        # ── Curiosity: action-responsive (TASK-088 Fix 1) ──
        if action in ("read_content", "browse_web"):
            curiosity = max(0.0, curiosity - 0.08)
        elif action is None:
            curiosity = min(1.0, curiosity + 0.03)
        else:
            curiosity = min(1.0, curiosity + 0.01)
        curiosity += (0.45 - curiosity) * 0.005

        # ── Arousal: action-responsive (TASK-088 Fix 2) ──
        if action in ("read_content", "write_journal", "speak", "post_x",
                       "post_x_image", "express_thought"):
            arousal = min(1.0, arousal + 0.04)
        elif action is None:
            arousal = max(0.0, arousal - 0.02)
        arousal += (0.35 - arousal) * 0.01

        # Valence drifts toward 0.0 (homeostasis)
        valence += (0.0 - valence) * 0.02

        return {
            "social_hunger": round(max(0, min(1, social)), 3),
            "curiosity": round(max(0, min(1, curiosity)), 3),
            "expression_need": round(max(0, min(1, expression)), 3),
            "energy": round(max(0, min(1, energy)), 3),
            "mood_valence": round(max(-1, min(1, valence)), 3),
            "mood_arousal": round(max(0, min(1, arousal)), 3),
        }

    def _parse_context(self, messages: list[dict], system: str) -> dict:
        """Parse incoming messages to extract simulation context.

        Looks for drive state, visitor presence, conversation,
        and content notifications in the message content.
        """
        ctx: dict = {
            "has_visitor": False,
            "visitor_message": None,
            "visitor_name": None,
            "visit_count": 0,
            "drives": {},
            "notifications": [],  # content notifications from SimContentPool
        }

        full_text = system
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            full_text += "\n" + content

        # Detect visitor presence
        if "visitor" in full_text.lower() and ("says:" in full_text.lower() or "message:" in full_text.lower()):
            ctx["has_visitor"] = True

        # Extract last visitor message
        for msg in reversed(messages):
            content = msg.get("content", "")
            if isinstance(content, str) and "says:" in content.lower():
                # Extract the message after "says:"
                parts = content.split("says:", 1)
                if len(parts) > 1:
                    ctx["visitor_message"] = parts[1].strip()[:200]
                    break

        # Parse drive values from system prompt (drives section)
        import re
        drive_keywords = {
            "social_hunger": "social_hunger",
            "curiosity": "curiosity",
            "expression_need": "expression_need",
            "energy": "energy",
            "mood_valence": "mood_valence",
            "mood_arousal": "mood_arousal",
        }
        for key, label in drive_keywords.items():
            match = re.search(rf'{key}\s*[:=]\s*([-\d.]+)', full_text, re.IGNORECASE)
            if match:
                try:
                    ctx["drives"][label] = float(match.group(1))
                except ValueError:
                    pass

        # Parse content notifications from message text
        # Format: • "title" (source) — topic [id:content_id]
        notif_pattern = re.compile(
            r'\[id:([a-z]+_\d+)\]'
        )
        for match in notif_pattern.finditer(full_text):
            content_id = match.group(1)
            ctx["notifications"].append({"content_id": content_id})

        return ctx

    def _estimate_tokens(self, messages: list[dict], system: str | None) -> int:
        """Rough token estimate for usage reporting."""
        total_chars = len(system or "")
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        total_chars += len(block.get("text", ""))
            else:
                total_chars += len(content)
        return max(1, total_chars // 4)

    def report(self) -> dict:
        """Return summary statistics."""
        return {
            "total_calls": self.call_count,
            "cost_usd": 0.0,
            "browses": self.state.browse_count,
            "journals": self.state.journal_count,
            "posts": self.state.post_count,
        }
