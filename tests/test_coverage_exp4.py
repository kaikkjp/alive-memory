"""Experiment 4: Tests targeting LLM providers (anthropic, openrouter),
embeddings/api, and remaining small gaps in consolidation/wake/whisper."""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Anthropic Provider ────────────────────────────────────────────


def test_anthropic_provider_import_error():
    """Cover anthropic.py lines 24-29: ImportError when anthropic not installed."""
    # Temporarily remove anthropic from sys.modules if present
    saved = sys.modules.pop("anthropic", None)
    saved_provider = sys.modules.pop("alive_memory.llm.anthropic", None)
    try:
        with patch.dict(sys.modules, {"anthropic": None}):
            # Force reimport
            if "alive_memory.llm.anthropic" in sys.modules:
                del sys.modules["alive_memory.llm.anthropic"]
            with pytest.raises(ImportError, match="anthropic package required"):
                from alive_memory.llm.anthropic import AnthropicProvider
                AnthropicProvider(api_key="test")
    finally:
        if saved is not None:
            sys.modules["anthropic"] = saved
        if saved_provider is not None:
            sys.modules["alive_memory.llm.anthropic"] = saved_provider


def test_anthropic_provider_init():
    """Cover anthropic.py lines 19-31: successful initialization."""
    # Create a mock anthropic module
    mock_anthropic = types.ModuleType("anthropic")
    mock_anthropic.AsyncAnthropic = MagicMock()

    saved = sys.modules.get("anthropic")
    saved_provider = sys.modules.pop("alive_memory.llm.anthropic", None)
    try:
        sys.modules["anthropic"] = mock_anthropic
        if "alive_memory.llm.anthropic" in sys.modules:
            del sys.modules["alive_memory.llm.anthropic"]

        from alive_memory.llm.anthropic import AnthropicProvider
        provider = AnthropicProvider(api_key="sk-test", model="claude-test")
        assert provider._model == "claude-test"
        mock_anthropic.AsyncAnthropic.assert_called_once_with(api_key="sk-test")
    finally:
        if saved is not None:
            sys.modules["anthropic"] = saved
        elif "anthropic" in sys.modules:
            del sys.modules["anthropic"]
        if saved_provider is not None:
            sys.modules["alive_memory.llm.anthropic"] = saved_provider


async def test_anthropic_provider_complete():
    """Cover anthropic.py lines 33-62: complete method with system prompt."""
    mock_anthropic = types.ModuleType("anthropic")
    mock_client = AsyncMock()

    # Build mock response
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "Hello world"
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5
    mock_client.messages.create.return_value = mock_response

    mock_anthropic.AsyncAnthropic = MagicMock(return_value=mock_client)

    saved = sys.modules.get("anthropic")
    saved_provider = sys.modules.pop("alive_memory.llm.anthropic", None)
    try:
        sys.modules["anthropic"] = mock_anthropic
        if "alive_memory.llm.anthropic" in sys.modules:
            del sys.modules["alive_memory.llm.anthropic"]

        from alive_memory.llm.anthropic import AnthropicProvider
        provider = AnthropicProvider(api_key="sk-test")

        # Test with system prompt
        result = await provider.complete("test prompt", system="you are helpful")
        assert result.text == "Hello world"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.metadata["provider"] == "anthropic"

        # Verify system was passed
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "you are helpful"

        # Test without system prompt
        mock_client.messages.create.reset_mock()
        result2 = await provider.complete("test prompt")
        call_kwargs2 = mock_client.messages.create.call_args[1]
        assert "system" not in call_kwargs2
    finally:
        if saved is not None:
            sys.modules["anthropic"] = saved
        elif "anthropic" in sys.modules:
            del sys.modules["anthropic"]
        if saved_provider is not None:
            sys.modules["alive_memory.llm.anthropic"] = saved_provider


