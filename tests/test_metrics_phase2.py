"""Tests for TASK-071 Phase 2 metrics: M3 entropy, M4 knowledge, M5 recall, M9 memory."""

import json
import os
import pytest
import db
import clock
from metrics.m_entropy import compute as compute_entropy, _shannon_entropy, _normalized_entropy
from metrics.m_knowledge import compute as compute_knowledge, _extract_query, _normalize_topic, _cluster_topics
from metrics.m_recall import compute as compute_recall
from metrics.m_memory import compute as compute_memory, _count_memory_refs, _is_prompted
from metrics.collector import collect_all, collect_six_hourly
from metrics.models import MetricResult


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    """Use a temp database for each test, with singleton rows seeded."""
    db._db = None
    original_path = db.DB_PATH
    db.DB_PATH = str(tmp_path / "test.db")
    await db.init_db()
    yield
    await db.close_db()
    db.DB_PATH = original_path


# ── Helpers ──

async def _insert_cycle(cycle_id: str, mode: str = 'ambient',
                         drives: dict = None,
                         monologue: str = None,
                         dialogue: str = None):
    """Insert a cycle_log row for testing."""
    d = drives or {'mood_valence': 0.0, 'mood_arousal': 0.3, 'energy': 0.8}
    await db._exec_write(
        """INSERT INTO cycle_log
           (id, mode, drives, internal_monologue, dialogue, ts)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (cycle_id, mode, json.dumps(d), monologue, dialogue,
         clock.now_utc().isoformat()),
    )


async def _insert_action(cycle_id: str, action: str = 'journal_write',
                          status: str = 'executed'):
    """Insert an action_log row for testing."""
    import uuid
    action_id = str(uuid.uuid4())[:12]
    await db._exec_write(
        """INSERT INTO action_log
           (id, cycle_id, action, status, source)
           VALUES (?, ?, ?, ?, ?)""",
        (action_id, cycle_id, action, status, 'cortex'),
    )


async def _insert_content_pool(title: str, source_channel: str = 'browse'):
    """Insert a content_pool row for testing."""
    import uuid
    item_id = str(uuid.uuid4())[:12]
    await db._exec_write(
        """INSERT INTO content_pool
           (id, fingerprint, source_type, source_channel, content, title,
            status, added_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_id, f'fp-{item_id}', 'url', source_channel, f'https://example.com/{item_id}',
         title, 'unseen', clock.now_utc().strftime('%Y-%m-%d %H:%M:%S')),
    )


