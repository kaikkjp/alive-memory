"""Tests for the evolve system — source-level memory optimization."""

from __future__ import annotations

import pytest

from tools.evolve.agent import (
    validate_changes,
)
from tools.evolve.analyzer import (
    cluster_failures,
    generate_failure_report,
)
from tools.evolve.engine import should_promote
from tools.evolve.scorer import (
    aggregate_split,
    cosine_similarity,
    exact_match,
    extract_keywords,
    keyword_match,
    match_fact,
    score_query,
)
from tools.evolve.suite.loader import load_seed_suite
from tools.evolve.suite.validator import (
    fact_traceable_to_conversation,
    validate_case,
)
from tools.evolve.types import (
    CaseResult,
    ConversationTurn,
    EvalCase,
    EvalQuery,
    EvolveScore,
    FailureCategory,
    RecallScore,
    SplitResult,
)

# ── Helpers ───────────────────────────────────────────────────────


def _make_case_result(
    case_id: str = "test-1",
    category: str = "short_term_recall",
    difficulty: int = 3,
    precision: float = 0.0,
    completeness: float = 0.0,
    noise_rejection: float = 0.0,
    ranking_quality: float = 0.0,
    latency_ms: float = 0.0,
) -> CaseResult:
    """Build a CaseResult with a specific RecallScore."""
    return CaseResult(
        case_id=case_id,
        category=category,
        difficulty=difficulty,
        score=RecallScore(
            precision=precision,
            completeness=completeness,
            noise_rejection=noise_rejection,
            ranking_quality=ranking_quality,
            latency_ms=latency_ms,
        ),
    )


def _make_evolve_score(
    train_score: float = 0.5,
    held_out_score: float = 0.5,
    production_score: float = 0.5,
) -> EvolveScore:
    """Build an EvolveScore with explicit aggregate scores per split."""
    train = SplitResult(name="train")
    train.aggregate_score = train_score
    held_out = SplitResult(name="held_out")
    held_out.aggregate_score = held_out_score
    production = SplitResult(name="production")
    production.aggregate_score = production_score
    return EvolveScore(train=train, held_out=held_out, production=production)


def _make_conversation(texts: list[str]) -> list[ConversationTurn]:
    """Build a simple conversation from alternating user/assistant texts."""
    turns = []
    for i, text in enumerate(texts):
        turns.append(
            ConversationTurn(
                turn=i + 1,
                time=f"2026-03-01T10:{i:02d}:00Z",
                role="user" if i % 2 == 0 else "assistant",
                content=text,
            )
        )
    return turns


def _make_valid_case(**overrides) -> EvalCase:
    """Build a minimal valid EvalCase, applying any overrides."""
    conversation = _make_conversation([
        "I just started a company called Petal, it's a flower delivery startup.",
        "That sounds great! Tell me more about Petal.",
    ])
    defaults = dict(
        id="valid-001",
        category="short_term_recall",
        difficulty=3,
        conversation=conversation,
        queries=[
            EvalQuery(
                time="2026-03-01T10:05:00Z",
                query="What startup did I mention?",
                ground_truth=["startup called Petal"],
            )
        ],
    )
    defaults.update(overrides)
    return EvalCase(**defaults)


# ═══════════════════════════════════════════════════════════════════
# Types tests
# ═══════════════════════════════════════════════════════════════════


