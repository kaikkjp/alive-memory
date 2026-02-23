"""Tests for sim.content_pool — SimContentPool.

TASK-086 test coverage:
- Pool has exactly 100 items
- Surfacing rate: ~50 items per 100 cycles
- Consumed items return full summary
- Pool resets when all items consumed
- Notifications match production format
- Invalid content_ids are ignored (not counted)
- Deterministic with same seed
- Mock cortex parses notifications from message text
"""

import pytest

from sim.content_pool import SimContentPool
from sim.data.content_pool_data import CONTENT_POOL


class TestContentPoolData:
    """Validate the curated content pool dataset."""

    def test_exactly_100_items(self):
        assert len(CONTENT_POOL) == 100

    def test_all_ids_unique(self):
        ids = [item["id"] for item in CONTENT_POOL]
        assert len(ids) == len(set(ids))

    def test_required_fields(self):
        required = {"id", "title", "summary", "source", "topic", "interest_score"}
        for item in CONTENT_POOL:
            missing = required - set(item.keys())
            assert not missing, f"Item {item.get('id', '?')} missing: {missing}"

    def test_interest_scores_in_range(self):
        for item in CONTENT_POOL:
            score = item["interest_score"]
            assert 0.0 <= score <= 1.0, (
                f"Item {item['id']} has interest_score {score} out of range"
            )

    def test_cluster_distribution(self):
        """Each cluster prefix has items."""
        from collections import Counter
        prefixes = Counter(item["id"].split("_")[0] for item in CONTENT_POOL)
        assert set(prefixes.keys()) == {"tcg", "jpn", "phi", "atm", "misc"}
        for prefix, count in prefixes.items():
            assert count >= 10, f"Cluster {prefix} has only {count} items"


class TestSimContentPool:
    """Test SimContentPool surfacing and consumption."""

    def test_deterministic_with_same_seed(self):
        pool_a = SimContentPool(seed=42)
        pool_b = SimContentPool(seed=42)
        notifs_a = [pool_a.get_notifications(c) for c in range(50)]
        notifs_b = [pool_b.get_notifications(c) for c in range(50)]
        assert notifs_a == notifs_b

    def test_different_seeds_differ(self):
        pool_a = SimContentPool(seed=42)
        pool_b = SimContentPool(seed=99)
        notifs_a = [pool_a.get_notifications(c) for c in range(50)]
        notifs_b = [pool_b.get_notifications(c) for c in range(50)]
        assert notifs_a != notifs_b

    def test_surfacing_rate(self):
        """~50 items surfaced per 100 cycles (Poisson ~0.5/cycle)."""
        pool = SimContentPool(seed=42)
        total_surfaced = 0
        for cycle in range(100):
            notifs = pool.get_notifications(cycle)
            total_surfaced += len(notifs)
        # Expect roughly 30-80 surfaced items (wide range for randomness)
        assert 20 <= total_surfaced <= 90, (
            f"Surfaced {total_surfaced} items in 100 cycles — outside expected range"
        )

    def test_max_items_per_cycle(self):
        """Never more than max_items per cycle."""
        pool = SimContentPool(seed=42)
        for cycle in range(200):
            notifs = pool.get_notifications(cycle, max_items=3)
            assert len(notifs) <= 3

    def test_notification_format(self):
        """Notifications match production format."""
        pool = SimContentPool(seed=42)
        # Run until we get at least one notification
        notifs = []
        for cycle in range(100):
            notifs = pool.get_notifications(cycle)
            if notifs:
                break
        assert len(notifs) > 0, "No notifications surfaced in 100 cycles"

        notif = notifs[0]
        assert "type" in notif and notif["type"] == "content"
        assert "title" in notif and isinstance(notif["title"], str)
        assert "source" in notif and isinstance(notif["source"], str)
        assert "content_id" in notif and isinstance(notif["content_id"], str)
        assert "topic" in notif and isinstance(notif["topic"], str)
        assert "interest_score" in notif

    def test_consume_returns_full_item(self):
        """Consumed items include summary text."""
        pool = SimContentPool(seed=42)
        item = pool.consume("tcg_001")
        assert item is not None
        assert "summary" in item
        assert len(item["summary"]) > 50
        assert item["title"] == CONTENT_POOL[0]["title"]

    def test_consume_marks_seen_and_consumed(self):
        pool = SimContentPool(seed=42)
        pool.consume("tcg_001")
        stats = pool.stats()
        assert "tcg_001" in stats["consumed_ids"]
        assert stats["consumed_count"] == 1
        assert "tcg_001" in pool.seen_ids

    def test_consume_invalid_id_returns_none(self):
        """Invalid content_ids return None and are NOT counted."""
        pool = SimContentPool(seed=42)
        result = pool.consume("tcg_999")
        assert result is None
        stats = pool.stats()
        assert stats["consumed_count"] == 0
        assert "tcg_999" not in stats["consumed_ids"]

    def test_consume_hallucinated_id_ignored(self):
        """Completely bogus IDs don't corrupt metrics."""
        pool = SimContentPool(seed=42)
        result = pool.consume("fake_hallucinated_id")
        assert result is None
        assert pool.stats()["consumed_count"] == 0

    def test_pool_resets_when_all_seen(self):
        """Pool resets seen_ids when all items have been surfaced."""
        pool = SimContentPool(seed=42)
        # Force-mark all items as seen
        for item in pool.pool:
            pool.seen_ids.add(item["id"])
        assert len(pool.seen_ids) == 100

        # Next get_notifications should reset and return items
        # Run until we get notifications (may take a few cycles due to Poisson)
        got_notifs = False
        for cycle in range(50):
            notifs = pool.get_notifications(cycle)
            if notifs:
                got_notifs = True
                break

        assert got_notifs, "Pool did not surface items after reset"
        # seen_ids should have been cleared then re-populated
        assert len(pool.seen_ids) < 100

    def test_stats(self):
        pool = SimContentPool(seed=42)
        stats = pool.stats()
        assert stats["total_items"] == 100
        assert stats["seen_count"] == 0
        assert stats["consumed_count"] == 0
        assert stats["consumed_ids"] == []

    def test_no_duplicate_notifications_in_cycle(self):
        """A single cycle should not surface the same item twice."""
        pool = SimContentPool(seed=42)
        for cycle in range(200):
            notifs = pool.get_notifications(cycle)
            ids = [n["content_id"] for n in notifs]
            assert len(ids) == len(set(ids)), (
                f"Duplicate in cycle {cycle}: {ids}"
            )