async def test_anthropic_provider_complete_multi_block():
    """Cover anthropic.py lines 52-55: multiple content blocks, non-text block."""
    mock_anthropic = types.ModuleType("anthropic")
    mock_client = AsyncMock()

    block1 = MagicMock()
    block1.type = "text"
    block1.text = "Part 1"
    block2 = MagicMock()
    block2.type = "tool_use"  # non-text block
    block2.text = "ignored"
    block3 = MagicMock()
    block3.type = "text"
    block3.text = " Part 2"

    mock_response = MagicMock()
    mock_response.content = [block1, block2, block3]
    mock_response.usage.input_tokens = 15
    mock_response.usage.output_tokens = 8
    mock_client.messages.create.return_value = mock_response

    mock_anthropic.AsyncAnthropic = MagicMock(return_value=mock_client)

    saved = sys.modules.get("anthropic")
    saved_provider = sys.modules.pop("alive_memory.llm.anthropic", None)
    try:
        sys.modules["anthropic"] = mock_anthropic
        if "alive_memory.llm.anthropic" in sys.modules:
            del sys.modules["alive_memory.llm.anthropic"]

        from alive_memory.llm.anthropic import AnthropicProvider
        provider = AnthropicProvider(api_key="sk-test")
        result = await provider.complete("test")
        assert result.text == "Part 1 Part 2"
    finally:
        if saved is not None:
            sys.modules["anthropic"] = saved
        elif "anthropic" in sys.modules:
            del sys.modules["anthropic"]
        if saved_provider is not None:
            sys.modules["alive_memory.llm.anthropic"] = saved_provider


# ── OpenRouter Provider ───────────────────────────────────────────


def test_openrouter_provider_no_api_key():
    """Cover openrouter.py lines 43-46: ValueError when no API key."""
    with patch.dict("os.environ", {}, clear=False):
        # Remove OPENROUTER_API_KEY if present
        import os
        old = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            from alive_memory.llm.openrouter import OpenRouterProvider
            with pytest.raises(ValueError, match="OpenRouter API key required"):
                OpenRouterProvider(api_key="")
        finally:
            if old is not None:
                os.environ["OPENROUTER_API_KEY"] = old


def test_openrouter_provider_init():
    """Cover openrouter.py lines 35-49: successful init."""
    from alive_memory.llm.openrouter import OpenRouterProvider
    provider = OpenRouterProvider(api_key="sk-or-test", model="test-model")
    assert provider._model == "test-model"
    assert provider._api_key == "sk-or-test"
    assert provider._max_retries == 3
    assert provider._backoff_delays == [2, 4, 8]


def test_openrouter_provider_init_from_env():
    """Cover openrouter.py line 42: API key from environment."""
    import os
    old = os.environ.get("OPENROUTER_API_KEY")
    try:
        os.environ["OPENROUTER_API_KEY"] = "sk-or-env-test"
        from alive_memory.llm.openrouter import OpenRouterProvider
        provider = OpenRouterProvider()
        assert provider._api_key == "sk-or-env-test"
    finally:
        if old is not None:
            os.environ["OPENROUTER_API_KEY"] = old
        else:
            os.environ.pop("OPENROUTER_API_KEY", None)


async def test_openrouter_provider_complete():
    """Cover openrouter.py lines 51-117: complete method success path."""
    import httpx
    from alive_memory.llm.openrouter import OpenRouterProvider

    provider = OpenRouterProvider(api_key="sk-or-test")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello from OpenRouter"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
        "model": "anthropic/claude-sonnet",
    }
    mock_response.headers = {"x-openrouter-request-id": "req-123"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete("test prompt", system="be helpful")

    assert result.text == "Hello from OpenRouter"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.metadata["provider"] == "openrouter"
    assert result.metadata["request_id"] == "req-123"


async def test_openrouter_provider_complete_no_system():
    """Cover openrouter.py line 60-62: without system prompt."""
    from alive_memory.llm.openrouter import OpenRouterProvider

    provider = OpenRouterProvider(api_key="sk-or-test")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "No system"}}],
        "usage": {},
        "model": "test",
    }
    mock_response.headers = {}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete("test prompt")

    assert result.text == "No system"
    # Verify messages don't include system
    call_kwargs = mock_client.post.call_args
    body = call_kwargs[1]["json"]
    assert body["messages"][0]["role"] == "user"


async def test_openrouter_provider_retry_on_timeout():
    """Cover openrouter.py lines 85-90: retry on timeout."""
    import httpx
    from alive_memory.llm.openrouter import OpenRouterProvider

    provider = OpenRouterProvider(api_key="sk-or-test", backoff_delays=[0, 0, 0])

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "After retry"}}],
        "usage": {},
    }
    mock_response.headers = {}

    mock_client = AsyncMock()
    # First call raises timeout, second succeeds
    mock_client.post.side_effect = [httpx.ReadTimeout("timeout"), mock_response]
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete("test")

    assert result.text == "After retry"
    assert mock_client.post.call_count == 2


