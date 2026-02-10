"""Perception Gate — strip forbidden internals, make everything diegetic. No LLM."""

from pipeline.sensorium import Perception
import db


FORBIDDEN_FEATURES = {'urls'}  # raw URLs go through enrichment, not to Cortex


def perception_gate(perceptions: list[Perception], visitor_id: str = None) -> list[Perception]:
    """Strip forbidden internals. Make everything diegetic."""

    gated = []
    for p in perceptions:
        clean = Perception(
            p_type=p.p_type,
            source=diegetic_source(p.source),
            ts=p.ts,
            content=p.content,
            features={k: v for k, v in p.features.items() if k not in FORBIDDEN_FEATURES},
            salience=p.salience,
        )
        gated.append(clean)
    return gated


def diegetic_source(source: str) -> str:
    """Translate system IDs into character-world language."""
    if not source.startswith('visitor:'):
        return source

    # We can't do async here in the gate, so we return the source as-is
    # and let the caller handle diegetic naming via the visitor object
    return source


async def diegetic_source_async(source: str) -> str:
    """Async version — translate system IDs into character-world language."""
    if not source.startswith('visitor:'):
        return source

    visitor_id = source.split(':')[1]
    visitor = await db.get_visitor(visitor_id)

    if not visitor:
        return "someone new"

    trust_map = {
        'stranger': "someone I don't recognize",
        'returner': "someone who's been here before",
        'regular': "a familiar face",
        'familiar': "someone I know well",
    }

    if visitor.name:
        return visitor.name
    return trust_map.get(visitor.trust_level, "someone")