class TestMockCortexNotificationParsing:
    """Test that MockCortex parses content notifications from messages."""

    def test_parse_notifications_from_message(self):
        from sim.llm.mock import MockCortex

        mock = MockCortex(seed=42)
        messages = [{
            "role": "user",
            "content": (
                'You notice some things in your feed:\n'
                '  \u2022 "Some title" (source) \u2014 topic [id:tcg_001]\n'
                '  \u2022 "Another title" (source2) \u2014 topic2 [id:phi_003]\n'
            ),
        }]
        ctx = mock._parse_context(messages, "")
        assert len(ctx["notifications"]) == 2
        assert ctx["notifications"][0]["content_id"] == "tcg_001"
        assert ctx["notifications"][1]["content_id"] == "phi_003"

    def test_no_notifications_when_absent(self):
        from sim.llm.mock import MockCortex

        mock = MockCortex(seed=42)
        messages = [{"role": "user", "content": "No new events. Continue your day."}]
        ctx = mock._parse_context(messages, "")
        assert ctx["notifications"] == []

    @pytest.mark.asyncio
    async def test_curiosity_with_notifications_targets_content_id(self):
        """When curiosity is high and notifications present, mock emits
        read_content with actual content_id, not random browse topic."""
        from sim.llm.mock import MockCortex
        import json

        mock = MockCortex(seed=42)
        system = "curiosity: 0.8\nenergy: 0.8\nexpression_need: 0.1"
        messages = [{
            "role": "user",
            "content": (
                'You notice some things in your feed:\n'
                '  \u2022 "Some title" (cllct) \u2014 tcg_market [id:tcg_005]\n'
            ),
        }]

        # Run multiple times to catch at least one read_content
        found_content_read = False
        for _ in range(20):
            mock_instance = MockCortex(seed=42 + _)
            resp = await mock_instance.complete(
                messages=messages, system=system, call_site="cortex",
            )
            output = json.loads(resp["content"][0]["text"])
            for intent in output.get("intentions", []):
                if intent.get("action") == "read_content":
                    detail = intent.get("detail", {})
                    if detail.get("content_id") == "tcg_005":
                        found_content_read = True
                        break
            if found_content_read:
                break

        assert found_content_read, (
            "Mock cortex never emitted read_content targeting tcg_005"
        )
