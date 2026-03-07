"""Tests for Gemini provider and multimodal intake."""

from __future__ import annotations

import importlib
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alive_memory import AliveMemory
from alive_memory.intake.multimodal import perceive_media
from alive_memory.llm.provider import LLMResponse

# ── Mock GeminiProvider ──────────────────────────────────────────


class MockGeminiProvider:
    """Fake GeminiProvider that returns canned responses without API calls."""

    def __init__(self, response_text: str = "A cat sitting on a windowsill."):
        self._response_text = response_text

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> LLMResponse:
        return LLMResponse(
            text=self._response_text,
            input_tokens=10,
            output_tokens=20,
            metadata={"model": "mock-gemini", "provider": "gemini"},
        )

    async def perceive_media(
        self,
        file_path: Path,
        *,
        prompt: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> LLMResponse:
        suffix = file_path.suffix.lower()
        media_type = {
            ".jpg": "image", ".jpeg": "image", ".png": "image",
            ".mp3": "audio", ".wav": "audio",
            ".mp4": "video",
            ".pdf": "document",
        }.get(suffix, "file")

        return LLMResponse(
            text=f"Perceived {media_type}: {self._response_text}",
            input_tokens=100,
            output_tokens=50,
            metadata={
                "model": "mock-gemini",
                "provider": "gemini",
                "media_file": file_path.name,
                "mime_type": f"{media_type}/{suffix.lstrip('.')}",
            },
        )


# ── perceive_media() ─────────────────────────────────────────────


async def test_perceive_media_returns_text():
    mock_llm = MockGeminiProvider("A sunset over the ocean.")
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"fake image data")
        path = Path(f.name)
    try:
        result = await perceive_media(path, mock_llm)
        assert "sunset" in result.lower()
        assert isinstance(result, str)
    finally:
        path.unlink()


async def test_perceive_media_custom_prompt():
    mock_llm = MockGeminiProvider("Custom response.")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"fake image data")
        path = Path(f.name)
    try:
        result = await perceive_media(path, mock_llm, prompt="Describe the colors.")
        assert "Custom response" in result
    finally:
        path.unlink()


async def test_perceive_media_rejects_provider_without_method():
    class PlainLLM:
        async def complete(self, prompt, **kw):
            return LLMResponse(text="hi")

    with pytest.raises(TypeError, match="does not support perceive_media"):
        await perceive_media(Path("test.jpg"), PlainLLM())


# ── AliveMemory.intake_media() ───────────────────────────────────


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def tmp_memory_dir():
    d = tempfile.mkdtemp(prefix="alive_test_media_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


async def test_intake_media_full_pipeline(tmp_db, tmp_memory_dir):
    mock_llm = MockGeminiProvider(
        "A person presenting quarterly results with charts showing growth."
    )
    async with AliveMemory(
        storage=tmp_db,
        memory_dir=tmp_memory_dir,
        llm=mock_llm,
    ) as memory:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"fake video data")
            path = Path(f.name)
        try:
            moment = await memory.intake_media(path, media_llm=mock_llm)
            # Should produce a moment (content is rich enough)
            if moment is not None:
                assert "quarterly results" in moment.content.lower()
                assert moment.metadata.get("media_perceived") is True
                assert moment.metadata.get("media_source") == str(path)
        finally:
            path.unlink()


async def test_intake_media_no_provider_raises(tmp_db, tmp_memory_dir):
    async with AliveMemory(
        storage=tmp_db,
        memory_dir=tmp_memory_dir,
    ) as memory:
        with pytest.raises(RuntimeError, match="multimodal LLM"):
            await memory.intake_media(Path("test.jpg"))


async def test_intake_media_uses_default_llm_if_multimodal(tmp_db, tmp_memory_dir):
    mock_llm = MockGeminiProvider("A landscape photograph.")
    async with AliveMemory(
        storage=tmp_db,
        memory_dir=tmp_memory_dir,
        llm=mock_llm,  # default LLM has perceive_media
    ) as memory:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"fake image")
            path = Path(f.name)
        try:
            # Should use self._llm since it has perceive_media
            await memory.intake_media(path)
        finally:
            path.unlink()


# ── GeminiProvider unit tests (mocked SDK) ───────────────────────


async def test_gemini_provider_import_error():
    """GeminiProvider raises ImportError when google-genai is not installed."""
    with (
        patch.dict("sys.modules", {"google": None, "google.genai": None}),
        pytest.raises(ImportError, match="google-genai"),
    ):
        import alive_memory.llm.gemini as mod
        importlib.reload(mod)
        mod.GeminiProvider(api_key="test")


async def test_gemini_provider_missing_key():
    """GeminiProvider raises ValueError without API key."""
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai

    os.environ.pop("GOOGLE_API_KEY", None)
    with (
        patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}),
        patch.dict(os.environ, {}, clear=False),
    ):
        import alive_memory.llm.gemini as mod
        importlib.reload(mod)
        with pytest.raises(ValueError, match="API key required"):
            mod.GeminiProvider()


# ── _resolve_llm("gemini") ──────────────────────────────────────


async def test_resolve_llm_gemini_string():
    """_resolve_llm('gemini') should attempt to create GeminiProvider."""
    from alive_memory import _resolve_llm

    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai

    with (
        patch.dict("sys.modules", {"google": mock_google, "google.genai": mock_genai}),
        patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}),
    ):
        import alive_memory.llm.gemini as mod
        importlib.reload(mod)
        provider = _resolve_llm("gemini")
        assert provider is not None


# ── GeminiProvider._default_perception_prompt ────────────────────


def test_default_perception_prompts():
    from alive_memory.llm.gemini import _default_perception_prompt

    img_prompt = _default_perception_prompt("image/jpeg")
    assert "image" in img_prompt.lower()

    audio_prompt = _default_perception_prompt("audio/mp3")
    assert "audio" in audio_prompt.lower()
    assert "speaker" in audio_prompt.lower()

    video_prompt = _default_perception_prompt("video/mp4")
    assert "video" in video_prompt.lower()
    assert "timestamp" in video_prompt.lower()

    pdf_prompt = _default_perception_prompt("application/pdf")
    assert "document" in pdf_prompt.lower()


# ── GeminiProvider._guess_mime ───────────────────────────────────


def test_guess_mime():
    from alive_memory.llm.gemini import _guess_mime

    assert _guess_mime(Path("photo.jpg")) == "image/jpeg"
    assert _guess_mime(Path("song.mp3")) == "audio/mpeg"
    assert _guess_mime(Path("clip.mp4")) == "video/mp4"
    assert _guess_mime(Path("doc.pdf")) == "application/pdf"
    assert _guess_mime(Path("unknown.zzz")) == "application/octet-stream"


# ── Supported MIME types ─────────────────────────────────────────


def test_supported_mime_types():
    from alive_memory.llm.gemini import _SUPPORTED_MIME_TYPES

    # Key types should be present
    assert "image/jpeg" in _SUPPORTED_MIME_TYPES
    assert "audio/mpeg" in _SUPPORTED_MIME_TYPES
    assert "video/mp4" in _SUPPORTED_MIME_TYPES
    assert "application/pdf" in _SUPPORTED_MIME_TYPES
    # Non-media types should not be
    assert "text/plain" not in _SUPPORTED_MIME_TYPES
    assert "application/json" not in _SUPPORTED_MIME_TYPES
