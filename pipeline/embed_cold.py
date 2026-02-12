"""Incremental cold memory embedding pipeline.

Runs during sleep cycle after consolidation. Embeds new conversation_log
and cycle_log entries into cold_memory_vec for semantic search.

Batch-limited to 50 per type per sleep cycle to bound API calls.
Remaining entries are picked up the next night.
"""

from datetime import datetime

import db
from pipeline.embed import embed, embed_model_name


_BATCH_LIMIT = 50


async def embed_new_cold_entries() -> dict:
    """Embed unembedded conversations and monologues into cold_memory_vec.

    Returns stats dict: {conversations_embedded: int, monologues_embedded: int, errors: int}
    """
    stats = {
        'conversations_embedded': 0,
        'monologues_embedded': 0,
        'errors': 0,
    }

    model_name = embed_model_name()

    # 1. Embed conversations
    unembedded_convos = await db.get_unembedded_conversations(limit=_BATCH_LIMIT)
    for row in unembedded_convos:
        try:
            # Build text for embedding: role-prefixed message
            role = row['role']
            text = row['text']
            embed_text = f"{role}: {text}"

            vec = await embed(embed_text)
            if vec is None:
                stats['errors'] += 1
                continue

            ts = datetime.fromisoformat(row['ts']) if isinstance(row['ts'], str) else row['ts']

            await db.insert_cold_embedding(
                source_type='conversation',
                source_id=row['id'],
                text_content=embed_text,
                ts=ts,
                embedding=vec,
                embed_model=model_name,
            )
            stats['conversations_embedded'] += 1

        except Exception as e:
            print(f"[EmbedCold] Failed to embed conversation {row['id']}: {e}")
            stats['errors'] += 1

    # 2. Embed monologues
    unembedded_monos = await db.get_unembedded_monologues(limit=_BATCH_LIMIT)
    for row in unembedded_monos:
        try:
            monologue = row['internal_monologue']
            # Include dialogue snippet for richer context if available
            dialogue = row.get('dialogue', '')
            if dialogue:
                embed_text = f"thinking: {monologue} | saying: {dialogue[:200]}"
            else:
                embed_text = f"thinking: {monologue}"

            vec = await embed(embed_text)
            if vec is None:
                stats['errors'] += 1
                continue

            ts = datetime.fromisoformat(row['ts']) if isinstance(row['ts'], str) else row['ts']

            await db.insert_cold_embedding(
                source_type='monologue',
                source_id=row['id'],
                text_content=embed_text,
                ts=ts,
                embedding=vec,
                embed_model=model_name,
            )
            stats['monologues_embedded'] += 1

        except Exception as e:
            print(f"[EmbedCold] Failed to embed monologue {row['id']}: {e}")
            stats['errors'] += 1

    return stats
