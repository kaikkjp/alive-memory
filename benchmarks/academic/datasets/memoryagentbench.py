"""MemoryAgentBench dataset adapter.

MemoryAgentBench evaluates memory in incremental multi-turn agent settings:
- Accurate Retrieval (AR): finding relevant past information
- Test-Time Learning (TTL): adapting from accumulated context
- Long-Range Understanding (LRU): connecting distant events
- Conflict Resolution (CR): resolving contradictory information

Paper: https://arxiv.org/abs/2501.14200
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
from benchmarks.academic.harness.scoring import exact_match, substring_match, token_f1

CATEGORIES = [
    "accurate_retrieval",
    "test_time_learning",
    "long_range_understanding",
    "conflict_resolution",
]

# Map legacy category names to standardized names
_CATEGORY_ALIASES = {
    "retrieval": "accurate_retrieval",
    "ar": "accurate_retrieval",
    "ttl": "test_time_learning",
    "lru": "long_range_understanding",
    "selective_forgetting": "conflict_resolution",
    "cr": "conflict_resolution",
}


class MemoryAgentBenchDataset(DatasetAdapter):
    """Adapter for the MemoryAgentBench benchmark dataset."""

    def __init__(self) -> None:
        self._sessions: list[list[ConversationTurn]] = []
        self._queries: list[MemoryQuery] = []
        self._ground_truth: dict[str, GroundTruth] = {}
        self._loaded = False

    @property
    def benchmark_id(self) -> str:
        return "memoryagentbench"

    async def load(self, data_dir: str, split: str = "test") -> None:
        """Load MemoryAgentBench dataset.

        Expected structure:
            data_dir/memoryagentbench/
                episodes.json   — multi-turn agent episodes
                questions.json  — evaluation queries by category
        """
        base = Path(data_dir) / "memoryagentbench"
        if not base.exists():
            raise FileNotFoundError(
                f"MemoryAgentBench data not found at {base}. "
                f"See: https://arxiv.org/abs/2501.14200\n"
                f"Expected files:\n"
                f"  {base}/episodes.json\n"
                f"  {base}/questions.json"
            )

        # Load episodes as sessions
        episodes_file = base / "episodes.json"
        if episodes_file.exists():
            raw_episodes = json.loads(episodes_file.read_text())
            self._sessions = self._parse_episodes(raw_episodes)

        # Load questions
        q_file = base / "questions.json"
        if q_file.exists():
            raw_questions = json.loads(q_file.read_text())
            self._queries, self._ground_truth = self._parse_questions(raw_questions)

        self._loaded = True
        print(f"  [memoryagentbench] Loaded {len(self._sessions)} episodes, "
              f"{len(self._queries)} questions")

    def _parse_episodes(
        self, raw: list[dict],
    ) -> list[list[ConversationTurn]]:
        """Parse agent episodes into conversation turn format."""
        sessions: list[list[ConversationTurn]] = []

        for ep_idx, episode in enumerate(raw):
            turns: list[ConversationTurn] = []
            session_id = episode.get("episode_id", f"ep_{ep_idx}")

            steps = episode.get("steps", episode.get("turns", episode.get("interactions", [])))
            for step_idx, step in enumerate(steps):
                if isinstance(step, dict):
                    # Agent episodes may have: observation, action, feedback
                    role = step.get("role", step.get("type", "user"))
                    content = step.get("content", step.get("text", ""))
                    if not content and "observation" in step:
                        content = step["observation"]
                        role = "system"
                    if not content and "action" in step:
                        content = step["action"]
                        role = "assistant"
                elif isinstance(step, str):
                    role = "user" if step_idx % 2 == 0 else "assistant"
                    content = step
                else:
                    continue

                turns.append(ConversationTurn(
                    role=role,
                    content=content,
                    turn_id=step_idx,
                    session_id=session_id,
                    metadata=step if isinstance(step, dict) else {},
                ))

            if turns:
                sessions.append(turns)

        return sessions

    def _parse_questions(
        self, raw: list[dict],
    ) -> tuple[list[MemoryQuery], dict[str, GroundTruth]]:
        """Parse evaluation queries."""
        queries: list[MemoryQuery] = []
        gt: dict[str, GroundTruth] = {}

        for q_idx, item in enumerate(raw):
            query_id = item.get("question_id", item.get("id", f"mab_q_{q_idx:04d}"))
            raw_category = item.get("category", item.get("type", "accurate_retrieval"))
            category = _CATEGORY_ALIASES.get(raw_category, raw_category)
            question = item.get("question", item.get("query", ""))
            answer = item.get("answer", item.get("expected_answer", ""))

            queries.append(MemoryQuery(
                query_id=str(query_id),
                question=question,
                category=category,
                session_id=item.get("episode_id", ""),
                metadata={"raw": item},
            ))

            gt[str(query_id)] = GroundTruth(
                query_id=str(query_id),
                answer=str(answer),
                category=category,
                evidence=item.get("evidence", []),
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
        judge_config: dict | None = None,
    ) -> list[EvalResult]:
        """Evaluate using task completion rate and accuracy."""
        results: list[EvalResult] = []

        for query_id, gt in ground_truth.items():
            pred = predictions.get(query_id, "")

            f1_scores = token_f1(pred, gt.answer)
            em = exact_match(pred, gt.answer)
            hit = substring_match(pred, [gt.answer])

            # Task completion: generous — any meaningful match counts
            task_complete = max(em, hit, 1.0 if f1_scores["f1"] > 0.5 else 0.0)

            scores = {
                "f1": f1_scores["f1"],
                "exact_match": em,
                "substring_hit": hit,
                "task_completion": task_complete,
                "accuracy": task_complete,
            }

            results.append(EvalResult(
                query_id=query_id,
                category=gt.category,
                predicted=pred,
                expected=gt.answer,
                scores=scores,
            ))

        return results
