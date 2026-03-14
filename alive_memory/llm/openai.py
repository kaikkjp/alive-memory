"""OpenAI provider for alive-memory.

Requires: pip install openai
"""

from __future__ import annotations

from alive_memory.llm.provider import LLMResponse


class OpenAIProvider:
    """LLM provider using the OpenAI Python SDK.

    Usage:
        provider = OpenAIProvider(api_key="sk-...")
        response = await provider.complete("What is memory?")
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
    ):
        try:
            import openai
        except ImportError as err:
            raise ImportError(
                "openai package required: pip install openai"
            ) from err
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._model = model

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> LLMResponse:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        text = response.choices[0].message.content or ""
        usage = response.usage

        return LLMResponse(
            text=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            metadata={"model": self._model, "provider": "openai"},
        )
