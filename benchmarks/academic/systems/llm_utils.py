"""Shared LLM calling utilities for benchmark system adapters.

All systems use the same LLM for answer generation to ensure fair comparison.
Only the memory retrieval mechanism differs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _extract_answer(text: str) -> str:
    """Extract the final answer from chain-of-thought response.

    Looks for the last "ANSWER: ..." line. Falls back to full text
    if no ANSWER line is found.
    """
    lines = text.strip().split("\n")
    # Search from bottom up for the last ANSWER: line
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.upper().startswith("ANSWER:"):
            return stripped[7:].strip()
    # No ANSWER: line found — return full text
    return text.strip()


@dataclass
class LLMTracker:
    """Tracks LLM usage across calls."""

    total_calls: int = 0
    total_tokens: int = 0


async def llm_answer(
    question: str,
    context: str,
    llm_config: dict,
    tracker: LLMTracker,
) -> str:
    """Generate an answer using an LLM with optional memory context.

    Args:
        question: The query to answer.
        context: Retrieved memory context (empty string = no context).
        llm_config: Dict with 'api_key', 'model', 'base_url'.
        tracker: Tracks cumulative LLM usage.

    Returns:
        Answer string.
    """
    try:
        import httpx
    except ImportError:
        return "[error: httpx not installed]"

    api_key = llm_config.get("api_key", os.environ.get(
        "OPENAI_API_KEY", os.environ.get("OPENROUTER_API_KEY", ""),
    ))
    model = llm_config.get("model", "gpt-4o-mini")
    base_url = llm_config.get("base_url", "https://api.openai.com/v1")

    if context:
        prompt = (
            f"You are answering questions about a user's past conversations. "
            f"The relevant excerpts are provided below.\n\n"
            f"{context}\n\n"
            f"Question: {question}\n\n"
            f"Reason through the excerpts to find the answer. "
            f"If a fact was updated across conversations, use the MOST RECENT value. "
            f"Then give your final answer on its own line starting with \"ANSWER: \".\n"
            f"The ANSWER must be ONLY the specific fact — a name, date, "
            f"place, number, or short phrase. No explanation after ANSWER.\n"
            f"If the excerpts contain no relevant information: ANSWER: I don't know"
        )
    else:
        prompt = (
            f"Question: {question}\n\nANSWER: I don't know"
        )

    try:
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
                    "max_tokens": 300,
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            tracker.total_calls += 1
            usage = data.get("usage", {})
            tracker.total_tokens += usage.get("total_tokens", 0)
            raw = data["choices"][0]["message"]["content"].strip()
            return _extract_answer(raw)
    except Exception as e:
        return f"[error: {e}]"