async def test_openrouter_provider_retry_on_status():
    """Cover openrouter.py lines 92-95: retry on retryable status code."""
    from alive_memory.llm.openrouter import OpenRouterProvider

    provider = OpenRouterProvider(api_key="sk-or-test", backoff_delays=[0, 0, 0])

    retry_response = MagicMock()
    retry_response.status_code = 429

    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.json.return_value = {
        "choices": [{"message": {"content": "OK"}}],
        "usage": {},
    }
    ok_response.headers = {}

    mock_client = AsyncMock()
    mock_client.post.side_effect = [retry_response, ok_response]
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete("test")

    assert result.text == "OK"


async def test_openrouter_provider_non_retryable_error():
    """Cover openrouter.py lines 97-100: non-retryable error raises."""
    from alive_memory.llm.openrouter import OpenRouterProvider

    provider = OpenRouterProvider(api_key="sk-or-test")

    error_response = MagicMock()
    error_response.status_code = 400
    error_response.text = "Bad request"

    mock_client = AsyncMock()
    mock_client.post.return_value = error_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="OpenRouter error 400"):
            await provider.complete("test")


async def test_openrouter_provider_timeout_exhausted():
    """Cover openrouter.py line 90: raise after all retries exhausted."""
    import httpx
    from alive_memory.llm.openrouter import OpenRouterProvider

    provider = OpenRouterProvider(api_key="sk-or-test", max_retries=2, backoff_delays=[0])

    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.ConnectTimeout("timeout")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.ConnectTimeout):
            await provider.complete("test")


# ── OpenAI Embedding Provider ────────────────────────────────────


def test_openai_embedding_import_error():
    """Cover embeddings/api.py lines 21-26: ImportError when openai not installed."""
    saved = sys.modules.pop("openai", None)
    saved_provider = sys.modules.pop("alive_memory.embeddings.api", None)
    try:
        with patch.dict(sys.modules, {"openai": None}):
            if "alive_memory.embeddings.api" in sys.modules:
                del sys.modules["alive_memory.embeddings.api"]
            with pytest.raises(ImportError, match="openai package required"):
                from alive_memory.embeddings.api import OpenAIEmbeddingProvider
                OpenAIEmbeddingProvider(api_key="test")
    finally:
        if saved is not None:
            sys.modules["openai"] = saved
        if saved_provider is not None:
            sys.modules["alive_memory.embeddings.api"] = saved_provider


def test_openai_embedding_init_and_dimensions():
    """Cover embeddings/api.py lines 16-36, 45-47: init + dimensions property."""
    mock_openai = types.ModuleType("openai")
    mock_openai.AsyncOpenAI = MagicMock()

    saved = sys.modules.get("openai")
    saved_provider = sys.modules.pop("alive_memory.embeddings.api", None)
    try:
        sys.modules["openai"] = mock_openai
        if "alive_memory.embeddings.api" in sys.modules:
            del sys.modules["alive_memory.embeddings.api"]

        from alive_memory.embeddings.api import OpenAIEmbeddingProvider
        provider = OpenAIEmbeddingProvider(api_key="sk-test", model="text-embedding-3-small")
        assert provider.dimensions == 1536

        provider2 = OpenAIEmbeddingProvider(api_key="sk-test", model="text-embedding-3-large")
        assert provider2.dimensions == 3072

        provider3 = OpenAIEmbeddingProvider(api_key="sk-test", model="unknown-model")
        assert provider3.dimensions == 1536  # default
    finally:
        if saved is not None:
            sys.modules["openai"] = saved
        elif "openai" in sys.modules:
            del sys.modules["openai"]
        if saved_provider is not None:
            sys.modules["alive_memory.embeddings.api"] = saved_provider


