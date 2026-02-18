"""tests/test_llm_config.py — Unit tests for llm/config.py.

No network calls, no DB. Tests use monkeypatch to control env vars.
"""

import pytest

from llm.config import get_api_key, resolve_model


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------


def test_resolve_cortex_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_CORTEX_MODEL env var should be returned for call_site='cortex'."""
    monkeypatch.setenv("LLM_CORTEX_MODEL", "openai/gpt-4o")
    monkeypatch.delenv("LLM_DEFAULT_MODEL", raising=False)

    assert resolve_model("cortex") == "openai/gpt-4o"


def test_resolve_cortex_maintenance_uses_cortex_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cortex_maintenance should also use LLM_CORTEX_MODEL."""
    monkeypatch.setenv("LLM_CORTEX_MODEL", "openai/gpt-4o")
    monkeypatch.delenv("LLM_DEFAULT_MODEL", raising=False)

    assert resolve_model("cortex_maintenance") == "openai/gpt-4o"


def test_resolve_fallback_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """When call-site env var is absent, LLM_DEFAULT_MODEL should be used."""
    monkeypatch.delenv("LLM_CORTEX_MODEL", raising=False)
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "anthropic/claude-haiku-4-5")

    assert resolve_model("cortex") == "anthropic/claude-haiku-4-5"


def test_resolve_hardcoded_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no env vars are set, hardcoded default should be returned."""
    monkeypatch.delenv("LLM_CORTEX_MODEL", raising=False)
    monkeypatch.delenv("LLM_REFLECT_MODEL", raising=False)
    monkeypatch.delenv("LLM_SLEEP_MODEL", raising=False)
    monkeypatch.delenv("LLM_EMBED_MODEL", raising=False)
    monkeypatch.delenv("LLM_DEFAULT_MODEL", raising=False)

    assert resolve_model("cortex") == "anthropic/claude-sonnet-4-5-20250929"


def test_unknown_call_site_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognised call_site should fall through to the default model."""
    monkeypatch.delenv("LLM_DEFAULT_MODEL", raising=False)

    result = resolve_model("unknown_site")

    # Falls back to hardcoded default
    assert result == "anthropic/claude-sonnet-4-5-20250929"


def test_unknown_call_site_respects_default_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown call_site with LLM_DEFAULT_MODEL set should use that model."""
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "meta-llama/llama-3-70b")

    assert resolve_model("something_new") == "meta-llama/llama-3-70b"


def test_reflect_uses_reflect_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_REFLECT_MODEL should be returned for call_site='reflect'."""
    monkeypatch.setenv("LLM_REFLECT_MODEL", "anthropic/claude-haiku-4-5")
    monkeypatch.delenv("LLM_DEFAULT_MODEL", raising=False)

    assert resolve_model("reflect") == "anthropic/claude-haiku-4-5"


def test_sleep_uses_sleep_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_SLEEP_MODEL should be returned for call_site='sleep'."""
    monkeypatch.setenv("LLM_SLEEP_MODEL", "openai/gpt-4o-mini")
    monkeypatch.delenv("LLM_DEFAULT_MODEL", raising=False)

    assert resolve_model("sleep") == "openai/gpt-4o-mini"


def test_embed_uses_embed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_EMBED_MODEL should be returned for call_site='embed'."""
    monkeypatch.setenv("LLM_EMBED_MODEL", "openai/text-embedding-3-small")
    monkeypatch.delenv("LLM_DEFAULT_MODEL", raising=False)

    assert resolve_model("embed") == "openai/text-embedding-3-small"


# ---------------------------------------------------------------------------
# get_api_key
# ---------------------------------------------------------------------------


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """ValueError should be raised when OPENROUTER_API_KEY is not set."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        get_api_key()


def test_api_key_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_api_key() should return the env var value when it is set."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    assert get_api_key() == "sk-or-test"
