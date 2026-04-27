"""Tests for the academic benchmark harness.

Tests the harness infrastructure (scoring, runner, adapters) without
requiring actual benchmark datasets or API keys.
"""

from __future__ import annotations

import pytest

from benchmarks.academic.harness.base import (
    BenchmarkRunResult,
    ConversationTurn,
    MemoryQuery,
    SystemMetrics,
)
from benchmarks.academic.harness.scoring import (
    _GENERIC_JUDGE_PROMPT,
    _LONGMEMEVAL_JUDGE_PROMPTS,
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
        await system.add_conversation(
            [
                ConversationTurn(role="user", content="Hello", turn_id=0),
            ]
        )
        await system.reset()

        metrics = await system.get_metrics()
        assert metrics.memory_count == 0


# --- CLI test ---


class TestConsolidateMetrics:
    def test_median_empty(self):
        m = SystemMetrics()
        assert m.median_consolidate_latency_ms == 0.0

    def test_median(self):
        m = SystemMetrics(consolidate_latencies_ms=[50, 100, 150, 200, 250])
        assert m.median_consolidate_latency_ms == 150.0

    def test_p95(self):
        m = SystemMetrics(consolidate_latencies_ms=list(range(100)))
        assert m.p95_consolidate_latency_ms == 95.0


class TestMemoryAgentBenchCategories:
    def test_categories(self):
        from benchmarks.academic.datasets.memoryagentbench import _CATEGORY_ALIASES, CATEGORIES

        assert "accurate_retrieval" in CATEGORIES
        assert "conflict_resolution" in CATEGORIES
        assert "selective_forgetting" not in CATEGORIES
        assert _CATEGORY_ALIASES["retrieval"] == "accurate_retrieval"
        assert _CATEGORY_ALIASES["selective_forgetting"] == "conflict_resolution"

    def test_parse_hf_rows_creates_instances(self):
        from benchmarks.academic.datasets.memoryagentbench import MemoryAgentBenchDataset

        dataset = MemoryAgentBenchDataset()
        dataset._parse_hf_rows(
            [
                {
                    "_split": "Accurate_Retrieval",
                    "context": "Document 1:\nNormandy is in France.",
                    "questions": ["Where is Normandy?"],
                    "answers": [["France", "in France"]],
                    "metadata": {
                        "source": "sample",
                        "qa_pair_ids": ["qa_1"],
                        "keypoints": ["Normandy is in France."],
                    },
                }
            ]
        )

        assert len(dataset.get_instances()) == 1
        # Query IDs are namespaced by row_id so duplicate qa_pair_ids across
        # rows/splits cannot silently overwrite each other.
        qid = dataset.get_queries()[0].query_id
        assert qid == "Accurate_Retrieval_0000::qa_1"
        assert dataset.get_queries()[0].category == "accurate_retrieval"
        gt = dataset.get_ground_truth()[qid]
        assert gt.answer == "France"
        assert "in France" in gt.metadata["answer_aliases"]

    def test_split_context_honors_smoke_chunk_limit(self, monkeypatch):
        from benchmarks.academic.datasets.memoryagentbench import _split_context

        monkeypatch.setenv("ALIVE_BENCH_MAX_CONTEXT_CHUNKS", "1")
        chunks = _split_context("Document 1:\na\n\nDocument 2:\nb", max_chars=10)

        assert len(chunks) == 1


class TestMemoryArenaDataset:
    def test_benchmark_id(self):
        from benchmarks.academic.datasets.memoryarena import MemoryArenaDataset

        dataset = MemoryArenaDataset()
        assert dataset.benchmark_id == "memoryarena"

    def test_task_families(self):
        from benchmarks.academic.datasets.memoryarena import TASK_FAMILIES

        assert "web_navigation" in TASK_FAMILIES
        assert "preference_planning" in TASK_FAMILIES
        assert "progressive_search" in TASK_FAMILIES
        assert "sequential_reasoning" in TASK_FAMILIES

    def test_parse_public_rows_creates_per_subtask_instances(self):
        from benchmarks.academic.datasets.memoryarena import MemoryArenaDataset

        dataset = MemoryArenaDataset()
        dataset._parse_public_rows(
            [
                {
                    "_config": "progressive_search",
                    "id": 7,
                    "backgrounds": ["Use source A", "Use source B"],
                    "questions": ["Find first clue", "Use first clue to answer"],
                    "answers": ["clue-one", "final-answer"],
                }
            ]
        )

        assert len(dataset.get_instances()) == 2
        assert dataset.get_queries()[0].category == "progressive_search"
        second_sessions, second_queries, second_gt = dataset.get_instances()[1]
        assert second_queries[0].query_id.endswith("_q001")
        assert second_gt[second_queries[0].query_id].answer == "final-answer"
        prior_text = "\n".join(turn.content for session in second_sessions for turn in session)
        assert "clue-one" in prior_text


class TestLLMJudgePrompts:
    def test_generic_prompt_has_placeholders(self):
        assert "{question}" in _GENERIC_JUDGE_PROMPT
        assert "{answer}" in _GENERIC_JUDGE_PROMPT
        assert "{prediction}" in _GENERIC_JUDGE_PROMPT

    def test_longmemeval_prompts_cover_all_types(self):
        expected = {
            "single-session-user",
            "single-session-assistant",
            "multi-session",
            "temporal-reasoning",
            "knowledge-update",
            "single-session-preference",
            "abstention",
        }
        assert set(_LONGMEMEVAL_JUDGE_PROMPTS.keys()) == expected

    def test_longmemeval_temporal_has_off_by_one(self):
        prompt = _LONGMEMEVAL_JUDGE_PROMPTS["temporal-reasoning"]
        assert "off-by-one" in prompt

    def test_longmemeval_preference_has_rubric(self):
        prompt = _LONGMEMEVAL_JUDGE_PROMPTS["single-session-preference"]
        assert "Rubric" in prompt

    def test_generic_prompt_formats(self):
        result = _GENERIC_JUDGE_PROMPT.format(
            question="What color?", answer="blue", prediction="It is blue"
        )
        assert "What color?" in result
        assert "blue" in result
        assert "It is blue" in result


class TestCLIList:
    @pytest.mark.asyncio
    async def test_list(self, capsys):
        from benchmarks.academic.__main__ import cmd_list

        class FakeArgs:
            pass

        await cmd_list(FakeArgs())
        captured = capsys.readouterr()
        assert "locomo" in captured.out
        assert "memoryarena" in captured.out
        assert "alive" in captured.out