async def _insert_visitor(visitor_id: str, name: str, visit_count: int = 1,
                           summary: str = None):
    """Insert a visitors row for testing."""
    await db._exec_write(
        """INSERT INTO visitors
           (id, name, visit_count, first_visit, last_visit, summary)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (visitor_id, name, visit_count,
         clock.now_utc().isoformat(), clock.now_utc().isoformat(), summary),
    )


# ══════════════════════════════════════════════════════════════
# M3: Behavioral Entropy
# ══════════════════════════════════════════════════════════════

class TestM3Entropy:

    def test_shannon_entropy_empty(self):
        assert _shannon_entropy([]) == 0.0

    def test_shannon_entropy_single(self):
        """Single action type → 0 entropy."""
        assert _shannon_entropy(['a', 'a', 'a']) == 0.0

    def test_shannon_entropy_uniform(self):
        """Uniform distribution → max entropy."""
        import math
        actions = ['a', 'b', 'c', 'd']
        expected = math.log2(4)
        assert abs(_shannon_entropy(actions) - expected) < 0.001

    def test_normalized_entropy_range(self):
        """Normalized entropy is always in [0, 1]."""
        assert _normalized_entropy([]) == 0.0
        assert _normalized_entropy(['a']) == 0.0
        assert _normalized_entropy(['a', 'a']) == 0.0
        result = _normalized_entropy(['a', 'b', 'c', 'd'])
        assert 0.99 < result <= 1.0  # uniform = 1.0

    def test_normalized_entropy_skewed(self):
        """Skewed distribution → lower than 1.0."""
        actions = ['a'] * 10 + ['b']
        result = _normalized_entropy(actions)
        assert 0.0 < result < 1.0

    @pytest.mark.asyncio
    async def test_entropy_empty_db(self):
        result = await compute_entropy(hours=24)
        assert result.name == 'behavioral_entropy'
        assert result.value == 0.0
        assert result.details['total_actions'] == 0

    @pytest.mark.asyncio
    async def test_entropy_diverse_actions(self):
        """Multiple action types → positive entropy."""
        await _insert_cycle('c1', mode='ambient')
        await _insert_action('c1', 'journal_write')
        await _insert_action('c1', 'browse_web')
        await _insert_cycle('c2', mode='ambient')
        await _insert_action('c2', 'post_x')
        await _insert_action('c2', 'update_room_state')
        result = await compute_entropy(hours=24)
        assert result.value > 0.0
        assert result.details['unique_actions'] == 4
        assert result.details['total_actions'] == 4

    @pytest.mark.asyncio
    async def test_entropy_single_action_type(self):
        """All same action → 0 entropy."""
        await _insert_cycle('c1', mode='ambient')
        await _insert_action('c1', 'journal_write')
        await _insert_action('c1', 'journal_write')
        await _insert_action('c1', 'journal_write')
        result = await compute_entropy(hours=24)
        assert result.value == 0.0


# ══════════════════════════════════════════════════════════════
# M4: Knowledge Accumulation
# ══════════════════════════════════════════════════════════════

class TestM4Knowledge:

    def test_extract_query(self):
        assert _extract_query('Web search: vintage carddass') == 'vintage carddass'
        assert _extract_query('Some other title') == 'Some other title'
        assert _extract_query(None) == ''
        assert _extract_query('') == ''

    def test_normalize_topic(self):
        assert _normalize_topic('Vintage Carddass!') == 'vintage carddass'
        assert _normalize_topic('  hello   world  ') == 'hello world'

    def test_cluster_topics(self):
        queries = ['vintage carddass', 'vintage carddass', 'pokemon pricing', 'vintage carddass']
        result = _cluster_topics(queries)
        assert result['vintage carddass'] == 3
        assert result['pokemon pricing'] == 1

    def test_cluster_topics_filters_short(self):
        """Topics shorter than _MIN_TOPIC_LEN are excluded."""
        queries = ['ab', 'ok', 'hello world']
        result = _cluster_topics(queries)
        assert 'ab' not in result
        assert 'hello world' in result

    @pytest.mark.asyncio
    async def test_knowledge_empty_db(self):
        result = await compute_knowledge()
        assert result.name == 'knowledge_accumulation'
        assert result.value == 0.0
        assert result.details['unique_topics'] == 0

    @pytest.mark.asyncio
    async def test_knowledge_with_searches(self):
        await _insert_content_pool('Web search: vintage carddass')
        await _insert_content_pool('Web search: pokemon pricing')
        await _insert_content_pool('Web search: vintage carddass')  # duplicate
        result = await compute_knowledge()
        assert result.value == 2.0  # 2 unique topics
        assert result.details['total_searches'] == 3
        assert result.details['unique_topics'] == 2

    @pytest.mark.asyncio
    async def test_knowledge_deep_topics(self):
        """Topics researched 3+ times are counted as deep."""
        for _ in range(4):
            await _insert_content_pool('Web search: bandai carddass history')
        await _insert_content_pool('Web search: something else')
        result = await compute_knowledge()
        assert result.details['deep_topics'] >= 1

    @pytest.mark.asyncio
    async def test_knowledge_ignores_non_browse(self):
        """Only source_channel = 'browse' entries count."""
        await _insert_content_pool('Web search: vintage cards', source_channel='browse')
        await _insert_content_pool('RSS Feed: news headline', source_channel='rss')
        result = await compute_knowledge()
        assert result.details['total_searches'] == 1


# ══════════════════════════════════════════════════════════════
# M5: Visitor Memory Accuracy
# ══════════════════════════════════════════════════════════════

class TestM5Recall:

    @pytest.mark.asyncio
    async def test_recall_no_returning_visitors(self):
        """No visitors with visit_count >= 2 → 0."""
        await _insert_visitor('v1', 'Alice', visit_count=1)
        result = await compute_recall()
        assert result.name == 'visitor_recall'
        assert result.value == 0.0
        assert result.details['total_returning'] == 0

    @pytest.mark.asyncio
    async def test_recall_with_summary(self):
        """Visitor with a summary is considered remembered."""
        await _insert_visitor('v1', 'Alice', visit_count=3,
                              summary='Likes vintage cards')
        result = await compute_recall()
        assert result.details['total_returning'] == 1
        assert result.details['remembered'] == 1
        assert result.value == 100.0

    @pytest.mark.asyncio
    async def test_recall_without_memory(self):
        """Returning visitor with no summary, no file, no injection → not remembered."""
        await _insert_visitor('v1', 'Alice', visit_count=5, summary=None)
        result = await compute_recall()
        assert result.details['total_returning'] == 1
        assert result.details['remembered'] == 0
        assert result.value == 0.0

    @pytest.mark.asyncio
    async def test_recall_mixed(self):
        """Mix of remembered and forgotten visitors."""
        await _insert_visitor('v1', 'Alice', visit_count=3,
                              summary='Likes vintage cards')
        await _insert_visitor('v2', 'Bob', visit_count=2, summary=None)
        result = await compute_recall()
        assert result.details['total_returning'] == 2
        assert result.details['remembered'] == 1
        assert result.value == 50.0


# ══════════════════════════════════════════════════════════════
# M9: Unprompted Memory References
# ══════════════════════════════════════════════════════════════

class TestM9Memory:

    def test_count_memory_refs_empty(self):
        assert _count_memory_refs('') == 0
        assert _count_memory_refs(None) == 0

    def test_count_memory_refs_with_markers(self):
        text = "I remember when I saw that card yesterday. It reminded me of last week."
        count = _count_memory_refs(text)
        assert count >= 3  # "I remember", "yesterday", "last week" + possibly "reminded me of"

    def test_count_memory_refs_no_markers(self):
        text = "The weather is nice today. I like this card."
        assert _count_memory_refs(text) == 0

    def test_is_prompted(self):
        assert _is_prompted("Do you remember that card?") is True
        assert _is_prompted("You told me about this before") is True
        assert _is_prompted("What do you think of this card?") is False
        assert _is_prompted(None) is False

    @pytest.mark.asyncio
    async def test_memory_empty_db(self):
        result = await compute_memory(hours=24)
        assert result.name == 'unprompted_memories'
        assert result.value == 0.0
        assert result.details['total_cycles_scanned'] == 0

    @pytest.mark.asyncio
    async def test_memory_with_references(self):
        """Cycles containing memory markers are counted."""
        await _insert_cycle('c1', mode='ambient',
                            monologue='I remember seeing that vintage card yesterday.')
        await _insert_cycle('c2', mode='ambient',
                            dialogue='This reminds me... last week I found something similar.')
        result = await compute_memory(hours=24)
        assert result.value > 0
        assert result.details['unprompted_references'] > 0
        assert result.details['total_cycles_scanned'] == 2

    @pytest.mark.asyncio
    async def test_memory_no_markers(self):
        """Cycles without memory markers → 0 references."""
        await _insert_cycle('c1', mode='ambient',
                            monologue='The store looks nice today.',
                            dialogue='Hello, welcome!')
        result = await compute_memory(hours=24)
        assert result.value == 0.0

    @pytest.mark.asyncio
    async def test_memory_skips_sleep_mode(self):
        """Sleep-mode cycles should be excluded."""
        await _insert_cycle('c1', mode='sleep',
                            monologue='I remember consolidating memories yesterday.')
        result = await compute_memory(hours=24)
        assert result.details['total_cycles_scanned'] == 0


# ══════════════════════════════════════════════════════════════
# Collector Integration
# ══════════════════════════════════════════════════════════════

class TestCollectorPhase2:

    @pytest.mark.asyncio
    async def test_collect_all_includes_phase2(self):
        """collect_all returns Phase 1 + Phase 2 metrics."""
        await _insert_cycle('c1')
        snapshot = await collect_all()
        names = {m.name for m in snapshot.metrics}
        # Phase 1
        assert 'uptime' in names
        assert 'initiative_rate' in names
        assert 'emotional_range' in names
        # Phase 2
        assert 'behavioral_entropy' in names
        assert 'knowledge_accumulation' in names
        assert 'visitor_recall' in names
        assert 'unprompted_memories' in names
        assert len(snapshot.metrics) == 7

    @pytest.mark.asyncio
    async def test_collect_six_hourly(self):
        """collect_six_hourly returns Phase 2 slow metrics."""
        snapshot = await collect_six_hourly()
        names = {m.name for m in snapshot.metrics}
        assert 'knowledge_accumulation' in names
        assert 'visitor_recall' in names
        assert 'unprompted_memories' in names
        assert len(snapshot.metrics) == 3
