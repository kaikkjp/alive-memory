"""M4: Knowledge Accumulation.

Source: content_pool table (source_channel = 'browse') + data/memory/browse/ MD files.
Calculation: Count unique topics browsed, deep research threads (3+ revisits).

Note: The TASK-071 spec references browse_history (TASK-069), but browse data
lives in content_pool WHERE source_channel = 'browse'. The title column contains
"Web search: {query}" — we strip that prefix to get the raw query.
"""

import os
import re
from collections import Counter
from datetime import timedelta
from metrics.models import MetricResult
import clock
import db.connection as _connection


# Prefix used in content_pool.title for browse actions
_BROWSE_PREFIX = 'Web search: '
# Minimum word length for topic extraction
_MIN_TOPIC_LEN = 3


def _extract_query(title: str) -> str:
    """Strip 'Web search: ' prefix from content_pool title."""
    if title and title.startswith(_BROWSE_PREFIX):
        return title[len(_BROWSE_PREFIX):].strip()
    return (title or '').strip()


def _normalize_topic(query: str) -> str:
    """Normalize a query string into a canonical topic key.

    Lowercases, strips punctuation, collapses whitespace.
    """
    q = query.lower().strip()
    q = re.sub(r'[^\w\s]', ' ', q)
    q = re.sub(r'\s+', ' ', q).strip()
    return q


def _cluster_topics(queries: list[str]) -> dict[str, int]:
    """Simple keyword-based topic clustering.

    Groups queries by their normalized form. Returns {topic: count}.
    No LLM needed — just deduplication by normalization.
    """
    counts: Counter[str] = Counter()
    for q in queries:
        topic = _normalize_topic(q)
        if len(topic) >= _MIN_TOPIC_LEN:
            counts[topic] += 1
    return dict(counts)


async def compute() -> MetricResult:
    """Compute M4 knowledge accumulation metric."""
    conn = await _connection.get_db()

    # Query all browse entries from content_pool
    cursor = await conn.execute(
        """SELECT title, added_at, status
           FROM content_pool
           WHERE source_channel = 'browse'
           ORDER BY added_at ASC"""
    )
    rows = await cursor.fetchall()

    queries = [_extract_query(r['title']) for r in rows if r['title']]
    queries = [q for q in queries if q]  # filter empty

    # Cluster into topics
    topic_counts = _cluster_topics(queries)
    unique_topics = len(topic_counts)
    deep_topics = {t: c for t, c in topic_counts.items() if c >= 3}

    # Also count browse MD files if they exist
    browse_dir = os.path.join('data', 'memory', 'browse')
    md_file_count = 0
    if os.path.isdir(browse_dir):
        md_file_count = len([f for f in os.listdir(browse_dir) if f.endswith('.md')])

    # Growth rate: topics per day alive
    total_browse = len(rows)
    days_span = 1
    if len(rows) >= 2:
        try:
            from datetime import datetime, timezone
            first = rows[0]['added_at']
            last = rows[-1]['added_at']
            first_dt = datetime.fromisoformat(str(first).replace('Z', '+00:00'))
            last_dt = datetime.fromisoformat(str(last).replace('Z', '+00:00'))
            days_span = max(1, (last_dt - first_dt).days + 1)
        except (ValueError, TypeError):
            days_span = 1

    growth_rate = unique_topics / days_span if days_span > 0 else 0.0

    display = (
        f"{unique_topics} unique topics explored, "
        f"{len(deep_topics)} deep research threads"
    )

    return MetricResult(
        name='knowledge_accumulation',
        value=float(unique_topics),
        details={
            'unique_topics': unique_topics,
            'deep_topics': len(deep_topics),
            'deep_topic_names': list(deep_topics.keys())[:10],
            'total_searches': total_browse,
            'browse_md_files': md_file_count,
            'growth_rate_per_day': round(growth_rate, 2),
            'days_span': days_span,
        },
        display=display,
    )
