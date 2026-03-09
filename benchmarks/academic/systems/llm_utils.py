"""Shared LLM calling utilities for benchmark system adapters.

All systems use the same LLM for answer generation to ensure fair comparison.
Only the memory retrieval mechanism differs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


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

    api_key = llm_config.get("api_key", os.environ.get("OPENROUTER_API_KEY", ""))
    model = llm_config.get("model", "anthropic/claude-haiku-4-5")
    base_url = llm_config.get("base_url", "https://openrouter.ai/api/v1")

    if context:
        prompt = (
            f"Based on the following conversation history, answer the question.\n\n"
            f"Conversation history:\n{context}\n\n"
            f"Question: {question}\n\n"
            f"Answer concisely. If the information is not in the history, "
            f"say 'I don't know'."
        )
    else:
        prompt = (
            f"Answer the following question. If you don't have enough "
            f"information, say 'I don't know'.\n\n"
            f"Question: {question}"
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
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[error: {e}]"
