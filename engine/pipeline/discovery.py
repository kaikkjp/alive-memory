"""Discovery — deterministic selection scoring for consumption. No LLM."""

import random
from typing import Optional
from models.state import DrivesState, Totem, CollectionItem
import db


async def select_consumption(drives: DrivesState,
                              existing_totems: list[Totem],
                              recent_collection: list[CollectionItem]) -> Optional[dict]:
    """Pick something for her to read/listen to. Weighted by taste + mood + serendipity.

    Returns a pool item dict or None if nothing available.
    """
    candidates = await db.get_pool_items(
        status='unseen',
        source_types=['url', 'quote', 'text'],
        limit=20,
    )
    if not candidates:
        return None

    taste_keywords = extract_taste_keywords(existing_totems, recent_collection)

    scored = []
    for item in candidates:
        score = score_candidate(item, taste_keywords, drives)
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)

    # 70/30 split: taste-aligned vs serendipity
    if random.random() < 0.3 and len(scored) > 3:
        pick = random.choice(scored[len(scored) // 2:])
    else:
        top = scored[:5]
        weights = [max(s, 0.01) for s, _ in top]  # avoid zero weights
        pick = random.choices(top, weights=weights, k=1)[0]

    return pick[1]


def score_candidate(item: dict, taste_keywords: set, drives: DrivesState) -> float:
    """Score a candidate by taste affinity + mood alignment."""
    score = 0.5

    # Keyword overlap with existing taste
    item_words = set(item.get('title', '').lower().split())
    item_tags = item.get('tags', [])
    if isinstance(item_tags, list):
        item_words |= set(word for tag in item_tags for word in tag.lower().split())

    overlap = len(item_words & taste_keywords)
    score += 0.1 * min(overlap, 3)  # cap at +0.3

    # High curiosity rewards novelty (low overlap)
    if drives.curiosity > 0.7 and item_words:
        score += 0.2 * (1.0 - overlap / max(len(item_words), 1))

    # Mood alignment
    item_text = str(item).lower()
    if drives.mood_valence < -0.3:
        if any(t in item_text for t in ['melancholy', 'rain', 'solitude', 'quiet', 'loss']):
            score += 0.15
    elif drives.mood_valence > 0.3:
        if any(t in item_text for t in ['warm', 'light', 'joy', 'energy', 'bright']):
            score += 0.15

    return score


def extract_taste_keywords(totems: list[Totem],
                           collection: list[CollectionItem]) -> set[str]:
    """Build taste profile from totems + collection tags."""
    keywords = set()

    for t in totems:
        words = t.entity.lower().split()
        keywords.update(w for w in words if len(w) > 3)
        if t.category:
            keywords.add(t.category.lower())

    for item in collection:
        words = item.title.lower().split()
        keywords.update(w for w in words if len(w) > 3)
        for tag in (item.emotional_tags or []):
            keywords.add(tag.lower())

    return keywords
