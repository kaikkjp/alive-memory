"""LLM provider abstractions for alive-memory."""

from alive_memory.llm.provider import LLMProvider, LLMResponse

__all__ = ["LLMProvider", "LLMResponse"]


def _lazy_gemini():
    from alive_memory.llm.gemini import GeminiProvider
    return GeminiProvider
