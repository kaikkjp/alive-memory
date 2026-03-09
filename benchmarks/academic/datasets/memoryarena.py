"""MemoryArena dataset adapter.

MemoryArena evaluates interdependent multi-session agentic memory across
four task families:
- Web navigation
- Preference-constrained planning
- Progressive information search
- Sequential formal reasoning

Paper: states release at project site.

Note: This is a Phase 2 adapter. The dataset format will be finalized
once the MemoryArena dataset is publicly released.
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


TASK_FAMILIES = [
    "web_navigation",
    "preference_planning",
    "progressive_search",
    "sequential_reasoning",
]


class MemoryArenaDataset(DatasetAdapter):
    """Adapter for the MemoryArena benchmark dataset.

    MemoryArena is reserved for Phase 2 because it exposes weaknesses not
    visible on long-context memory benchmarks alone.
    """

    def __init__(self) -> None:
        self._sessions: list[list[ConversationTurn]] = []
        self._queries: list[MemoryQuery] = []
        self._ground_truth: dict[str, GroundTruth] = {}
        self._loaded = False

    @property
    def benchmark_id(self) -> str:
        return "memoryarena"

    async def load(self, data_dir: str, split: str = "test") -> None:
        """Load MemoryArena dataset.

        Expected structure:
            data_dir/memoryarena/
                tasks.json    — multi-session agentic tasks
                queries.json  — evaluation queries by task family
        """
        base = Path(data_dir) / "memoryarena"
        if not base.exists():
            raise FileNotFoundError(
                f"MemoryArena data not found at {base}. "
                f"This is a Phase 2 benchmark — dataset may not be released yet.\n"
                f"Expected files:\n"
                f"  {base}/tasks.json\n"
                f"  {base}/queries.json"
            )

        # Load tasks as sessions
        tasks_file = base / "tasks.json"
        if tasks_file.exists():
            raw_tasks = json.loads(tasks_file.read_text())
            self._sessions = self._parse_tasks(raw_tasks)

        # Load queries
        q_file = base / "queries.json"
        if q_file.exists():
            raw_questions = json.loads(q_file.read_text())
            self._queries, self._ground_truth = self._parse_queries(raw_questions)

        self._loaded = True
        print(f"  [memoryarena] Loaded {len(self._sessions)} task sessions, "
              f"{len(self._queries)} queries")

    def _parse_tasks(
        self, raw: list[dict],
    ) -> list[list[ConversationTurn]]:
        """Parse agentic task sessions."""
        sessions: list[list[ConversationTurn]] = []

        for task_idx, task in enumerate(raw):
            turns: list[ConversationTurn] = []
            session_id = task.get("task_id", f"arena_{task_idx}")

            steps = task.get("steps", task.get("interactions", []))
            for step_idx, step in enumerate(steps):
                if isinstance(step, dict):
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

    def _parse_queries(
        self, raw: list[dict],
    ) -> tuple[list[MemoryQuery], dict[str, GroundTruth]]:
        """Parse evaluation queries by task family."""
        queries: list[MemoryQuery] = []
        gt: dict[str, GroundTruth] = {}

        for q_idx, item in enumerate(raw):
            query_id = item.get("query_id", item.get("id", f"arena_q_{q_idx:04d}"))
            category = item.get("task_family", item.get("category", "web_navigation"))
            question = item.get("question", item.get("query", ""))
            answer = item.get("answer", item.get("expected_answer", ""))

            queries.append(MemoryQuery(
                query_id=str(query_id),
                question=question,
                category=category,
                session_id=item.get("task_id", ""),
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
    ) -> list[EvalResult]:
        """Evaluate using task completion and accuracy."""
        results: list[EvalResult] = []

        for query_id, gt in ground_truth.items():
            pred = predictions.get(query_id, "")

            f1_scores = token_f1(pred, gt.answer)
            em = exact_match(pred, gt.answer)
            hit = substring_match(pred, [gt.answer])

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
