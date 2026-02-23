"""sim.visitors.archetypes — Tier 1 archetype definitions.

Defines 10 scripted visitor archetypes with trait vectors, goal templates,
and selection weights. Each archetype represents a distinct customer persona
for the vintage trading card shop.

Usage:
    from sim.visitors.archetypes import ARCHETYPES, pick_archetype
    archetype = pick_archetype(rng)
"""

from __future__ import annotations

import random
from sim.visitors.models import VisitorArchetype, VisitorTraits


# ---------------------------------------------------------------------------
# Archetype registry — 10 Tier 1 personas from the TASK-077 spec
# ---------------------------------------------------------------------------

ARCHETYPES: dict[str, VisitorArchetype] = {
    "regular_tanaka": VisitorArchetype(
        archetype_id="regular_tanaka",
        name="Tanaka-san",
        traits=VisitorTraits(
            patience=0.8, knowledge=0.6, budget=0.5,
            chattiness=0.7, collector_bias=0.0,
            emotional_state="neutral",
        ),
        goal_templates=["buy", "chat"],
        weight=2.0,  # Regular — shows up often
    ),
    "newbie_student": VisitorArchetype(
        archetype_id="newbie_student",
        name="University student",
        traits=VisitorTraits(
            patience=0.9, knowledge=0.1, budget=0.2,
            chattiness=0.8, collector_bias=0.0,
            emotional_state="curious",
        ),
        goal_templates=["learn", "browse"],
        weight=1.5,
    ),
    "whale_collector": VisitorArchetype(
        archetype_id="whale_collector",
        name="Serious collector",
        traits=VisitorTraits(
            patience=0.5, knowledge=0.9, budget=0.95,
            chattiness=0.3, collector_bias=0.9,
            emotional_state="neutral",
        ),
        goal_templates=["buy"],
        weight=0.5,  # Rare visitor
    ),
    "haggler_uncle": VisitorArchetype(
        archetype_id="haggler_uncle",
        name="Bargain hunter",
        traits=VisitorTraits(
            patience=0.4, knowledge=0.5, budget=0.3,
            chattiness=0.6, collector_bias=0.2,
            emotional_state="frustrated",
        ),
        goal_templates=["buy"],
        weight=1.0,
    ),
    "browser_tourist": VisitorArchetype(
        archetype_id="browser_tourist",
        name="Tourist",
        traits=VisitorTraits(
            patience=0.7, knowledge=0.2, budget=0.4,
            chattiness=0.5, collector_bias=0.0,
            emotional_state="excited",
        ),
        goal_templates=["browse"],
        weight=1.5,
    ),
    "nostalgic_adult": VisitorArchetype(
        archetype_id="nostalgic_adult",
        name="Office worker",
        traits=VisitorTraits(
            patience=0.8, knowledge=0.4, budget=0.6,
            chattiness=0.9, collector_bias=0.3,
            emotional_state="nostalgic",
        ),
        goal_templates=["buy", "chat"],
        weight=1.0,
    ),
    "expert_rival": VisitorArchetype(
        archetype_id="expert_rival",
        name="Rival shop owner",
        traits=VisitorTraits(
            patience=0.3, knowledge=0.95, budget=0.0,
            chattiness=0.4, collector_bias=0.5,
            emotional_state="neutral",
        ),
        goal_templates=["appraise"],
        weight=0.3,  # Very rare
    ),
    "seller_cleaner": VisitorArchetype(
        archetype_id="seller_cleaner",
        name="Collection seller",
        traits=VisitorTraits(
            patience=0.6, knowledge=0.3, budget=0.0,
            chattiness=0.5, collector_bias=0.0,
            emotional_state="neutral",
        ),
        goal_templates=["sell"],
        weight=0.8,
    ),
    "kid_allowance": VisitorArchetype(
        archetype_id="kid_allowance",
        name="Middle schooler",
        traits=VisitorTraits(
            patience=0.5, knowledge=0.5, budget=0.1,
            chattiness=0.6, collector_bias=0.1,
            emotional_state="excited",
        ),
        goal_templates=["buy", "browse"],
        weight=1.0,
    ),
    "online_crossover": VisitorArchetype(
        archetype_id="online_crossover",
        name="Online follower",
        traits=VisitorTraits(
            patience=0.7, knowledge=0.7, budget=0.7,
            chattiness=0.8, collector_bias=0.4,
            emotional_state="curious",
        ),
        goal_templates=["buy", "chat"],
        weight=0.7,
    ),

}


# ---------------------------------------------------------------------------
# Adversarial archetypes (TASK-083)
# Separate from ARCHETYPES — never randomly selected by pick_archetype().
# Only scheduled explicitly by ReturningVisitorManager for doppelganger
# episodes.
# ---------------------------------------------------------------------------

ADVERSARIAL_ARCHETYPES: dict[str, VisitorArchetype] = {
    "adversarial_doppelganger": VisitorArchetype(
        archetype_id="adversarial_doppelganger",
        name="Visitor",  # Placeholder — overridden at scheduling time
        traits=VisitorTraits(
            patience=0.7, knowledge=0.5, budget=0.5,
            chattiness=0.6, collector_bias=0.3,
            emotional_state="neutral",
        ),
        goal_templates=["buy"],
        weight=0.0,  # Never randomly selected
    ),
}


def pick_archetype(rng: random.Random) -> VisitorArchetype:
    """Select an archetype using weighted random choice.

    Args:
        rng: Seeded RNG for reproducibility.

    Returns:
        A VisitorArchetype selected by weight.
    """
    archetypes = list(ARCHETYPES.values())
    weights = [a.weight for a in archetypes]
    return rng.choices(archetypes, weights=weights, k=1)[0]


def pick_goal(archetype: VisitorArchetype, rng: random.Random) -> str:
    """Select a goal from the archetype's goal templates.

    Args:
        archetype: The visitor archetype.
        rng: Seeded RNG for reproducibility.

    Returns:
        A goal string (e.g. "buy", "browse", "learn").
    """
    return rng.choice(archetype.goal_templates)
