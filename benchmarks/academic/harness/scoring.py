"""Common scoring utilities for academic benchmarks.

Provides F1, BLEU, ROUGE-L, exact match, and LLM-as-judge scoring.
Benchmark-specific evaluators can use these as building blocks.
"""

from __future__ import annotations

import os
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


# ---------------------------------------------------------------------------
# LLM-as-Judge scoring
# ---------------------------------------------------------------------------

# LongMemEval official judge prompts (from xiaowu0162/LongMemEval evaluate_qa.py)
_LONGMEMEVAL_JUDGE_PROMPTS: dict[str, str] = {
    "single-session-user": (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response is equivalent to the correct answer or contains all the intermediate "
        "steps to get the correct answer, you should also answer yes. If the response only "
        "contains a subset of the information required by the answer, answer no. "
        "\n\nQuestion: {question}\n\nCorrect Answer: {answer}\n\nModel Response: {prediction}"
        "\n\nIs the model response correct? Answer yes or no only."
    ),
    "single-session-assistant": (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response is equivalent to the correct answer or contains all the intermediate "
        "steps to get the correct answer, you should also answer yes. If the response only "
        "contains a subset of the information required by the answer, answer no. "
        "\n\nQuestion: {question}\n\nCorrect Answer: {answer}\n\nModel Response: {prediction}"
        "\n\nIs the model response correct? Answer yes or no only."
    ),
    "multi-session": (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response is equivalent to the correct answer or contains all the intermediate "
        "steps to get the correct answer, you should also answer yes. If the response only "
        "contains a subset of the information required by the answer, answer no. "
        "\n\nQuestion: {question}\n\nCorrect Answer: {answer}\n\nModel Response: {prediction}"
        "\n\nIs the model response correct? Answer yes or no only."
    ),
    "temporal-reasoning": (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response is equivalent to the correct answer or contains all the intermediate "
        "steps to get the correct answer, you should also answer yes. If the response only "
        "contains a subset of the information required by the answer, answer no. "
        "In addition, do not penalize off-by-one errors for the number of days. If the question "
        "asks for the number of days/weeks/months, etc., and the model makes off-by-one errors "
        "(e.g., predicting 19 days when the answer is 18), the model's response is still correct. "
        "\n\nQuestion: {question}\n\nCorrect Answer: {answer}\n\nModel Response: {prediction}"
        "\n\nIs the model response correct? Answer yes or no only."
    ),
    "knowledge-update": (
        "I will give you a question, a correct answer, and a response from a model. "
        "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
        "If the response contains some previous information along with an updated answer, "
        "the response should be considered as correct as long as the updated answer is the "
        "required answer."
        "\n\nQuestion: {question}\n\nCorrect Answer: {answer}\n\nModel Response: {prediction}"
        "\n\nIs the model response correct? Answer yes or no only."
    ),
    "single-session-preference": (
        "I will give you a question, a rubric for desired personalized response, and a response "
        "from a model. Please answer yes if the response satisfies the desired response. "
        "Otherwise, answer no. The model does not need to reflect all the points in the rubric. "
        "The response is correct as long as it recalls and utilizes the user's personal "
        "information correctly."
        "\n\nQuestion: {question}\n\nRubric: {answer}\n\nModel Response: {prediction}"
        "\n\nIs the model response correct? Answer yes or no only."
    ),
    "abstention": (
        "I will give you an unanswerable question, an explanation, and a response from a model. "
        "Please answer yes if the model correctly identifies the question as unanswerable. "
        "The model could say that the information is incomplete, or some other information is "
        "given but the asked information is not."
        "\n\nQuestion: {question}\n\nExplanation: {answer}\n\nModel Response: {prediction}"
        "\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only."
    ),
}

# Generic judge prompt for LoCoMo and other benchmarks (matches convention
# used by Mnemis, MAGMA, etc.)
_GENERIC_JUDGE_PROMPT = (
    "I will give you a question, a correct answer, and a response from a model. "
    "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
    "If the response is equivalent to the correct answer or contains all the intermediate "
    "steps to get the correct answer, you should also answer yes. If the response only "
    "contains a subset of the information required by the answer, answer no."
    "\n\nQuestion: {question}\n\nCorrect Answer: {answer}\n\nModel Response: {prediction}"
    "\n\nIs the model response correct? Answer yes or no only."
)

# Adversarial/abstention prompt for LoCoMo category 5
_ADVERSARIAL_JUDGE_PROMPT = (
    "I will give you a question that should NOT be answerable from the conversation history, "
    "a ground truth answer, and a response from a model. "
    "Please answer yes if the model correctly identifies that the question cannot be answered "
    "from the conversation, or if the model abstains. "
    "Answer no if the model provides a confident but incorrect answer."
    "\n\nQuestion: {question}\n\nGround Truth: {answer}\n\nModel Response: {prediction}"
    "\n\nDoes the model correctly handle this unanswerable question? Answer yes or no only."
)


async def llm_judge(
    question: str,
    prediction: str,
    answer: str,
    judge_config: dict,
    question_type: str = "",
    benchmark: str = "",
) -> float:
    """Score a prediction using LLM-as-Judge (binary 0/1).

    Args:
        question: The original question.
        prediction: Model's predicted answer.
        answer: Ground truth answer.
        judge_config: Dict with 'api_key', 'model', 'base_url' for the judge LLM.
        question_type: Task-specific type (e.g., 'temporal-reasoning') for
            selecting the appropriate judge prompt template.
        benchmark: Benchmark name ('longmemeval', 'locomo', etc.) for
            selecting benchmark-specific prompts.

    Returns:
        1.0 if the judge says yes, 0.0 otherwise.

    Raises:
        RuntimeError: If the judge call fails (auth error, timeout, etc.)
            so infrastructure errors are surfaced rather than silently
            recorded as model failures.
    """
    import httpx

    # Select prompt template
    if benchmark == "longmemeval" and question_type in _LONGMEMEVAL_JUDGE_PROMPTS:
        template = _LONGMEMEVAL_JUDGE_PROMPTS[question_type]
    elif question_type in ("adversarial", "abstention"):
        template = _ADVERSARIAL_JUDGE_PROMPT
    else:
        template = _GENERIC_JUDGE_PROMPT

    prompt = template.format(
        question=question,
        answer=answer,
        prediction=prediction,
    )

    api_key = judge_config.get("api_key", os.environ.get("OPENROUTER_API_KEY", ""))
    model = judge_config.get("model", "anthropic/claude-haiku-4-5")
    base_url = judge_config.get("base_url", "https://openrouter.ai/api/v1")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 10,
                "temperature": 0,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        response_text = data["choices"][0]["message"]["content"].strip().lower()
        # Parse as exact yes/no — avoid substring matches like "yesterday"
        first_word = response_text.split()[0].strip(".,!") if response_text else ""
        return 1.0 if first_word == "yes" else 0.0