class TestRecallScore:
    def test_recall_score_composite(self):
        s = RecallScore(
            precision=0.8,
            completeness=0.6,
            noise_rejection=0.9,
            ranking_quality=0.7,
            latency_ms=100.0,
        )
        # quality = 0.35*0.6 + 0.25*0.8 + 0.20*0.9 + 0.15*0.7
        #         = 0.21 + 0.20 + 0.18 + 0.105 = 0.695
        # latency_factor = max(100-200,0)/800 = 0 → penalty = 0
        # composite = 1.0 - 0.695 + 0.0 = 0.305
        assert s.composite == pytest.approx(0.305, abs=1e-6)

    def test_recall_score_composite_perfect(self):
        s = RecallScore(
            precision=1.0,
            completeness=1.0,
            noise_rejection=1.0,
            ranking_quality=1.0,
            latency_ms=50.0,
        )
        # quality = 0.35 + 0.25 + 0.20 + 0.15 = 0.95
        # latency_factor = 0 (50 < 200) → penalty = 0
        # composite = 1.0 - 0.95 = 0.05
        assert s.composite == pytest.approx(0.05, abs=1e-6)

    def test_recall_score_composite_worst(self):
        s = RecallScore(
            precision=0.0,
            completeness=0.0,
            noise_rejection=0.0,
            ranking_quality=0.0,
            latency_ms=0.0,
        )
        # quality = 0, penalty = 0 → composite = 1.0
        assert s.composite == pytest.approx(1.0, abs=1e-6)


class TestSplitResult:
    def test_split_result_aggregate_empty(self):
        sr = SplitResult(name="empty")
        assert sr.aggregate_score == 1.0


class TestEvolveScore:
    def test_evolve_score_composite(self):
        score = _make_evolve_score(
            train_score=0.3, held_out_score=0.4, production_score=0.5
        )
        # 0.4*0.3 + 0.4*0.4 + 0.2*0.5 = 0.12 + 0.16 + 0.10 = 0.38
        assert score.composite == pytest.approx(0.38, abs=1e-6)

    def test_evolve_score_overfitting_signal(self):
        score = _make_evolve_score(train_score=0.2, held_out_score=0.5)
        # overfitting_signal = train - held_out = 0.2 - 0.5 = -0.3
        assert score.overfitting_signal == pytest.approx(-0.3, abs=1e-6)


class TestFailureCategory:
    def test_failure_category_values(self):
        categories = {c.value for c in FailureCategory}
        expected = {
            "short_term_recall",
            "cross_session_recall",
            "consolidation_survival",
            "noise_decay",
            "contradiction_handling",
            "high_volume_stress",
            "emotional_weighting",
            "relational_recall",
        }
        assert categories == expected
        assert len(FailureCategory) == 8


# ═══════════════════════════════════════════════════════════════════
# Scorer tests
# ═══════════════════════════════════════════════════════════════════


class TestExactMatch:
    def test_exact_match_basic(self):
        assert exact_match(
            "I recall a startup called Petal that delivers flowers",
            "startup called Petal",
        )

    def test_exact_match_case_insensitive(self):
        assert exact_match("STARTUP CALLED PETAL", "startup called petal")

    def test_exact_match_miss(self):
        assert not exact_match("I went to the park yesterday", "startup called Petal")


class TestKeywordMatch:
    def test_keyword_match_full_overlap(self):
        score = keyword_match(
            "I love Rust programming and systems design",
            "Rust programming systems",
        )
        assert score == pytest.approx(1.0)

    def test_keyword_match_partial(self):
        score = keyword_match(
            "I love Rust programming",
            "Rust programming systems design",
        )
        # gt_kw = {"rust", "programming", "systems", "design"} (4 keywords)
        # recalled has "rust", "programming" → 2/4 = 0.5
        assert score == pytest.approx(0.5, abs=0.01)

    def test_keyword_match_no_overlap(self):
        score = keyword_match("I went to the park", "quantum computing research")
        assert score == pytest.approx(0.0)


class TestExtractKeywords:
    def test_extract_keywords(self):
        kw = extract_keywords("The quick brown fox jumps over the lazy dog")
        # Should remove stopwords ("the", "over") and short tokens
        assert "quick" in kw
        assert "brown" in kw
        assert "fox" in kw
        assert "jumps" in kw
        assert "lazy" in kw
        assert "dog" in kw
        assert "the" not in kw
        # "over" has 4 chars and may not be in stopwords; check "the" is removed
        assert "a" not in kw  # short token removed


