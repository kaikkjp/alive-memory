"""LoCoMo dataset adapter.

LoCoMo (Long-Context Conversational Memory) evaluates memory over very long
multi-session conversations (19-32 sessions each). Contains 10 conversation
samples with 1,986 total QA pairs.

Dataset: https://github.com/snap-research/locomo (data/locomo10.json)
Paper: https://arxiv.org/abs/2402.17753

Categories (numeric in dataset):
- 1: multi_hop — Multi-step reasoning over conversation
- 2: single_hop — Direct factual recall
- 3: temporal — Time-aware questions
- 4: open_domain — General knowledge + conversation
- 5: adversarial — Questions designed to trick systems (abstention)
"""

from __future__ import annotations

import json
import re
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
    rouge_l,
    substring_match,
    token_f1,
)

# Map numeric category to string name
_CATEGORY_MAP = {
    1: "multi_hop",
    2: "single_hop",
    3: "temporal",
    4: "open_domain",
    5: "adversarial",
}


class LoCoMoDataset(DatasetAdapter):
    """Adapter for the LoCoMo benchmark dataset.

    Parses the canonical locomo10.json format where each sample contains
    conversation sessions (session_1..session_N) and QA pairs.
    """

    def __init__(self) -> None:
        self._sessions: list[list[ConversationTurn]] = []
        self._queries: list[MemoryQuery] = []
        self._ground_truth: dict[str, GroundTruth] = {}
        # Per-sample instances for isolated evaluation
        self._instances: list[tuple[list[list[ConversationTurn]], list[MemoryQuery], dict[str, GroundTruth]]] = []
        self._loaded = False

    @property
    def benchmark_id(self) -> str:
        return "locomo"

    async def load(self, data_dir: str, split: str = "test") -> None:
        """Load LoCoMo dataset from local directory.

        Expected structure:
            data_dir/locomo/
                locomo10.json  — full dataset (10 conversations + QA pairs)
        """
        base = Path(data_dir) / "locomo"
        if not base.exists():
            raise FileNotFoundError(
                f"LoCoMo data not found at {base}. "
                f"Download from: https://github.com/snap-research/locomo\n"
                f"  curl -L -o {base}/locomo10.json "
                f"https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
            )

        data_file = base / "locomo10.json"
        if not data_file.exists():
            raise FileNotFoundError(
                f"Expected {data_file}. Download locomo10.json from "
                f"https://github.com/snap-research/locomo/tree/main/data"
            )

        raw = json.loads(data_file.read_text())

        total_qa = 0
        for sample in raw:
            sample_id = sample.get("sample_id", "")
            conv = sample["conversation"]
            sessions = self._parse_conversation(conv, sample_id)
            self._sessions.extend(sessions)

            queries, gt = self._parse_qa(sample["qa"], sample_id)
            self._queries.extend(queries)
            self._ground_truth.update(gt)
            total_qa += len(queries)

            # Store per-sample instance for isolated evaluation
            self._instances.append((sessions, queries, gt))

        self._loaded = True
        print(f"  [locomo] Loaded {len(raw)} conversations, "
              f"{len(self._sessions)} sessions, {total_qa} QA pairs")

    def _parse_conversation(
        self, conv: dict, sample_id: str,
    ) -> list[list[ConversationTurn]]:
        """Parse LoCoMo conversation object with session_N keys."""
        speaker_a = conv.get("speaker_a", "speaker_a")
        speaker_b = conv.get("speaker_b", "speaker_b")

        # Find all session keys (session_1, session_2, ...)
        session_keys = sorted(
            [k for k in conv.keys()
             if re.match(r"session_\d+$", k)],
            key=lambda k: int(k.split("_")[1]),
        )

        sessions: list[list[ConversationTurn]] = []
        for sess_key in session_keys:
            session_num = sess_key.split("_")[1]
            session_id = f"{sample_id}_{sess_key}"
            date_key = f"{sess_key}_date_time"
            session_date = conv.get(date_key, "")

            turns: list[ConversationTurn] = []
            for turn_idx, utt in enumerate(conv[sess_key]):
                speaker = utt.get("speaker", "")
                text = utt.get("text", "")
                dia_id = utt.get("dia_id", "")

                # Map speaker names to roles
                if speaker == speaker_a:
                    role = "user"
                elif speaker == speaker_b:
                    role = "assistant"
                else:
                    role = speaker.lower()

                turns.append(ConversationTurn(
                    role=role,
                    content=f"{speaker}: {text}",
                    turn_id=turn_idx,
                    session_id=session_id,
                    timestamp=session_date,
                    metadata={"dia_id": dia_id, "speaker": speaker},
                ))

            if turns:
                sessions.append(turns)

        return sessions

    def _parse_qa(
        self, qa_list: list[dict], sample_id: str,
    ) -> tuple[list[MemoryQuery], dict[str, GroundTruth]]:
        """Parse LoCoMo QA pairs with numeric categories."""
        queries: list[MemoryQuery] = []
        gt: dict[str, GroundTruth] = {}

        for q_idx, item in enumerate(qa_list):
            query_id = f"{sample_id}_q{q_idx:04d}"
            cat_num = item.get("category", 2)
            category = _CATEGORY_MAP.get(cat_num, f"category_{cat_num}")
            question = item.get("question", "")
            answer = str(item.get("answer", ""))
            evidence = item.get("evidence", [])

            is_adversarial = category == "adversarial"

            queries.append(MemoryQuery(
                query_id=query_id,
                question=question,
                category=category,
                session_id="",  # QA spans full conversation
                metadata={
                    "sample_id": sample_id,
                    "is_adversarial": is_adversarial,
                    "adversarial_answer": item.get("adversarial_answer", ""),
                },
            ))

            gt[query_id] = GroundTruth(
                query_id=query_id,
                answer=answer,
                category=category,
                evidence=evidence,
                metadata={"is_adversarial": is_adversarial},
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
        """Return per-sample instances. Each LoCoMo conversation is independent."""
        return self._instances

    async def evaluate(
        self,
        predictions: dict[str, str],
        ground_truth: dict[str, GroundTruth],
    ) -> list[EvalResult]:
        """Evaluate using token F1 (LoCoMo's primary metric).

        Category 5 (adversarial) uses abstention scoring.
        Category 1 (multi_hop) splits answers on ',' for partial scoring.
        """
        results: list[EvalResult] = []

        for query_id, gt in ground_truth.items():
            pred = predictions.get(query_id, "")
            is_adversarial = gt.metadata.get("is_adversarial", False)

            if is_adversarial:
                # Adversarial: system should abstain
                abst = abstention_score(pred, should_abstain=True)
                scores = {
                    "f1": abst,
                    "abstention_accuracy": abst,
                    "accuracy": abst,
                }
            elif gt.category == "multi_hop":
                # Multi-hop: check containment of each sub-answer, then
                # compute overall F1 against the full answer string.
                # Real LoCoMo answers use commas as separators
                # (e.g., "pottery, camping, painting, swimming")
                sub_answers = [a.strip() for a in gt.answer.split(",") if a.strip()]
                if len(sub_answers) <= 1:
                    sub_answers = [gt.answer]
                # Check how many sub-answers are present in prediction
                hits = sum(1 for sa in sub_answers if substring_match(pred, [sa]) > 0)
                sub_hit_rate = hits / len(sub_answers) if sub_answers else 0.0

                # F1 against full answer (not split)
                f1_scores = token_f1(pred, gt.answer)
                rl_scores = rouge_l(pred, gt.answer)
                scores = {
                    "f1": f1_scores["f1"],
                    "sub_hit_rate": sub_hit_rate,
                    "rouge_l_f1": rl_scores["rouge_l_f1"],
                    "accuracy": max(sub_hit_rate, 1.0 if f1_scores["f1"] > 0.5 else 0.0),
                }
            else:
                # Standard: token F1
                f1_scores = token_f1(pred, gt.answer)
                rl_scores = rouge_l(pred, gt.answer)
                hit = substring_match(pred, [gt.answer]) if gt.answer else 0.0

                scores = {
                    "f1": f1_scores["f1"],
                    "precision": f1_scores["precision"],
                    "recall": f1_scores["recall"],
                    "rouge_l_f1": rl_scores["rouge_l_f1"],
                    "evidence_hit": hit,
                    "accuracy": max(hit, 1.0 if f1_scores["f1"] > 0.5 else 0.0),
                }

            results.append(EvalResult(
                query_id=query_id,
                category=gt.category,
                predicted=pred,
                expected=gt.answer,
                scores=scores,
            ))

        return results
