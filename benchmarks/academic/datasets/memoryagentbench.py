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
import os
import re
import urllib.parse
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

CATEGORIES = [
    "accurate_retrieval",
    "test_time_learning",
    "long_range_understanding",
    "conflict_resolution",
]

_HF_DATASET = "ai-hyz/MemoryAgentBench"
_HF_CONFIG = "default"
_HF_SPLITS = {
    "Accurate_Retrieval": "accurate_retrieval",
    "Test_Time_Learning": "test_time_learning",
    "Long_Range_Understanding": "long_range_understanding",
    "Conflict_Resolution": "conflict_resolution",
}

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
        self._instances: list[
            tuple[list[list[ConversationTurn]], list[MemoryQuery], dict[str, GroundTruth]]
        ] = []
        self._loaded = False

    @property
    def benchmark_id(self) -> str:
        return "memoryagentbench"

    async def load(self, data_dir: str, split: str = "test") -> None:
        """Load MemoryAgentBench dataset.

        Supported structures:
            data_dir/memoryagentbench/
                episodes.json   — multi-turn agent episodes
                questions.json  — evaluation queries by category

        Or the public Hugging Face rows cached as:
            data_dir/memoryagentbench/hf_rows/*.jsonl

        If neither local form exists, this loader downloads and caches the
        public rows through the Hugging Face dataset-server JSON API. This
        avoids requiring pyarrow/datasets just to normalize the benchmark.
        """
        base = Path(data_dir) / "memoryagentbench"
        base.mkdir(parents=True, exist_ok=True)

        episodes_file = base / "episodes.json"
        questions_file = base / "questions.json"

        if episodes_file.exists() and questions_file.exists():
            raw_episodes = json.loads(episodes_file.read_text())
            self._sessions = self._parse_episodes(raw_episodes)
            raw_questions = json.loads(questions_file.read_text())
            self._queries, self._ground_truth = self._parse_questions(raw_questions)
            self._instances = [(self._sessions, self._queries, self._ground_truth)]
        else:
            rows = self._load_hf_rows(base)
            self._parse_hf_rows(rows)

        self._loaded = True
        print(
            f"  [memoryagentbench] Loaded {len(self._sessions)} episodes, "
            f"{len(self._queries)} questions"
        )

    def _load_hf_rows(self, base: Path) -> list[dict]:
        """Load public MemoryAgentBench rows from cache or Hugging Face API."""
        cache_dir = base / "hf_rows"
        cache_dir.mkdir(parents=True, exist_ok=True)
        rows: list[dict] = []

        max_rows_env = os.environ.get("ALIVE_BENCH_HF_MAX_ROWS")
        max_rows = int(max_rows_env) if max_rows_env else None

        # Capped runs use a distinct cache file so a smoke-test cap cannot
        # poison the full-run cache (and a full cache cannot silently mask a
        # later cap).
        suffix = f"capped{max_rows}" if max_rows is not None else "full"

        for split_name in _HF_SPLITS:
            cache_file = cache_dir / f"{split_name}.{suffix}.jsonl"
            if not cache_file.exists():
                self._download_split(split_name, cache_file, max_rows=max_rows)

            count = 0
            with cache_file.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    row["_split"] = split_name
                    rows.append(row)
                    count += 1
                    if max_rows is not None and count >= max_rows:
                        break

        return rows

    def _download_split(
        self,
        split_name: str,
        cache_file: Path,
        max_rows: int | None = None,
    ) -> None:
        """Download one split through Hugging Face dataset-server rows API."""
        first = self._fetch_rows(split_name, offset=0, length=1)
        total = int(first.get("num_rows_total", 0))
        if max_rows is not None:
            total = min(total, max_rows)

        tmp = cache_file.with_suffix(".jsonl.tmp")
        with tmp.open("w") as f:
            offset = 0
            while offset < total:
                payload = (
                    first if offset == 0 else self._fetch_rows(split_name, offset=offset, length=1)
                )
                for item in payload.get("rows", []):
                    row = item.get("row", {})
                    f.write(json.dumps(row) + "\n")
                    offset += 1
                    if offset >= total:
                        break
        tmp.rename(cache_file)

    def _fetch_rows(self, split_name: str, offset: int, length: int) -> dict:
        query = urllib.parse.urlencode(
            {
                "dataset": _HF_DATASET,
                "config": _HF_CONFIG,
                "split": split_name,
                "offset": offset,
                "length": length,
            }
        )
        url = f"https://datasets-server.huggingface.co/rows?{query}"
        with urllib.request.urlopen(url, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _parse_hf_rows(self, rows: list[dict]) -> None:
        """Normalize public Hugging Face rows into harness instances."""
        for row_idx, row in enumerate(rows):
            split_name = row.get("_split", "Accurate_Retrieval")
            category = _HF_SPLITS.get(split_name, "accurate_retrieval")
            source = (row.get("metadata") or {}).get("source") or split_name
            row_id = f"{split_name}_{row_idx:04d}"

            sessions = self._context_to_sessions(
                row_id=row_id,
                context=row.get("context", ""),
                split_name=split_name,
                source=source,
            )

            queries, gt = self._parse_hf_questions(
                row=row,
                row_id=row_id,
                category=category,
            )

            self._sessions.extend(sessions)
            self._queries.extend(queries)
            self._ground_truth.update(gt)
            self._instances.append((sessions, queries, gt))

    def _context_to_sessions(
        self,
        row_id: str,
        context: str,
        split_name: str,
        source: str,
    ) -> list[list[ConversationTurn]]:
        """Split a large context string into ingestible turns."""
        chunks = _split_context(context)
        turns = [
            ConversationTurn(
                role="system",
                content=chunk,
                turn_id=i,
                session_id=row_id,
                metadata={
                    "source": source,
                    "split": split_name,
                    "chunk_index": i,
                },
            )
            for i, chunk in enumerate(chunks)
            if chunk.strip()
        ]
        return [turns] if turns else []

    def _parse_hf_questions(
        self,
        row: dict,
        row_id: str,
        category: str,
    ) -> tuple[list[MemoryQuery], dict[str, GroundTruth]]:
        questions = row.get("questions") or []
        answers = row.get("answers") or []
        metadata = row.get("metadata") or {}
        qa_ids = metadata.get("qa_pair_ids") or metadata.get("question_ids") or []
        keypoints = metadata.get("keypoints") or []

        queries: list[MemoryQuery] = []
        gt: dict[str, GroundTruth] = {}

        for idx, question in enumerate(questions):
            # qa_pair_ids in metadata are NOT globally unique across rows or
            # splits (e.g. "eventqa_full_no0" repeats), so always namespace
            # by row_id to avoid silent overwrites in self._ground_truth and
            # downstream prediction dicts.
            local_qid = str(qa_ids[idx]) if idx < len(qa_ids) else f"q{idx:04d}"
            query_id = f"{row_id}::{local_qid}"
            raw_answer = answers[idx] if idx < len(answers) else ""
            answer = _answer_to_text(raw_answer)
            aliases = _answer_aliases(raw_answer)

            queries.append(
                MemoryQuery(
                    query_id=query_id,
                    question=str(question),
                    category=category,
                    session_id=row_id,
                    metadata={
                        "source": metadata.get("source"),
                        "split": row.get("_split"),
                        "row_id": row_id,
                        "answer_aliases": aliases,
                    },
                )
            )

            gt[query_id] = GroundTruth(
                query_id=query_id,
                answer=answer,
                category=category,
                evidence=keypoints if isinstance(keypoints, list) else [],
                metadata={
                    "answer_aliases": aliases,
                    "source": metadata.get("source"),
                    "row_id": row_id,
                },
            )

        return queries, gt

    def _parse_episodes(
        self,
        raw: list[dict],
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

    def _parse_questions(
        self,
        raw: list[dict],
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

            queries.append(
                MemoryQuery(
                    query_id=str(query_id),
                    question=question,
                    category=category,
                    session_id=item.get("episode_id", ""),
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
        """Return one independent instance per MemoryAgentBench row."""
        return self._instances or [(self._sessions, self._queries, self._ground_truth)]

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

            aliases = gt.metadata.get("answer_aliases") or [gt.answer]
            f1_scores = _best_token_f1(pred, aliases)
            em = max(exact_match(pred, ref) for ref in aliases) if aliases else 0.0
            hit = substring_match(pred, aliases)

            # Task completion: generous — any meaningful match counts
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


def _split_context(context: str, max_chars: int = 6000) -> list[str]:
    """Split large benchmark contexts into stable chunks."""
    if not context:
        return []

    max_chunks_env = os.environ.get("ALIVE_BENCH_MAX_CONTEXT_CHUNKS")
    max_chunks = int(max_chunks_env) if max_chunks_env else None
    parts = re.split(r"(?=\n?Document\s+\d+:)", context)
    chunks: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_chars:
            chunks.append(part)
            if max_chunks is not None and len(chunks) >= max_chunks:
                return chunks
            continue
        for start in range(0, len(part), max_chars):
            chunks.append(part[start : start + max_chars])
            if max_chunks is not None and len(chunks) >= max_chunks:
                return chunks
    return chunks


def _answer_to_text(answer) -> str:
    aliases = _answer_aliases(answer)
    return aliases[0] if aliases else ""


def _answer_aliases(answer) -> list[str]:
    if answer is None:
        return []
    if isinstance(answer, str):
        return [answer]
    if isinstance(answer, list):
        aliases: list[str] = []
        for item in answer:
            aliases.extend(_answer_aliases(item))
        return [a for a in aliases if a]
    if isinstance(answer, dict):
        return [json.dumps(answer, sort_keys=True)]
    return [str(answer)]


def _best_token_f1(pred: str, references: list[str]) -> dict[str, float]:
    if not references:
        return token_f1(pred, "")
    scores = [token_f1(pred, ref) for ref in references]
    return max(scores, key=lambda s: s["f1"])