class TestCosineSimilarity:
    def test_cosine_similarity_identical(self):
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_cosine_similarity_orthogonal(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)


class TestMatchFact:
    @pytest.mark.asyncio
    async def test_match_fact_exact(self):
        score = await match_fact(
            "She mentioned a startup called Petal", "startup called Petal"
        )
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_match_fact_keyword(self):
        # No exact substring match, but keyword overlap >= 0.7
        score = await match_fact(
            "Petal is a flower delivery startup business",
            "Petal flower delivery startup",
        )
        assert score == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_match_fact_no_match(self):
        score = await match_fact(
            "The weather is sunny today",
            "quantum computing research paper",
        )
        assert score == pytest.approx(0.0)


class TestScoreQuery:
    @pytest.mark.asyncio
    async def test_score_query_perfect_recall(self):
        query = EvalQuery(
            time="2026-03-01T10:00:00Z",
            query="What startup?",
            ground_truth=["startup called Petal", "flower delivery"],
        )
        # Recalled items contain exact matches for both ground truth facts
        recalled = [
            "She told me about a startup called Petal",
            "It's a flower delivery company",
        ]
        score = await score_query(recalled, query)
        assert score.completeness >= 0.9
        assert score.precision >= 0.9

    @pytest.mark.asyncio
    async def test_score_query_empty_recall(self):
        query = EvalQuery(
            time="2026-03-01T10:00:00Z",
            query="What startup?",
            ground_truth=["startup called Petal"],
        )
        score = await score_query([], query)
        assert score.completeness == 0.0
        assert score.precision == 0.0
        assert score.noise_rejection == 1.0
        assert score.ranking_quality == 0.0

    @pytest.mark.asyncio
    async def test_score_query_noise_rejection(self):
        query = EvalQuery(
            time="2026-03-01T10:00:00Z",
            query="What startup?",
            ground_truth=["startup called Petal"],
            should_not_recall=["old address", "deleted info"],
        )
        # Recalled items do NOT contain forbidden items
        recalled = ["She mentioned a startup called Petal"]
        score = await score_query(recalled, query)
        assert score.noise_rejection == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_score_query_noise_found(self):
        query = EvalQuery(
            time="2026-03-01T10:00:00Z",
            query="What startup?",
            ground_truth=["startup called Petal"],
            should_not_recall=["old address"],
        )
        # Recalled items DO contain a forbidden item
        recalled = [
            "She mentioned a startup called Petal",
            "Her old address was 123 Main St",
        ]
        score = await score_query(recalled, query)
        assert score.noise_rejection < 1.0


class TestAggregateSplit:
    def test_aggregate_split_empty(self):
        assert aggregate_split([]) == 1.0


# ═══════════════════════════════════════════════════════════════════
# Validator tests
# ═══════════════════════════════════════════════════════════════════


class TestValidateCase:
    def test_validate_case_valid(self):
        case = _make_valid_case()
        errors = validate_case(case)
        assert errors == []

    def test_validate_case_missing_id(self):
        case = _make_valid_case(id="")
        errors = validate_case(case)
        assert any("id" in e.lower() for e in errors)

    def test_validate_case_invalid_category(self):
        case = _make_valid_case(category="totally_made_up")
        errors = validate_case(case)
        assert any("category" in e.lower() for e in errors)

    def test_validate_case_short_conversation(self):
        case = _make_valid_case(
            conversation=[
                ConversationTurn(
                    turn=1,
                    time="2026-03-01T10:00:00Z",
                    role="user",
                    content="Hello",
                )
            ]
        )
        errors = validate_case(case)
        assert any("turn" in e.lower() or "conversation" in e.lower() for e in errors)

    def test_validate_case_no_queries(self):
        case = _make_valid_case(queries=[])
        errors = validate_case(case)
        assert any("quer" in e.lower() for e in errors)

    def test_validate_case_difficulty_out_of_range(self):
        case = _make_valid_case(difficulty=15)
        errors = validate_case(case)
        assert any("difficulty" in e.lower() for e in errors)

    def test_validate_case_compound_ground_truth(self):
        case = _make_valid_case(
            queries=[
                EvalQuery(
                    time="2026-03-01T10:05:00Z",
                    query="Tell me everything",
                    ground_truth=[
                        "startup called Petal, flower delivery, founded 2025, based in Tokyo"
                    ],
                )
            ],
        )
        errors = validate_case(case)
        assert any("comma" in e.lower() for e in errors)


