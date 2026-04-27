from benchmarks.adapters.base import RecallResult
from benchmarks.generate_streams import StreamGenerator
from benchmarks.runner import BenchmarkResult, CycleMetrics
from benchmarks.scoring.autobiographical import (
    aggregate_autobiographical_scores,
    score_autobiographical_query,
)


def test_autobiographical_scores_current_preference_without_stale():
    query = {
        "query_id": "q_pref",
        "query": "What is kai's beverage_preference?",
        "category": "fact_update",
    }
    ground_truth = {
        "expected_memories": ["avoids caffeine"],
        "current_fact": "avoids caffeine",
        "stale_fact": "strong coffee",
        "autobiographical_axes": [
            "taste_currentness",
            "contradiction_handling",
            "temporal_specificity",
            "change_legibility",
        ],
    }
    results = [
        RecallResult(
            content="Kai now avoids caffeine after a health scare.",
            score=1.0,
            metadata={"evidence_ids": ["evt_900"]},
        )
    ]

    score = score_autobiographical_query(query, ground_truth, results)

    assert score is not None
    assert score.axis_scores["taste_currentness"] == 1.0
    assert score.axis_scores["contradiction_handling"] == 1.0
    assert score.axis_scores["temporal_specificity"] == 1.0
    assert score.diagnostics["stale_preference_rate"] == 0.0


def test_autobiographical_penalizes_stale_and_boundary_leakage():
    query = {
        "query_id": "q_boundary",
        "query": "What is kai's beverage_preference?",
        "category": "fact_update",
    }
    ground_truth = {
        "expected_memories": ["avoids caffeine"],
        "current_fact": "avoids caffeine",
        "stale_fact": "strong coffee",
        "autobiographical_axes": ["taste_currentness", "person_boundary"],
    }
    results = [
        RecallResult(
            content="Kai now avoids caffeine, but Mira prefers strong coffee.",
            score=1.0,
        )
    ]

    score = score_autobiographical_query(query, ground_truth, results)

    assert score is not None
    assert score.axis_scores["taste_currentness"] == 0.5
    assert score.axis_scores["person_boundary"] == 0.0
    assert score.diagnostics["stale_preference_rate"] == 1.0
    assert score.diagnostics["boundary_leakage_rate"] == 1.0


def test_autobiographical_aggregate_reports_axes_and_diagnostics():
    scores = [
        {
            "query_id": "q1",
            "axes": ["identity_preservation"],
            "overall": 1.0,
            "axis_scores": {"identity_preservation": 1.0},
            "diagnostics": {"evidence_trace_rate": 1.0},
        },
        {
            "query_id": "q2",
            "axes": ["identity_preservation"],
            "overall": 0.0,
            "axis_scores": {"identity_preservation": 0.0},
            "diagnostics": {"evidence_trace_rate": 0.0},
        },
    ]

    summary = aggregate_autobiographical_scores(scores)

    assert summary["overall"] == 0.5
    assert summary["count"] == 2
    assert summary["axes"]["identity_preservation"] == 0.5
    assert summary["diagnostics"]["evidence_trace_rate"] == 0.5


def test_autobiographical_generator_tags_track_e_axes():
    generator = StreamGenerator(
        scenario="autobiographical_agent",
        total_events=1000,
        seed=42,
    )
    events = generator._generate_events()
    queries, ground_truth = generator._generate_queries_and_gt(events)

    tagged_queries = [q for q in queries if q.get("track") == "autobiographical"]
    tagged_ground_truth = [
        gt for gt in ground_truth if gt.get("autobiographical_axes")
    ]

    assert tagged_queries
    assert len(tagged_queries) == len(tagged_ground_truth)
    assert any(
        "identity_preservation" in q.get("autobiographical_axes", [])
        for q in tagged_queries
    )
    assert any(
        "taste_currentness" in q.get("autobiographical_axes", [])
        for q in tagged_queries
    )


def test_benchmark_result_serializes_autobiographical_audit_fields():
    result = BenchmarkResult(
        system_id="alive",
        stream_name="autobiographical_agent_3k",
        seed=42,
        run_manifest={"event_count": 100, "files": {"stream": {"sha256": "abc"}}},
    )
    result.final_metrics = CycleMetrics(
        cycle=100,
        autobiographical_summary={"overall": 0.5, "count": 1},
        autobiographical_scores=[
            {
                "query_id": "q1",
                "axes": ["identity_preservation"],
                "overall": 0.5,
            }
        ],
        recall_traces=[
            {
                "query_id": "q1",
                "results": [{"rank": 1, "content_snippet": "Maru"}],
            }
        ],
    )

    serialized = result.to_dict()

    assert serialized["run_manifest"]["event_count"] == 100
    final_metrics = serialized["final_metrics"]
    assert final_metrics["autobiographical_summary"]["overall"] == 0.5
    assert final_metrics["autobiographical_scores"][0]["query_id"] == "q1"
    assert final_metrics["recall_traces"][0]["results"][0]["rank"] == 1
