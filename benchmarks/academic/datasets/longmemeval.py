"""LongMemEval dataset adapter.

LongMemEval evaluates long-term chat assistant memory across five abilities:
- Information extraction (single-session-user, single-session-assistant, single-session-preference)
- Multi-session reasoning
- Temporal reasoning
- Knowledge updates
- Abstention (questions ending with _abs)

Dataset: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned
Paper: https://arxiv.org/abs/2410.10813

Uses longmemeval_s_cleaned.json (277MB, ~115k tokens/question, ~40 sessions).
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.academic.harness.base import (
    ConversationTurn,
    DatasetAdapter,
    EvalResult,
    GroundTruth,
    MemoryQuery,
)
from benchmarks.academic.harness.scoring import (
    abstention_score,
    exact_match,
    llm_judge,
    substring_match,
    token_f1,
)

# Map question_type to ability category
_TYPE_TO_ABILITY = {
    "single-session-user": "information_extraction",
    "single-session-assistant": "information_extraction",
    "single-session-preference": "information_extraction",
    "multi-session": "multi_session_reasoning",
    "temporal-reasoning": "temporal_reasoning",
    "knowledge-update": "knowledge_updates",
}

# LongMemEval ability categories
ABILITIES = [
    "information_extraction",
    "multi_session_reasoning",
    "temporal_reasoning",
    "knowledge_updates",
    "abstention",
]


class LongMemEvalDataset(DatasetAdapter):
    """Adapter for the LongMemEval benchmark dataset.

    LongMemEval embeds sessions per-question: each question has its own
    haystack_sessions (the conversation history relevant to it). The
    adapter deduplicates sessions across questions to build a unified
    session list for ingestion.
    """

    def __init__(self) -> None:
        self._sessions: list[list[ConversationTurn]] = []
        self._queries: list[MemoryQuery] = []
        self._ground_truth: dict[str, GroundTruth] = {}
        # Per-question instances for isolated evaluation
        self._instances: list[tuple[list[list[ConversationTurn]], list[MemoryQuery], dict[str, GroundTruth]]] = []
        self._loaded = False

    @property
    def benchmark_id(self) -> str:
        return "longmemeval"

    async def load(self, data_dir: str, split: str = "test") -> None:
        """Load LongMemEval dataset.

        Expected structure:
            data_dir/longmemeval/
                longmemeval_s_cleaned.json  — small variant (~115k tokens)
        """
        base = Path(data_dir) / "longmemeval"
        if not base.exists():
            raise FileNotFoundError(
                f"LongMemEval data not found at {base}. "
                f"Download from: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned\n"
                f"  pip install huggingface_hub\n"
                f"  python -c \"from huggingface_hub import hf_hub_download; "
                f"hf_hub_download('xiaowu0162/longmemeval-cleaned', "
                f"'longmemeval_s_cleaned.json', repo_type='dataset', "
                f"local_dir='{base}')\""
            )

        # Try variants in order of preference
        for fname in ["longmemeval_s_cleaned.json", "longmemeval_oracle.json"]:
            data_file = base / fname
            if data_file.exists():
                break
        else:
            raise FileNotFoundError(
                f"No LongMemEval data file found in {base}. "
                f"Expected longmemeval_s_cleaned.json"
            )

        raw = json.loads(data_file.read_text())

        # Each question has its own haystack — build per-question instances
        seen_session_ids: set[str] = set()

        for item in raw:
            question_id = item["question_id"]
            question_type = item.get("question_type", "")
            is_abstention = question_id.endswith("_abs")

            # Map to ability category
            if is_abstention:
                ability = "abstention"
            else:
                ability = _TYPE_TO_ABILITY.get(question_type, question_type)

            # Parse this question's haystack sessions
            haystack_ids = item.get("haystack_session_ids", [])
            haystack_dates = item.get("haystack_dates", [])
            haystack_sessions = item.get("haystack_sessions", [])

            question_sessions: list[list[ConversationTurn]] = []
            for idx, (sess_id, session_turns) in enumerate(
                zip(haystack_ids, haystack_sessions)
            ):
                date = haystack_dates[idx] if idx < len(haystack_dates) else ""
                turns = self._parse_session(sess_id, session_turns, date)
                if turns:
                    question_sessions.append(turns)
                # Track globally for get_sessions()
                if sess_id not in seen_session_ids:
                    seen_session_ids.add(sess_id)
                    if turns:
                        self._sessions.append(turns)

            # Build query
            answer = item.get("answer", "")
            query = MemoryQuery(
                query_id=question_id,
                question=item["question"],
                category=ability,
                session_id="",
                metadata={
                    "question_type": question_type,
                    "question_date": item.get("question_date", ""),
                    "answer_session_ids": item.get("answer_session_ids", []),
                    "is_abstention": is_abstention,
                },
            )
            self._queries.append(query)

            gt_entry = GroundTruth(
                query_id=question_id,
                answer=str(answer),
                category=ability,
                evidence=item.get("answer_session_ids", []),
                metadata={
                    "is_abstention": is_abstention,
                    "question_type": question_type,
                    "question": item["question"],
                },
            )
            self._ground_truth[question_id] = gt_entry

            # Per-question instance: own haystack + single query
            self._instances.append((
                question_sessions,
                [query],
                {question_id: gt_entry},
            ))

        self._loaded = True

        abs_count = sum(1 for q in self._queries
                        if q.metadata.get("is_abstention"))
        print(f"  [longmemeval] Loaded {len(self._instances)} instances "
              f"({len(self._sessions)} unique sessions), "
              f"{len(self._queries)} questions ({abs_count} abstention), "
              f"from {data_file.name}")

    def _parse_session(
        self, session_id: str, turns: list[dict], date: str,
    ) -> list[ConversationTurn]:
        """Parse a single session's turn list."""
        parsed: list[ConversationTurn] = []
        for turn_idx, turn in enumerate(turns):
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if not content:
                continue
            parsed.append(ConversationTurn(
                role=role,
                content=content,
                turn_id=turn_idx,
                session_id=session_id,
                timestamp=date,
                metadata={
                    "has_answer": turn.get("has_answer", False),
                },
            ))
        return parsed

    def get_sessions(self) -> list[list[ConversationTurn]]:
        return self._sessions

    def get_queries(self) -> list[MemoryQuery]:
        return self._queries

    def get_ground_truth(self) -> dict[str, GroundTruth]:
        return self._ground_truth

    def get_instances(
        self,
    ) -> list[tuple[list[list[ConversationTurn]], list[MemoryQuery], dict[str, GroundTruth]]]:
        """Return per-question instances. Each question has its own haystack."""
        return self._instances

    async def evaluate(
        self,
        predictions: dict[str, str],
        ground_truth: dict[str, GroundTruth],
        judge_config: dict | None = None,
    ) -> list[EvalResult]:
        """Evaluate using accuracy and ability-specific metrics.

        Abstention questions are scored on whether the system correctly
        identifies the question as unanswerable. All other questions use
        token F1 and substring matching.
        If judge_config is provided, also runs LLM-as-Judge scoring.
        """
        results: list[EvalResult] = []

        for query_id, gt in ground_truth.items():
            pred = predictions.get(query_id, "")
            is_abstention = gt.metadata.get("is_abstention", False)
            question_type = gt.metadata.get("question_type", "")

            scores: dict[str, float] = {}

            if is_abstention:
                abst = abstention_score(pred, should_abstain=True)
                scores["abstention_accuracy"] = abst
                scores["accuracy"] = abst
            else:
                f1_scores = token_f1(pred, gt.answer)
                scores["f1"] = f1_scores["f1"]
                scores["exact_match"] = exact_match(pred, gt.answer)
                scores["substring_hit"] = substring_match(pred, [gt.answer])

                scores["accuracy"] = max(
                    scores["exact_match"],
                    scores["substring_hit"],
                    1.0 if scores["f1"] > 0.5 else 0.0,
                )

            # LLM-as-Judge (optional, uses official LongMemEval prompts)
            if judge_config:
                j_type = "abstention" if is_abstention else question_type
                judge_score = await llm_judge(
                    question=gt.metadata.get("question", query_id),
                    prediction=pred,
                    answer=gt.answer,
                    judge_config=judge_config,
                    question_type=j_type,
                    benchmark="longmemeval",
                )
                scores["llm_judge"] = judge_score

            results.append(EvalResult(
                query_id=query_id,
                category=gt.category,
                predicted=pred,
                expected=gt.answer,
                scores=scores,
            ))

        return results
