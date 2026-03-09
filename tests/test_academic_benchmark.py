"""Tests for the academic benchmark harness.

Tests the harness infrastructure (scoring, runner, adapters) without
requiring actual benchmark datasets or API keys.
"""

from __future__ import annotations

import pytest

from benchmarks.academic.harness.base import (
    BenchmarkRunResult,
    ConversationTurn,
    EvalResult,
    GroundTruth,
    MemoryQuery,
    SystemMetrics,
)
from benchmarks.academic.harness.scoring import (
    abstention_score,
    exact_match,
    normalize_text,
    rouge_l,
    substring_match,
    token_f1,
)


# --- Scoring tests ---


class TestNormalizeText:
    def test_basic(self):
        assert normalize_text("Hello, World!") == "hello world"

    def test_whitespace(self):
        assert normalize_text("  lots   of   spaces  ") == "lots of spaces"

    def test_punctuation(self):
        assert normalize_text("don't stop! yes.") == "don t stop yes"


class TestTokenF1:
    def test_perfect_match(self):
        scores = token_f1("hello world", "hello world")
        assert scores["f1"] == 1.0

    def test_no_match(self):
        scores = token_f1("hello", "goodbye")
        assert scores["f1"] == 0.0

    def test_partial_match(self):
        scores = token_f1("the cat sat", "the dog sat")
        assert 0.0 < scores["f1"] < 1.0
        assert scores["precision"] > 0
        assert scores["recall"] > 0

    def test_empty_prediction(self):
        scores = token_f1("", "hello world")
        assert scores["f1"] == 0.0

    def test_empty_both(self):
        scores = token_f1("", "")
        assert scores["f1"] == 1.0


class TestExactMatch:
    def test_match(self):
        assert exact_match("Hello World", "hello world") == 1.0

    def test_no_match(self):
        assert exact_match("hello", "goodbye") == 0.0


class TestSubstringMatch:
    def test_hit(self):
        assert substring_match("The answer is Paris", ["Paris"]) == 1.0

    def test_miss(self):
        assert substring_match("The answer is London", ["Paris"]) == 0.0

    def test_multiple_refs(self):
        assert substring_match("I like cats", ["dogs", "cats"]) == 1.0

    def test_empty_refs(self):
        assert substring_match("anything", []) == 0.0


class TestRougeL:
    def test_perfect(self):
        scores = rouge_l("the cat sat on the mat", "the cat sat on the mat")
        assert scores["rouge_l_f1"] == 1.0

    def test_no_overlap(self):
        scores = rouge_l("hello", "goodbye")
        assert scores["rouge_l_f1"] == 0.0

    def test_partial(self):
        scores = rouge_l("the cat sat on mat", "the dog sat on mat")
        assert 0.0 < scores["rouge_l_f1"] < 1.0


class TestAbstentionScore:
    def test_correct_abstention(self):
        assert abstention_score("I don't know", should_abstain=True) == 1.0

    def test_incorrect_answer_when_should_abstain(self):
        assert abstention_score("The answer is Paris", should_abstain=True) == 0.0

    def test_correct_answer(self):
        assert abstention_score("The answer is Paris", should_abstain=False) == 1.0

    def test_incorrect_abstention(self):
        assert abstention_score("I don't know", should_abstain=False) == 0.0


# --- Data class tests ---


class TestConversationTurn:
    def test_create(self):
        turn = ConversationTurn(
            role="user",
            content="Hello",
            turn_id=0,
            session_id="s1",
        )
        assert turn.role == "user"
        assert turn.content == "Hello"


class TestMemoryQuery:
    def test_create(self):
        q = MemoryQuery(
            query_id="q1",
            question="What is the capital?",
            category="factual",
        )
        assert q.query_id == "q1"


class TestSystemMetrics:
    def test_median_empty(self):
        m = SystemMetrics()
        assert m.median_query_latency_ms == 0.0

    def test_median(self):
        m = SystemMetrics(query_latencies_ms=[100, 200, 300, 400, 500])
        assert m.median_query_latency_ms == 300.0

    def test_p95(self):
        m = SystemMetrics(query_latencies_ms=list(range(100)))
        assert m.p95_query_latency_ms == 95.0


class TestBenchmarkRunResult:
    def test_overall_score_f1(self):
        r = BenchmarkRunResult(
            system_id="test",
            benchmark_id="test",
            aggregate_scores={"f1": 0.75, "accuracy": 0.80},
        )
        assert r.overall_score() == 0.75  # prefers f1

    def test_overall_score_accuracy(self):
        r = BenchmarkRunResult(
            system_id="test",
            benchmark_id="test",
            aggregate_scores={"accuracy": 0.80},
        )
        assert r.overall_score() == 0.80

    def test_overall_score_empty(self):
        r = BenchmarkRunResult(system_id="test", benchmark_id="test")
        assert r.overall_score() == 0.0


# --- System adapter tests (no API calls) ---


class TestNoMemorySystem:
    @pytest.mark.asyncio
    async def test_discards_history(self):
        from benchmarks.academic.systems.no_memory import NoMemorySystem

        system = NoMemorySystem()
        await system.setup({})

        turns = [
            ConversationTurn(role="user", content="Hello", turn_id=0),
            ConversationTurn(role="assistant", content="Hi!", turn_id=1),
        ]
        await system.add_conversation(turns)

        metrics = await system.get_metrics()
        assert metrics.storage_bytes == 0
        assert metrics.memory_count == 0


class TestFullContextSystem:
    @pytest.mark.asyncio
    async def test_stores_history(self):
        from benchmarks.academic.systems.full_context import FullContextSystem

        system = FullContextSystem()
        await system.setup({})

        turns = [
            ConversationTurn(role="user", content="Hello", turn_id=0),
            ConversationTurn(role="assistant", content="Hi!", turn_id=1),
        ]
        await system.add_conversation(turns)

        metrics = await system.get_metrics()
        assert metrics.memory_count == 2
        assert metrics.storage_bytes > 0

    @pytest.mark.asyncio
    async def test_reset(self):
        from benchmarks.academic.systems.full_context import FullContextSystem

        system = FullContextSystem()
        await system.setup({})
        await system.add_conversation([
            ConversationTurn(role="user", content="Hello", turn_id=0),
        ])
        await system.reset()

        metrics = await system.get_metrics()
        assert metrics.memory_count == 0


# --- CLI test ---


class TestCLIList:
    @pytest.mark.asyncio
    async def test_list(self, capsys):
        from benchmarks.academic.__main__ import cmd_list

        class FakeArgs:
            pass

        await cmd_list(FakeArgs())
        captured = capsys.readouterr()
        assert "locomo" in captured.out
        assert "alive" in captured.out