class TestFactTraceable:
    def test_fact_traceable(self):
        conversation = _make_conversation([
            "I started a company called Petal for flower delivery.",
            "That's interesting, tell me more.",
        ])
        assert fact_traceable_to_conversation("company called Petal", conversation)

    def test_fact_not_traceable(self):
        conversation = _make_conversation([
            "I went to the park today.",
            "Sounds relaxing!",
        ])
        assert not fact_traceable_to_conversation(
            "quantum computing research laboratory", conversation
        )


# ═══════════════════════════════════════════════════════════════════
# Suite loader tests
# ═══════════════════════════════════════════════════════════════════


class TestSuiteLoader:
    def test_load_seed_suite(self):
        suite = load_seed_suite()
        assert len(suite.train) == 10
        assert len(suite.held_out) == 5
        assert len(suite.production) == 0
        assert suite.version != "unknown"

    def test_parse_case(self):
        suite = load_seed_suite()
        case = suite.train[0]
        assert isinstance(case.id, str) and case.id
        assert isinstance(case.category, str) and case.category
        assert isinstance(case.difficulty, int)
        assert isinstance(case.conversation, list)
        assert len(case.conversation) >= 2
        assert isinstance(case.conversation[0], ConversationTurn)
        assert isinstance(case.queries, list)
        assert len(case.queries) >= 1
        assert isinstance(case.queries[0], EvalQuery)
        assert isinstance(case.queries[0].ground_truth, list)


# ═══════════════════════════════════════════════════════════════════
# Analyzer tests
# ═══════════════════════════════════════════════════════════════════


class TestAnalyzer:
    def test_generate_failure_report_all_pass(self):
        sr = SplitResult(name="train")
        sr.case_results = [
            _make_case_result(
                case_id="pass-1",
                precision=1.0,
                completeness=1.0,
                noise_rejection=1.0,
                ranking_quality=1.0,
            ),
        ]
        sr.pass_count = 1
        sr.fail_count = 0
        report = generate_failure_report(sr)
        assert "All cases passed" in report

    def test_generate_failure_report_with_failures(self):
        sr = SplitResult(name="train")
        sr.case_results = [
            _make_case_result(
                case_id="fail-1",
                category="noise_decay",
                difficulty=5,
                precision=0.1,
                completeness=0.1,
                noise_rejection=0.1,
                ranking_quality=0.1,
            ),
            _make_case_result(
                case_id="fail-2",
                category="noise_decay",
                difficulty=7,
                precision=0.2,
                completeness=0.2,
                noise_rejection=0.2,
                ranking_quality=0.2,
            ),
        ]
        sr.fail_count = 2
        sr.pass_count = 0
        report = generate_failure_report(sr)
        assert "noise_decay" in report
        assert "fail-" in report

    def test_cluster_failures(self):
        results = [
            _make_case_result(case_id="f1", category="noise_decay", difficulty=3),
            _make_case_result(case_id="f2", category="noise_decay", difficulty=5),
            _make_case_result(
                case_id="f3", category="short_term_recall", difficulty=2
            ),
        ]
        clusters = cluster_failures(results, threshold=0.5)
        # All have composite ~1.0 (all zeros), so all fail threshold 0.5
        cats = {c.category for c in clusters}
        assert "noise_decay" in cats
        assert "short_term_recall" in cats
        # noise_decay cluster should have count 2
        nd_cluster = next(c for c in clusters if c.category == "noise_decay")
        assert nd_cluster.count == 2


