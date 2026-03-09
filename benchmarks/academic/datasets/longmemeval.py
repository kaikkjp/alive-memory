"""LongMemEval dataset adapter.

LongMemEval evaluates long-term chat assistant memory across five abilities:
- Information extraction
- Multi-session reasoning
- Temporal reasoning
- Knowledge updates
- Abstention (correctly saying "I don't know")

Dataset: https://huggingface.co/datasets/xiaowu0162/LongMemEval
Paper: https://arxiv.org/abs/2407.15460
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
    substring_match,
    token_f1,
)


# LongMemEval ability categories
ABILITIES = [
    "information_extraction",
    "multi_session_reasoning",
    "temporal_reasoning",
    "knowledge_updates",
    "abstention",
]


class LongMemEvalDataset(DatasetAdapter):
    """Adapter for the LongMemEval benchmark dataset."""

    def __init__(self) -> None:
        self._sessions: list[list[ConversationTurn]] = []
        self._queries: list[MemoryQuery] = []
        self._ground_truth: dict[str, GroundTruth] = {}
        self._loaded = False

    @property
    def benchmark_id(self) -> str:
        return "longmemeval"

    async def load(self, data_dir: str, split: str = "test") -> None:
        """Load LongMemEval dataset.

        Expected structure:
            data_dir/longmemeval/
                sessions.json   — multi-session conversation histories
                questions.json  — evaluation questions with abilities
        """
        base = Path(data_dir) / "longmemeval"
        if not base.exists():
            raise FileNotFoundError(
                f"LongMemEval data not found at {base}. "
                f"Download from: https://huggingface.co/datasets/xiaowu0162/LongMemEval\n"
                f"Expected files:\n"
                f"  {base}/sessions.json\n"
                f"  {base}/questions.json"
            )

        # Load sessions
        sessions_file = base / "sessions.json"
        if sessions_file.exists():
            raw_sessions = json.loads(sessions_file.read_text())
            self._sessions = self._parse_sessions(raw_sessions)

        # Load questions
        q_file = base / "questions.json"
        if q_file.exists():
            raw_questions = json.loads(q_file.read_text())
            self._queries, self._ground_truth = self._parse_questions(raw_questions)

        self._loaded = True
        print(f"  [longmemeval] Loaded {len(self._sessions)} sessions, "
              f"{len(self._queries)} questions across {len(ABILITIES)} abilities")

    def _parse_sessions(
        self, raw: list[dict],
    ) -> list[list[ConversationTurn]]:
        """Parse LongMemEval multi-session format."""
        sessions: list[list[ConversationTurn]] = []

        for sess_idx, sess in enumerate(raw):
            turns: list[ConversationTurn] = []
            session_id = sess.get("session_id", f"sess_{sess_idx}")

            messages = sess.get("messages", sess.get("turns", sess.get("conversation", [])))
            for turn_idx, msg in enumerate(messages):
                if isinstance(msg, dict):
                    role = msg.get("role", "user")
                    content = msg.get("content", msg.get("text", ""))
                    timestamp = msg.get("timestamp", msg.get("date", ""))
                elif isinstance(msg, str):
                    role = "user" if turn_idx % 2 == 0 else "assistant"
                    content = msg
                    timestamp = ""
                else:
                    continue

                turns.append(ConversationTurn(
                    role=role,
                    content=content,
                    turn_id=turn_idx,
                    session_id=session_id,
                    timestamp=timestamp,
                ))

            if turns:
                sessions.append(turns)

        return sessions

    def _parse_questions(
        self, raw: list[dict],
    ) -> tuple[list[MemoryQuery], dict[str, GroundTruth]]:
        """Parse LongMemEval questions with ability labels."""
        queries: list[MemoryQuery] = []
        gt: dict[str, GroundTruth] = {}

        for q_idx, item in enumerate(raw):
            query_id = item.get("question_id", item.get("id", f"lme_q_{q_idx:04d}"))
            # Map ability to our category names
            ability = item.get("ability", item.get("category", "information_extraction"))
            question = item.get("question", item.get("query", ""))
            answer = item.get("answer", item.get("expected_answer", ""))
            should_abstain = item.get("should_abstain", ability == "abstention")

            queries.append(MemoryQuery(
                query_id=str(query_id),
                question=question,
                category=ability,
                session_id=item.get("session_id", ""),
                metadata={
                    "should_abstain": should_abstain,
                    "raw": item,
                },
            ))

            gt[str(query_id)] = GroundTruth(
                query_id=str(query_id),
                answer=str(answer),
                category=ability,
                evidence=item.get("evidence", []),
                metadata={"should_abstain": should_abstain},
            )

        return queries, gt

    def get_sessions(self) -> list[list[ConversationTurn]]:
        return self._sessions

    def get_queries(self) -> list[MemoryQuery]:
        return self._queries

    def get_ground_truth(self) -> dict[str, GroundTruth]:
        return self._ground_truth

    async def evaluate(
        self,
        predictions: dict[str, str],
        ground_truth: dict[str, GroundTruth],
    ) -> list[EvalResult]:
        """Evaluate using accuracy and ability-specific metrics."""
        results: list[EvalResult] = []

        for query_id, gt in ground_truth.items():
            pred = predictions.get(query_id, "")
            should_abstain = gt.metadata.get("should_abstain", False)

            scores: dict[str, float] = {}

            if should_abstain:
                # For abstention questions, score whether the system correctly abstained
                scores["abstention_accuracy"] = abstention_score(pred, should_abstain=True)
                scores["accuracy"] = scores["abstention_accuracy"]
            else:
                # For factual questions, score answer quality
                f1_scores = token_f1(pred, gt.answer)
                scores["f1"] = f1_scores["f1"]
                scores["exact_match"] = exact_match(pred, gt.answer)
                scores["substring_hit"] = substring_match(pred, [gt.answer])

                # Accuracy: any hit counts
                scores["accuracy"] = max(
                    scores["exact_match"],
                    scores["substring_hit"],
                    1.0 if scores["f1"] > 0.5 else 0.0,
                )

            results.append(EvalResult(
                query_id=query_id,
                category=gt.category,
                predicted=pred,
                expected=gt.answer,
                scores=scores,
            ))

        return results
