"""Unit tests for the enhanced whisper module."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from alive_memory.consolidation.whisper import (
    WHISPER_TEMPLATES,
    _direction,
    _humanize_param_path,
    process_whispers,
    register_whisper,
    translate_whisper,
)

# ---------------------------------------------------------------------------
# _direction helper
# ---------------------------------------------------------------------------

def test_direction_increase():
    assert _direction(0.3, 0.7) == "increase"


def test_direction_decrease():
    assert _direction(0.7, 0.3) == "decrease"


def test_direction_stable():
    assert _direction(0.5, 0.5) == "stable"


# ---------------------------------------------------------------------------
# _humanize_param_path
# ---------------------------------------------------------------------------

def test_humanize_param_path_default():
    assert _humanize_param_path("hypothalamus.equilibria.curiosity") == "curiosity"
    assert _humanize_param_path("communication_style.formality") == "formality"
    assert _humanize_param_path("sleep.morning.energy") == "morning energy"


def test_humanize_param_path_fallback():
    result = _humanize_param_path("some.custom.param_name")
    assert result == "param name"


def test_humanize_param_path_override():
    overrides = {"my.custom.path": "custom label"}
    assert _humanize_param_path("my.custom.path", overrides=overrides) == "custom label"
    # Built-in still works when not overridden
    assert _humanize_param_path("hypothalamus.equilibria.curiosity", overrides=overrides) == "curiosity"


# ---------------------------------------------------------------------------
# Built-in whisper templates — curiosity
# ---------------------------------------------------------------------------

def test_translate_whisper_curiosity_increase():
    result = translate_whisper("drives.curiosity", 0.3, 0.7)
    assert "stir" in result.lower()
    assert "wonder" in result.lower()


def test_translate_whisper_curiosity_decrease():
    result = translate_whisper("drives.curiosity", 0.7, 0.3)
    assert "settled" in result.lower() or "fades" in result.lower()


# ---------------------------------------------------------------------------
# social
# ---------------------------------------------------------------------------

def test_translate_whisper_social_increase():
    result = translate_whisper("drives.social_hunger", 0.3, 0.7)
    assert "silence" in result.lower() or "company" in result.lower()


def test_translate_whisper_social_decrease():
    result = translate_whisper("drives.social", 0.7, 0.3)
    assert "solitude" in result.lower() or "softens" in result.lower()


# ---------------------------------------------------------------------------
# expression
# ---------------------------------------------------------------------------

def test_translate_whisper_expression_increase():
    result = translate_whisper("drives.expression", 0.3, 0.7)
    assert "words" in result.lower() or "building" in result.lower()


def test_translate_whisper_expression_decrease():
    result = translate_whisper("drives.expression", 0.7, 0.3)
    assert "quiet" in result.lower() or "eases" in result.lower()


# ---------------------------------------------------------------------------
# valence
# ---------------------------------------------------------------------------

def test_translate_whisper_valence_increase():
    result = translate_whisper("mood.valence", 0.3, 0.7)
    assert "warmth" in result.lower() or "brighter" in result.lower()


def test_translate_whisper_valence_decrease():
    result = translate_whisper("mood.valence", 0.7, 0.3)
    assert "weight" in result.lower() or "dims" in result.lower()


# ---------------------------------------------------------------------------
# arousal
# ---------------------------------------------------------------------------

def test_translate_whisper_arousal_increase():
    result = translate_whisper("mood.arousal", 0.3, 0.7)
    assert "sharpens" in result.lower() or "senses" in result.lower()


def test_translate_whisper_arousal_decrease():
    result = translate_whisper("mood.arousal", 0.7, 0.3)
    assert "softens" in result.lower() or "drowsiness" in result.lower()


# ---------------------------------------------------------------------------
# energy
# ---------------------------------------------------------------------------

def test_translate_whisper_energy_increase():
    result = translate_whisper("sleep.morning.energy", 0.3, 0.7)
    assert "capable" in result.lower() or "fuel" in result.lower()


def test_translate_whisper_energy_decrease():
    result = translate_whisper("sleep.morning.energy", 0.7, 0.3)
    assert "tiredness" in result.lower() or "selective" in result.lower()


# ---------------------------------------------------------------------------
# formality (NEW)
# ---------------------------------------------------------------------------

def test_translate_whisper_formality_increase():
    result = translate_whisper("communication_style.formality", 0.3, 0.7)
    assert "precision" in result.lower() or "measured" in result.lower()


def test_translate_whisper_formality_decrease():
    result = translate_whisper("communication_style.formality", 0.7, 0.3)
    assert "loosens" in result.lower() or "easier" in result.lower()


# ---------------------------------------------------------------------------
# verbosity (NEW)
# ---------------------------------------------------------------------------

def test_translate_whisper_verbosity_increase():
    result = translate_whisper("communication_style.verbosity", 0.3, 0.7)
    assert "expand" in result.lower() or "detail" in result.lower()


def test_translate_whisper_verbosity_decrease():
    result = translate_whisper("communication_style.verbosity", 0.7, 0.3)
    assert "brevity" in result.lower() or "fewer" in result.lower()


# ---------------------------------------------------------------------------
# social_readiness (NEW)
# ---------------------------------------------------------------------------

def test_translate_whisper_social_readiness_increase():
    result = translate_whisper("sleep.morning.social_readiness", 0.3, 0.7)
    assert "ready" in result.lower() or "faces" in result.lower()


def test_translate_whisper_social_readiness_decrease():
    result = translate_whisper("sleep.morning.social_readiness", 0.7, 0.3)
    assert "quieter" in result.lower() or "alone" in result.lower()


# ---------------------------------------------------------------------------
# morning_curiosity (NEW)
# ---------------------------------------------------------------------------

def test_translate_whisper_morning_curiosity_increase():
    result = translate_whisper("sleep.morning.curiosity", 0.3, 0.7)
    assert "dawn" in result.lower() or "questions" in result.lower()


def test_translate_whisper_morning_curiosity_decrease():
    result = translate_whisper("sleep.morning.curiosity", 0.7, 0.3)
    assert "still" in result.lower() or "familiar" in result.lower()


# ---------------------------------------------------------------------------
# Longest match first — morning.curiosity beats curiosity
# ---------------------------------------------------------------------------

def test_longest_match_first():
    """'morning.curiosity' (18 chars) should match before 'curiosity' (9 chars)
    for the path 'sleep.morning.curiosity'."""
    result = translate_whisper("sleep.morning.curiosity", 0.3, 0.7)
    # Should get the morning_curiosity template (has "dawn"), not generic curiosity ("stirs")
    assert "dawn" in result.lower() or "questions" in result.lower()
    assert "stir" not in result.lower()


# ---------------------------------------------------------------------------
# Unknown / fallback
# ---------------------------------------------------------------------------

def test_translate_whisper_unknown_fallback():
    result = translate_whisper("some.unknown.param", 0.3, 0.7)
    assert "shifts" in result.lower()
    assert "param" in result.lower()


def test_translate_whisper_unknown_fallback_decrease():
    result = translate_whisper("some.unknown.param", 0.7, 0.3)
    assert "shifts" in result.lower()
    assert "fades" in result.lower()


# ---------------------------------------------------------------------------
# Custom registration
# ---------------------------------------------------------------------------

def test_register_whisper_custom(monkeypatch):
    """Register a new custom template; verify it's used."""
    saved = dict(WHISPER_TEMPLATES)
    try:
        def _custom(old: float, new: float) -> str:
            return "custom dream"

        register_whisper("custom_drive", _custom)
        result = translate_whisper("my.custom_drive.x", 0.3, 0.7)
        assert result == "custom dream"
    finally:
        WHISPER_TEMPLATES.clear()
        WHISPER_TEMPLATES.update(saved)


def test_register_whisper_override(monkeypatch):
    """Override a built-in template; verify override wins."""
    saved = dict(WHISPER_TEMPLATES)
    try:
        def _override(old: float, new: float) -> str:
            return "overridden"

        register_whisper("curiosity", _override)
        result = translate_whisper("drives.curiosity", 0.3, 0.7)
        assert result == "overridden"
    finally:
        WHISPER_TEMPLATES.clear()
        WHISPER_TEMPLATES.update(saved)


# ---------------------------------------------------------------------------
# process_whispers integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_whispers_integration():
    """Async test calling process_whispers() with mock storage."""
    mock_storage = AsyncMock()

    whispers = [
        {"param_path": "drives.curiosity", "old_value": 0.3, "new_value": 0.7},
        {"param_path": "mood.valence", "old_value": 0.5, "new_value": 0.2},
    ]
    dreams = await process_whispers(whispers, mock_storage)

    assert len(dreams) == 2
    assert "stir" in dreams[0].lower() or "wonder" in dreams[0].lower()
    assert "weight" in dreams[1].lower() or "dims" in dreams[1].lower()
    assert mock_storage.set_parameter.call_count == 2