# ═══════════════════════════════════════════════════════════════════
# Agent tests (validation, no LLM needed)
# ═══════════════════════════════════════════════════════════════════


class TestAgentValidation:
    def test_validate_changes_valid(self):
        changes = {"alive_memory/recall/hippocampus.py": "x = 1\n"}
        errors = validate_changes(
            changes, allowed_files=["alive_memory/recall/hippocampus.py"]
        )
        assert errors == []

    def test_validate_changes_syntax_error(self):
        changes = {"alive_memory/recall/hippocampus.py": "def foo(\n"}
        errors = validate_changes(
            changes, allowed_files=["alive_memory/recall/hippocampus.py"]
        )
        assert any("syntax" in e.lower() for e in errors)

    def test_validate_changes_forbidden_import(self):
        code = "import tools.evolve.scorer\nx = 1\n"
        changes = {"alive_memory/recall/hippocampus.py": code}
        errors = validate_changes(
            changes, allowed_files=["alive_memory/recall/hippocampus.py"]
        )
        assert any("forbidden" in e.lower() for e in errors)

    def test_validate_changes_unauthorized_file(self):
        changes = {"some/random/file.py": "x = 1\n"}
        errors = validate_changes(
            changes, allowed_files=["alive_memory/recall/hippocampus.py"]
        )
        assert any("unauthorized" in e.lower() for e in errors)


# ═══════════════════════════════════════════════════════════════════
# Engine tests (should_promote)
# ═══════════════════════════════════════════════════════════════════


class TestShouldPromote:
    def test_should_promote_improvement(self):
        incumbent = _make_evolve_score(
            train_score=0.5, held_out_score=0.5, production_score=0.5
        )
        candidate = _make_evolve_score(
            train_score=0.3, held_out_score=0.3, production_score=0.3
        )
        assert should_promote(candidate, incumbent) is True

    def test_should_promote_no_improvement(self):
        incumbent = _make_evolve_score(
            train_score=0.3, held_out_score=0.3, production_score=0.3
        )
        candidate = _make_evolve_score(
            train_score=0.5, held_out_score=0.5, production_score=0.5
        )
        assert should_promote(candidate, incumbent) is False

    def test_should_promote_held_out_regression(self):
        incumbent = _make_evolve_score(
            train_score=0.5, held_out_score=0.3, production_score=0.5
        )
        # Candidate improves composite overall but held_out regresses beyond tolerance
        candidate = _make_evolve_score(
            train_score=0.1, held_out_score=0.5, production_score=0.1
        )
        assert should_promote(candidate, incumbent) is False

    def test_should_promote_overfitting(self):
        incumbent = _make_evolve_score(
            train_score=0.5, held_out_score=0.5, production_score=0.5
        )
        # Candidate: train much better than held_out → overfitting
        # overfitting_signal = train - held_out = 0.1 - 0.45 = -0.35 ... no
        # We need train - held_out > 0.15 but remember lower is better
        # overfitting_signal = train.aggregate - held_out.aggregate
        # For overfitting: train is much LOWER (better) than held_out
        # But the formula is train - held_out, so we need that > 0.15
        # That means train aggregate > held_out aggregate
        # So train=0.5, held_out=0.2 → signal=0.3 > 0.15
        candidate = _make_evolve_score(
            train_score=0.45, held_out_score=0.2, production_score=0.2
        )
        # composite = 0.4*0.45 + 0.4*0.2 + 0.2*0.2 = 0.18+0.08+0.04 = 0.30
        # incumbent composite = 0.5 → candidate is better
        # held_out: 0.2 <= 0.5 + 0.01 → OK
        # production: 0.2 <= 0.5 + 0.01 → OK
        # overfitting: 0.45 - 0.2 = 0.25 > 0.15 → FAIL
        assert should_promote(candidate, incumbent) is False
