"""MemoryArena dataset adapter.

MemoryArena evaluates interdependent multi-session agentic memory across
four task families:
- Web navigation
- Preference-constrained planning
- Progressive information search
- Sequential formal reasoning

Paper/data: https://memoryarena.github.io/ and Hugging Face dataset
`ZexueHe/memoryarena`.

Note: This is a Phase 2 adapter. The public Hugging Face data is organized as
task-family JSONL files, while this simplified academic harness currently
expects normalized tasks/queries JSON files.
"""

from __future__ import annotations

import json
import os
import urllib.request
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

_HF_DATASET = "https://huggingface.co/datasets/ZexueHe/memoryarena/resolve/main"
_HF_CONFIGS = {
    "bundled_shopping": "preference_planning",
    "group_travel_planner": "preference_planning",
    "progressive_search": "progressive_search",
    "formal_reasoning_math": "sequential_reasoning",
    "formal_reasoning_phys": "sequential_reasoning",
}


class MemoryArenaDataset(DatasetAdapter):
    """Adapter for the MemoryArena benchmark dataset.

    MemoryArena is reserved for Phase 2 because it exposes weaknesses not
    visible on long-context memory benchmarks alone.
    """

    def __init__(self) -> None:
        self._sessions: list[list[ConversationTurn]] = []
        self._queries: list[MemoryQuery] = []
        self._ground_truth: dict[str, GroundTruth] = {}
        self._instances: list[
            tuple[list[list[ConversationTurn]], list[MemoryQuery], dict[str, GroundTruth]]
        ] = []
        self._loaded = False

    @property
    def benchmark_id(self) -> str:
        return "memoryarena"

    async def load(self, data_dir: str, split: str = "test") -> None:
        """Load MemoryArena dataset.

        Supported structures:
            data_dir/memoryarena/
                tasks.json    — multi-session agentic tasks
                queries.json  — evaluation queries by task family

        Or the public Hugging Face layout:
            data_dir/memoryarena/<config>/data.jsonl

        If no local data is present, this loader downloads the public JSONL
        files from Hugging Face and caches them locally.
        """
        base = Path(data_dir) / "memoryarena"
        base.mkdir(parents=True, exist_ok=True)

        tasks_file = base / "tasks.json"
        queries_file = base / "queries.json"
        if tasks_file.exists() and queries_file.exists():
            raw_tasks = json.loads(tasks_file.read_text())
            self._sessions = self._parse_tasks(raw_tasks)
            raw_questions = json.loads(queries_file.read_text())
            self._queries, self._ground_truth = self._parse_queries(raw_questions)
            self._instances = [(self._sessions, self._queries, self._ground_truth)]
        else:
            rows = self._load_public_jsonl(base)
            self._parse_public_rows(rows)

        self._loaded = True
        print(
            f"  [memoryarena] Loaded {len(self._sessions)} task sessions, "
            f"{len(self._queries)} queries"
        )

    def _load_public_jsonl(self, base: Path) -> list[dict]:
        """Load public MemoryArena JSONL rows from cache or Hugging Face."""
        rows: list[dict] = []
        max_rows_env = os.environ.get("ALIVE_BENCH_HF_MAX_ROWS")
        max_rows = int(max_rows_env) if max_rows_env else None

        for config_name in _HF_CONFIGS:
            path = base / config_name / "data.jsonl"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                self._download_config(config_name, path)

            count = 0
            with path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    row["_config"] = config_name
                    rows.append(row)
                    count += 1
                    if max_rows is not None and count >= max_rows:
                        break

        return rows

    def _download_config(self, config_name: str, path: Path) -> None:
        url = f"{_HF_DATASET}/{config_name}/data.jsonl"
        tmp = path.with_suffix(".jsonl.tmp")
        with urllib.request.urlopen(url, timeout=120) as resp:
            tmp.write_bytes(resp.read())
        tmp.rename(path)

    def _parse_public_rows(self, rows: list[dict]) -> None:
        """Normalize public MemoryArena rows into per-subtask instances."""
        for row_idx, row in enumerate(rows):
            config_name = row.get("_config", "bundled_shopping")
            task_family = _HF_CONFIGS.get(config_name, "preference_planning")
            task_id = f"{config_name}_{row.get('id', row_idx)}"
            questions = row.get("questions") or []
            answers = row.get("answers") or []
            backgrounds = row.get("backgrounds", row.get("background", []))
            # group_travel_planner stores Jennifer's original trip request and
            # existing daily plan under `base_person` instead of `backgrounds`.
            # Without this, subtasks lose the context they need to answer.
            base_person_text = _base_person_to_text(row.get("base_person"))

            for sub_idx, question in enumerate(questions):
                query_id = f"{task_id}_q{sub_idx:03d}"
                background = _background_for_index(backgrounds, sub_idx)
                prior_turns = self._prior_turns(
                    task_id=task_id,
                    questions=questions,
                    answers=answers,
                    upto=sub_idx,
                )

                sessions: list[list[ConversationTurn]] = []
                if base_person_text:
                    sessions.append(
                        [
                            ConversationTurn(
                                role="system",
                                content=base_person_text,
                                turn_id=0,
                                session_id=f"{task_id}_base_person",
                                metadata={
                                    "task_family": task_family,
                                    "config": config_name,
                                    "kind": "base_person",
                                },
                            )
                        ]
                    )
                if background:
                    sessions.append(
                        [
                            ConversationTurn(
                                role="system",
                                content=background,
                                turn_id=0,
                                session_id=f"{task_id}_background_{sub_idx}",
                                metadata={
                                    "task_family": task_family,
                                    "config": config_name,
                                    "kind": "background",
                                },
                            )
                        ]
                    )
                if prior_turns:
                    sessions.append(prior_turns)

                raw_answer = answers[sub_idx] if sub_idx < len(answers) else ""
                answer = _answer_to_text(raw_answer, task_family=task_family)
                aliases = _answer_aliases(raw_answer, task_family=task_family)

                query = MemoryQuery(
                    query_id=query_id,
                    question=str(question),
                    category=task_family,
                    session_id=task_id,
                    metadata={
                        "config": config_name,
                        "task_id": task_id,
                        "subtask_index": sub_idx,
                        "answer_aliases": aliases,
                        "raw_category": row.get("category"),
                    },
                )
                gt = GroundTruth(
                    query_id=query_id,
                    answer=answer,
                    category=task_family,
                    evidence=[background] if background else [],
                    metadata={
                        "answer_aliases": aliases,
                        "config": config_name,
                        "task_id": task_id,
                        "subtask_index": sub_idx,
                        "raw_category": row.get("category"),
                    },
                )

                self._sessions.extend(sessions)
                self._queries.append(query)
                self._ground_truth[query_id] = gt
                self._instances.append((sessions, [query], {query_id: gt}))

    def _prior_turns(
        self,
        task_id: str,
        questions: list,
        answers: list,
        upto: int,
    ) -> list[ConversationTurn]:
        turns: list[ConversationTurn] = []
        for idx in range(upto):
            if idx >= len(questions):
                break
            turns.append(
                ConversationTurn(
                    role="user",
                    content=str(questions[idx]),
                    turn_id=len(turns),
                    session_id=f"{task_id}_prior",
                    metadata={"subtask_index": idx},
                )
            )
            if idx < len(answers):
                turns.append(
                    ConversationTurn(
                        role="assistant",
                        content=_answer_to_text(answers[idx]),
                        turn_id=len(turns),
                        session_id=f"{task_id}_prior",
                        metadata={"subtask_index": idx},
                    )
                )
        return turns

    def _parse_tasks(
        self,
        raw: list[dict],
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

                turns.append(
                    ConversationTurn(
                        role=role,
                        content=content,
                        turn_id=step_idx,
                        session_id=session_id,
                        metadata=step if isinstance(step, dict) else {},
                    )
                )

            if turns:
                sessions.append(turns)

        return sessions

    def _parse_queries(
        self,
        raw: list[dict],
    ) -> tuple[list[MemoryQuery], dict[str, GroundTruth]]:
        """Parse evaluation queries by task family."""
        queries: list[MemoryQuery] = []
        gt: dict[str, GroundTruth] = {}

        for q_idx, item in enumerate(raw):
            query_id = item.get("query_id", item.get("id", f"arena_q_{q_idx:04d}"))
            category = item.get("task_family", item.get("category", "web_navigation"))
            question = item.get("question", item.get("query", ""))
            answer = item.get("answer", item.get("expected_answer", ""))

            queries.append(
                MemoryQuery(
                    query_id=str(query_id),
                    question=question,
                    category=category,
                    session_id=item.get("task_id", ""),
                    metadata={"raw": item},
                )
            )

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

    def get_instances(
        self,
    ) -> list[tuple[list[list[ConversationTurn]], list[MemoryQuery], dict[str, GroundTruth]]]:
        """Return one independent instance per MemoryArena subtask."""
        return self._instances or [(self._sessions, self._queries, self._ground_truth)]

    async def evaluate(
        self,
        predictions: dict[str, str],
        ground_truth: dict[str, GroundTruth],
        judge_config: dict | None = None,
    ) -> list[EvalResult]:
        """Evaluate using task completion and accuracy."""
        results: list[EvalResult] = []

        for query_id, gt in ground_truth.items():
            pred = predictions.get(query_id, "")

            aliases = gt.metadata.get("answer_aliases") or [gt.answer]
            f1_scores = _best_token_f1(pred, aliases)
            em = max(exact_match(pred, ref) for ref in aliases) if aliases else 0.0
            hit = substring_match(pred, aliases)

            task_complete = max(em, hit, 1.0 if f1_scores["f1"] > 0.5 else 0.0)

            scores = {
                "f1": f1_scores["f1"],
                "exact_match": em,
                "substring_hit": hit,
                "task_completion": task_complete,
                "accuracy": task_complete,
            }

            results.append(
                EvalResult(
                    query_id=query_id,
                    category=gt.category,
                    predicted=pred,
                    expected=gt.answer,
                    scores=scores,
                )
            )

        return results


def _background_for_index(backgrounds, index: int) -> str:
    if backgrounds is None:
        return ""
    if isinstance(backgrounds, str):
        return backgrounds
    if isinstance(backgrounds, list):
        if not backgrounds:
            return ""
        if index < len(backgrounds):
            return _answer_to_text(backgrounds[index])
        return _answer_to_text(backgrounds[0])
    return str(backgrounds)


def _answer_to_text(answer, *, task_family: str | None = None) -> str:
    aliases = _answer_aliases(answer, task_family=task_family)
    return aliases[0] if aliases else ""


def _answer_aliases(answer, *, task_family: str | None = None) -> list[str]:
    """Return alternative reference strings for `answer`.

    A list of strings is treated as alternatives. A list of dicts (e.g. a
    multi-day itinerary in group_travel_planner) is a single structured target;
    flattening per-item would let a prediction containing only one day score as
    fully correct, so we serialize the whole list as one canonical string and
    only add per-field aliases that the scorer can substring-match.
    """
    if answer is None:
        return []
    if isinstance(answer, str):
        return [answer]
    if isinstance(answer, dict):
        aliases: list[str] = []
        target = answer.get("target_asin")
        if target:
            aliases.append(str(target))
        # Attributes are properties of the target product, not alternative
        # correct answers. Adding each as its own alias would let a prediction
        # like "gluten free" substring-match the alias and score
        # task-complete without selecting the right product. Combine them into
        # one full descriptor instead so a partial mention does not match.
        attrs = answer.get("attributes")
        if isinstance(attrs, list) and attrs:
            full_attrs = " ".join(str(attr) for attr in attrs)
            if full_attrs:
                aliases.append(full_attrs)
        aliases.append(json.dumps(answer, sort_keys=True))
        return [a for a in aliases if a]
    if isinstance(answer, list):
        if not answer:
            return []
        # Heterogeneous list of dicts → single structured target (e.g. a
        # multi-day itinerary). Treating each element as an alias would let a
        # prediction containing only one day exact/substring-match the whole
        # task as correct, so emit the canonical full sequence as the only
        # reference.
        if any(isinstance(item, dict) for item in answer):
            return [json.dumps(answer, sort_keys=True)]
        # Plain string/scalar list → alternative references.
        aliases = []
        for item in answer:
            aliases.extend(_answer_aliases(item, task_family=task_family))
        return [a for a in aliases if a]
    return [str(answer)]


def _base_person_to_text(base_person) -> str:
    """Flatten base_person into a system-style background string.

    The HF group_travel_planner schema stores the initial traveler request and
    pre-existing per-day plan under `base_person` instead of `backgrounds`,
    leaving the first subtask with no context if we don't surface it.
    """
    if not base_person:
        return ""
    if isinstance(base_person, str):
        return base_person
    if isinstance(base_person, dict):
        parts: list[str] = []
        name = base_person.get("name")
        query = base_person.get("query")
        if name and query:
            parts.append(f"{name}: {query}")
        elif query:
            parts.append(str(query))
        elif name:
            parts.append(f"Traveler: {name}")
        daily = base_person.get("daily_plans")
        if daily:
            parts.append("Existing plan: " + json.dumps(daily, sort_keys=True))
        # Surface any other top-level scalar fields we did not explicitly
        # consume so adapter output stays useful as the schema evolves.
        consumed = {"name", "query", "daily_plans"}
        for key, value in base_person.items():
            if key in consumed:
                continue
            if isinstance(value, (str, int, float)):
                parts.append(f"{key}: {value}")
        return "\n".join(p for p in parts if p)
    return str(base_person)


def _best_token_f1(pred: str, references: list[str]) -> dict[str, float]:
    if not references:
        return token_f1(pred, "")
    scores = [token_f1(pred, ref) for ref in references]
    return max(scores, key=lambda s: s["f1"])