async def test_openai_embedding_embed():
    """Cover embeddings/api.py lines 38-43: embed method."""
    mock_openai = types.ModuleType("openai")
    mock_client = AsyncMock()
    mock_embedding = MagicMock()
    mock_embedding.embedding = [0.1, 0.2, 0.3]
    mock_response = MagicMock()
    mock_response.data = [mock_embedding]
    mock_client.embeddings.create.return_value = mock_response
    mock_openai.AsyncOpenAI = MagicMock(return_value=mock_client)

    saved = sys.modules.get("openai")
    saved_provider = sys.modules.pop("alive_memory.embeddings.api", None)
    try:
        sys.modules["openai"] = mock_openai
        if "alive_memory.embeddings.api" in sys.modules:
            del sys.modules["alive_memory.embeddings.api"]

        from alive_memory.embeddings.api import OpenAIEmbeddingProvider
        provider = OpenAIEmbeddingProvider(api_key="sk-test")
        result = await provider.embed("Hello world")
        assert result == [0.1, 0.2, 0.3]
        mock_client.embeddings.create.assert_called_once()
    finally:
        if saved is not None:
            sys.modules["openai"] = saved
        elif "openai" in sys.modules:
            del sys.modules["openai"]
        if saved_provider is not None:
            sys.modules["alive_memory.embeddings.api"] = saved_provider


# ── Server models converters (without fastapi) ───────────────────
# These only need pydantic which is already installed

def test_server_config_defaults():
    """Cover server/config.py lines 8-27: ServerConfig with defaults and env."""
    import os

    # Clear relevant env vars
    env_keys = ["ALIVE_HOST", "ALIVE_PORT", "ALIVE_DB", "ALIVE_CONFIG",
                "ALIVE_API_KEY", "ALIVE_CORS_ORIGINS"]
    old_vals = {k: os.environ.pop(k, None) for k in env_keys}
    try:
        from alive_memory.server.config import ServerConfig
        config = ServerConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8100
        assert config.db_path == "memory.db"
        assert config.config_path is None
        assert config.api_key is None
        assert config.cors_origins == ["*"]
    finally:
        for k, v in old_vals.items():
            if v is not None:
                os.environ[k] = v


def test_server_config_from_env():
    """Cover server/config.py lines 19-27: ServerConfig from environment."""
    import os

    env_keys = ["ALIVE_HOST", "ALIVE_PORT", "ALIVE_DB", "ALIVE_CONFIG",
                "ALIVE_API_KEY", "ALIVE_CORS_ORIGINS"]
    old_vals = {k: os.environ.get(k) for k in env_keys}
    try:
        os.environ["ALIVE_HOST"] = "127.0.0.1"
        os.environ["ALIVE_PORT"] = "9000"
        os.environ["ALIVE_DB"] = "/tmp/test.db"
        os.environ["ALIVE_CONFIG"] = "/tmp/config.yaml"
        os.environ["ALIVE_API_KEY"] = "test-key"
        os.environ["ALIVE_CORS_ORIGINS"] = "http://localhost:3000, http://example.com"

        # Force reimport
        saved = sys.modules.pop("alive_memory.server.config", None)
        try:
            from alive_memory.server.config import ServerConfig
            config = ServerConfig()
            assert config.host == "127.0.0.1"
            assert config.port == 9000
            assert config.db_path == "/tmp/test.db"
            assert config.config_path == "/tmp/config.yaml"
            assert config.api_key == "test-key"
            assert config.cors_origins == ["http://localhost:3000", "http://example.com"]
        finally:
            if saved is not None:
                sys.modules["alive_memory.server.config"] = saved
    finally:
        for k, v in old_vals.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)


