"""LoCoMo dataset adapter.

LoCoMo (Long-Context Conversational Memory) evaluates memory over very long
conversations. It includes QA, event summarization, and dialogue generation
tasks.

Dataset: https://huggingface.co/datasets/locomo-ai/LoCoMo
Paper: https://arxiv.org/abs/2402.17753

Categories:
- single_hop: Direct factual recall
- multi_hop: Multi-step reasoning over conversation
- temporal: Time-aware questions
- open_domain: General knowledge + conversation
- adversarial: Questions designed to trick systems
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from benchmarks.academic.harness.base import (
    ConversationTurn,
    DatasetAdapter,
    EvalResult,
    GroundTruth,
    MemoryQuery,
)
from benchmarks.academic.harness.scoring import rouge_l, substring_match, token_f1


class LoCoMoDataset(DatasetAdapter):
    """Adapter for the LoCoMo benchmark dataset."""

    def __init__(self) -> None:
        self._sessions: list[list[ConversationTurn]] = []
        self._queries: list[MemoryQuery] = []
        self._ground_truth: dict[str, GroundTruth] = {}
        self._loaded = False

    @property
    def benchmark_id(self) -> str:
        return "locomo"

    async def load(self, data_dir: str, split: str = "test") -> None:
        """Load LoCoMo dataset from local directory.

        Expected structure:
            data_dir/locomo/
                conversations.json  — list of conversation objects
                questions.json      — list of QA pairs with categories
        """
        base = Path(data_dir) / "locomo"
        if not base.exists():
            raise FileNotFoundError(
                f"LoCoMo data not found at {base}. "
                f"Download from: https://huggingface.co/datasets/locomo-ai/LoCoMo\n"
                f"Expected files:\n"
                f"  {base}/conversations.json\n"
                f"  {base}/questions.json"
            )

        # Load conversations
        conv_file = base / "conversations.json"
        if conv_file.exists():
            raw_convos = json.loads(conv_file.read_text())
            self._sessions = self._parse_conversations(raw_convos)

        # Load questions + ground truth
        q_file = base / "questions.json"
        if q_file.exists():
            raw_questions = json.loads(q_file.read_text())
            self._queries, self._ground_truth = self._parse_questions(raw_questions)

        self._loaded = True
        print(f"  [locomo] Loaded {len(self._sessions)} conversations, "
              f"{len(self._queries)} questions")

    def _parse_conversations(
        self, raw: list[dict],
    ) -> list[list[ConversationTurn]]:
        """Parse raw LoCoMo conversation format."""
        sessions: list[list[ConversationTurn]] = []

        for conv_idx, conv in enumerate(raw):
            turns: list[ConversationTurn] = []
            session_id = conv.get("conversation_id", f"conv_{conv_idx}")

            # LoCoMo stores turns as a list of utterances
            utterances = conv.get("conversation", conv.get("utterances", []))
            for turn_idx, utt in enumerate(utterances):
                if isinstance(utt, dict):
                    role = utt.get("role", utt.get("speaker", "user"))
                    content = utt.get("content", utt.get("text", ""))
                    timestamp = utt.get("timestamp", "")
                elif isinstance(utt, str):
                    # Simple string format: "Speaker: message"
                    if ":" in utt:
                        role, content = utt.split(":", 1)
                        role = role.strip().lower()
                        content = content.strip()
                    else:
                        role = "user" if turn_idx % 2 == 0 else "assistant"
                        content = utt
                    timestamp = ""
                else:
                    continue

                turns.append(ConversationTurn(
                    role=role.lower(),
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
        """Parse LoCoMo questions into queries + ground truth."""
        queries: list[MemoryQuery] = []
        gt: dict[str, GroundTruth] = {}

        for q_idx, item in enumerate(raw):
            query_id = item.get("question_id", item.get("id", f"q_{q_idx:04d}"))
            category = item.get("category", item.get("type", "single_hop"))
            question = item.get("question", item.get("query", ""))
            answer = item.get("answer", item.get("expected_answer", ""))

            # Evidence: conversation turn indices that support the answer
            evidence = item.get("evidence", item.get("supporting_turns", []))
            if isinstance(evidence, str):
                evidence = [evidence]

            queries.append(MemoryQuery(
                query_id=str(query_id),
                question=question,
                category=category,
                session_id=item.get("conversation_id", ""),
                metadata={"raw": item},
            ))

            gt[str(query_id)] = GroundTruth(
                query_id=str(query_id),
                answer=str(answer),
                category=category,
                evidence=[str(e) for e in evidence],
                metadata=item.get("metadata", {}),
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
        """Evaluate using token F1 and ROUGE-L (LoCoMo's standard metrics)."""
        results: list[EvalResult] = []

        for query_id, gt in ground_truth.items():
            pred = predictions.get(query_id, "")

            f1_scores = token_f1(pred, gt.answer)
            rl_scores = rouge_l(pred, gt.answer)

            # Also check substring containment for factual answers
            evidence_hit = substring_match(pred, [gt.answer]) if gt.answer else 0.0

            scores = {
                "f1": f1_scores["f1"],
                "precision": f1_scores["precision"],
                "recall": f1_scores["recall"],
                "rouge_l_f1": rl_scores["rouge_l_f1"],
                "evidence_hit": evidence_hit,
            }

            results.append(EvalResult(
                query_id=query_id,
                category=gt.category,
                predicted=pred,
                expected=gt.answer,
                scores=scores,
            ))

        return results
