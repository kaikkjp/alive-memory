"""Common scoring utilities for academic benchmarks.

Provides F1, BLEU, ROUGE-L, exact match, and LLM-as-judge scoring.
Benchmark-specific evaluators can use these as building blocks.
"""

from __future__ import annotations

import re
from collections import Counter


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def token_f1(prediction: str, reference: str) -> dict[str, float]:
    """Compute token-level precision, recall, F1 between two strings."""
    pred_tokens = normalize_text(prediction).split()
    ref_tokens = normalize_text(reference).split()

    if not pred_tokens or not ref_tokens:
        exact = 1.0 if pred_tokens == ref_tokens else 0.0
        return {"precision": exact, "recall": exact, "f1": exact}

    common = Counter(pred_tokens) & Counter(ref_tokens)
    num_common = sum(common.values())

    if num_common == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    precision = num_common / len(pred_tokens)
    recall = num_common / len(ref_tokens)
    f1 = 2 * precision * recall / (precision + recall)

    return {"precision": precision, "recall": recall, "f1": f1}


def exact_match(prediction: str, reference: str) -> float:
    """Case-insensitive exact match after normalization."""
    return 1.0 if normalize_text(prediction) == normalize_text(reference) else 0.0


def substring_match(prediction: str, references: list[str]) -> float:
    """Check if any reference substring appears in prediction."""
    pred_norm = normalize_text(prediction)
    for ref in references:
        ref_norm = normalize_text(ref)
        if ref_norm and ref_norm in pred_norm:
            return 1.0
    return 0.0


def rouge_l(prediction: str, reference: str) -> dict[str, float]:
    """Compute ROUGE-L (longest common subsequence) F1."""
    pred_tokens = normalize_text(prediction).split()
    ref_tokens = normalize_text(reference).split()

    if not pred_tokens or not ref_tokens:
        exact = 1.0 if pred_tokens == ref_tokens else 0.0
        return {"rouge_l_precision": exact, "rouge_l_recall": exact, "rouge_l_f1": exact}

    # LCS via DP
    m, n = len(pred_tokens), len(ref_tokens)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if pred_tokens[i - 1] == ref_tokens[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    lcs_len = dp[m][n]
    if lcs_len == 0:
        return {"rouge_l_precision": 0.0, "rouge_l_recall": 0.0, "rouge_l_f1": 0.0}

    precision = lcs_len / m
    recall = lcs_len / n
    f1 = 2 * precision * recall / (precision + recall)

    return {"rouge_l_precision": precision, "rouge_l_recall": recall, "rouge_l_f1": f1}


def abstention_score(prediction: str, should_abstain: bool) -> float:
    """Score abstention correctness.

    If should_abstain is True, the system should say "I don't know" or similar.
    If should_abstain is False, the system should give a substantive answer.
    """
    abstention_phrases = [
        "i don't know",
        "i do not know",
        "not sure",
        "no information",
        "cannot answer",
        "can't answer",
        "don't have",
        "do not have",
        "not mentioned",
        "no memory",
        "unable to",
        "i'm not aware",
        "i am not aware",
    ]
    pred_lower = prediction.lower()
    predicted_abstain = any(phrase in pred_lower for phrase in abstention_phrases)

    if should_abstain and predicted_abstain:
        return 1.0  # correct abstention
    elif not should_abstain and not predicted_abstain:
        return 1.0  # correct answer attempt
    else:
        return 0.0  # wrong