def test_server_models_converters():
    """Cover server/models.py lines 143-225: all converter functions."""
    pytest.importorskip("pydantic", reason="pydantic required for server models")
    from alive_memory.server.models import (
        moment_to_response,
        recall_context_to_response,
        cognitive_state_to_response,
        self_model_to_response,
        drive_state_to_response,
        sleep_report_to_response,
        consolidation_report_to_response,
        ConsolidationReportResponse,
        SleepReportResponse,
    )
    from alive_memory.types import (
        CognitiveState, DayMoment, DriveState, EventType,
        MoodState, RecallContext, SelfModel, SleepReport,
    )

    # moment_to_response
    moment = DayMoment(
        id="m1", event_type=EventType.CONVERSATION, content="test",
        salience=0.8, valence=0.5, drive_snapshot={"social": 0.5},
        timestamp=datetime.now(timezone.utc), metadata={"key": "val"},
    )
    resp = moment_to_response(moment)
    assert resp.id == "m1"
    assert resp.content == "test"
    assert resp.event_type == "conversation"
    assert resp.salience == 0.8

    # recall_context_to_response
    ctx = RecallContext(
        journal_entries=["j1"], visitor_notes=["v1"],
        self_knowledge=["s1"], reflections=["r1"],
        thread_context=["t1"], query="test", total_hits=5,
    )
    resp2 = recall_context_to_response(ctx)
    assert resp2.total_hits == 5
    assert resp2.query == "test"

    # cognitive_state_to_response
    state = CognitiveState(
        mood=MoodState(valence=0.5, arousal=0.3, word="calm"),
        energy=0.7,
        drives=DriveState(curiosity=0.5, social=0.5, expression=0.5, rest=0.5),
        cycle_count=10,
        last_sleep=None,
        memories_total=42,
    )
    resp3 = cognitive_state_to_response(state)
    assert resp3.mood.word == "calm"
    assert resp3.energy == 0.7
    assert resp3.cycle_count == 10

    # self_model_to_response
    model = SelfModel(
        traits={"openness": 0.8}, behavioral_summary="test summary",
        drift_history=[{"delta": 0.1}], version=2,
        snapshot_at=datetime.now(timezone.utc),
    )
    resp4 = self_model_to_response(model)
    assert resp4.version == 2
    assert resp4.behavioral_summary == "test summary"

    # drive_state_to_response
    drives = DriveState(curiosity=0.1, social=0.2, expression=0.3, rest=0.4)
    resp5 = drive_state_to_response(drives)
    assert resp5.curiosity == 0.1
    assert resp5.rest == 0.4

    # sleep_report_to_response
    report = SleepReport(
        moments_processed=5, journal_entries_written=2,
        reflections_written=1, cold_embeddings_added=3,
        cold_echoes_found=1, dreams=["dream1"],
        reflections=["ref1"], identity_drift={"delta": 0.05},
        duration_ms=1500, depth="full",
    )
    resp6 = sleep_report_to_response(report)
    assert resp6.moments_processed == 5
    assert resp6.depth == "full"

    # Alias
    assert consolidation_report_to_response is sleep_report_to_response
    assert ConsolidationReportResponse is SleepReportResponse


def test_server_models_request_models():
    """Cover server/models.py lines 24-58: all request model constructors."""
    pytest.importorskip("pydantic", reason="pydantic required for server models")
    from alive_memory.server.models import (
        IntakeRequest, RecallRequest, ConsolidateRequest,
        DriveUpdateRequest, BackstoryRequest,
    )

    intake = IntakeRequest(event_type="conversation", content="hello")
    assert intake.event_type == "conversation"
    assert intake.metadata is None

    recall = RecallRequest(query="test")
    assert recall.limit == 10

    consolidate = ConsolidateRequest()
    assert consolidate.depth == "full"

    drive = DriveUpdateRequest(delta=0.5)
    assert drive.delta == 0.5

    backstory = BackstoryRequest(content="origin story", title="origin")
    assert backstory.title == "origin"


def test_server_models_response_models():
    """Cover server/models.py lines 63-138: all response model constructors."""
    pytest.importorskip("pydantic", reason="pydantic required for server models")
    from alive_memory.server.models import (
        DayMomentResponse, RecallContextResponse, MoodResponse,
        DriveStateResponse, CognitiveStateResponse, SelfModelResponse,
        SleepReportResponse, HealthResponse,
    )

    moment_resp = DayMomentResponse(
        id="m1", content="test", event_type="conversation",
        salience=0.5, valence=0.0, timestamp=datetime.now(timezone.utc),
    )
    assert moment_resp.drive_snapshot == {}

    recall_resp = RecallContextResponse()
    assert recall_resp.total_hits == 0

    mood = MoodResponse(valence=0.5, arousal=0.3, word="calm")
    assert mood.word == "calm"

    drives = DriveStateResponse(curiosity=0.5, social=0.5, expression=0.5, rest=0.5)
    assert drives.curiosity == 0.5

    cog = CognitiveStateResponse(
        mood=mood, energy=0.7, drives=drives, cycle_count=1,
    )
    assert cog.memories_total == 0

    identity = SelfModelResponse()
    assert identity.version == 0

    sleep = SleepReportResponse()
    assert sleep.depth == "full"

    health = HealthResponse()
    assert health.status == "ok"


# ── Remaining small coverage gaps ─────────────────────────────────


async def test_consolidation_wake_embedding_failure():
    """Cover wake.py lines 137-143: cold embedding step with individual moment failure."""
    from alive_memory.consolidation.wake import run_wake_transition, WakeConfig
    from alive_memory.types import DayMoment, EventType

    storage = AsyncMock()
    moments = [DayMoment(
        id="m1", event_type=EventType.CONVERSATION, content="test",
        salience=0.8, valence=0.0, drive_snapshot={},
        timestamp=datetime.now(timezone.utc), metadata={},
    )]
    storage.get_unprocessed_moments.return_value = moments
    storage.flush_stale_moments = AsyncMock(return_value=0)
    storage.flush_day_memory = AsyncMock(return_value=1)
    storage.store_cold_embedding = AsyncMock()

    # Provide an embedder that raises on embed
    embedder = AsyncMock()
    embedder.embed.side_effect = Exception("embed failed")

    cfg = WakeConfig()
    report = await run_wake_transition(storage, embedder=embedder, config=cfg)
    # Should handle the error gracefully - 0 embeddings added
    assert report.cold_embeddings_added == 0


async def test_consolidation_whisper_set_parameter_failure():
    """Cover whisper.py lines 254-255: set_parameter exception in process_whispers."""
    from alive_memory.consolidation.whisper import process_whispers

    storage = AsyncMock()
    storage.set_parameter = AsyncMock(side_effect=Exception("db error"))

    whispers = [{"type": "config_change", "key": "salience.base", "old_value": 0.5, "new_value": 0.6}]
    result = await process_whispers(whispers, storage)
    assert isinstance(result, list)


def test_hot_reader_missing_file(tmp_path):
    """Cover reader.py line 146, 199: reading from directory with no files."""
    from alive_memory.hot.reader import MemoryReader

    reader = MemoryReader(str(tmp_path))
    # grep_memory on empty directory
    results = reader.grep_memory("nonexistent query")
    assert isinstance(results, list)
    assert len(results) == 0


async def test_embeddings_local_dimensions():
    """Cover embeddings/local.py line 29-30: dimensions property."""
    from alive_memory.embeddings.local import LocalEmbeddingProvider

    provider = LocalEmbeddingProvider(dimensions=64)
    assert provider.dimensions == 64
    vec = await provider.embed("")
    assert len(vec) == 64


async def test_wake_transition_full_success():
    """Cover wake.py lines 118-149: full success path with embedder."""
    from alive_memory.consolidation.wake import run_wake_transition, WakeConfig
    from alive_memory.types import DayMoment, EventType

    storage = AsyncMock()
    moments = [DayMoment(
        id="m1", event_type=EventType.CONVERSATION, content="test",
        salience=0.8, valence=0.0, drive_snapshot={},
        timestamp=datetime.now(timezone.utc), metadata={},
    )]
    storage.get_unprocessed_moments.return_value = moments
    storage.flush_stale_moments = AsyncMock(return_value=0)
    storage.flush_day_memory = AsyncMock(return_value=1)
    storage.store_cold_embedding = AsyncMock()

    embedder = AsyncMock()
    embedder.embed.return_value = [0.1, 0.2, 0.3]

    cfg = WakeConfig()
    report = await run_wake_transition(storage, embedder=embedder, config=cfg)
    assert report.cold_embeddings_added == 1
    assert report.day_memory_flushed == 1


async def test_wake_transition_outer_exception():
    """Cover wake.py lines 142-143: outer exception in embedding step."""
    from alive_memory.consolidation.wake import run_wake_transition, WakeConfig

    storage = AsyncMock()
    # get_unprocessed_moments raises
    storage.get_unprocessed_moments.side_effect = Exception("db error")
    storage.flush_stale_moments = AsyncMock(return_value=0)
    storage.flush_day_memory = AsyncMock(return_value=0)

    embedder = AsyncMock()

    cfg = WakeConfig()
    report = await run_wake_transition(storage, embedder=embedder, config=cfg)
    assert report.cold_embeddings_added == 0
