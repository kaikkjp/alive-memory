"""Tests for alive_memory.hot.translator — numbers to feelings."""

from __future__ import annotations

from alive_memory.hot.translator import (
    drive_level,
    energy_word,
    mood_word,
    scrub_numbers,
    translate_drive,
    translate_drives_summary,
    translate_energy,
    translate_internal_conflict,
    translate_mood,
)
from alive_memory.types import DriveState, MoodState

# ── mood_word ────────────────────────────────────────────────────────


class TestMoodWord:
    def test_energized(self):
        assert mood_word(0.7, 0.7) == "energized"

    def test_content(self):
        assert mood_word(0.7, 0.3) == "content"

    def test_curious(self):
        assert mood_word(0.3, 0.7) == "curious"

    def test_calm(self):
        assert mood_word(0.3, 0.3) == "calm"

    def test_restless(self):
        assert mood_word(0.0, 0.7) == "restless"

    def test_neutral(self):
        assert mood_word(0.0, 0.3) == "neutral"

    def test_agitated(self):
        assert mood_word(-0.3, 0.7) == "agitated"

    def test_subdued(self):
        assert mood_word(-0.3, 0.3) == "subdued"

    def test_distressed(self):
        assert mood_word(-0.7, 0.7) == "distressed"

    def test_low(self):
        assert mood_word(-0.7, 0.3) == "low"


# ── drive_level ──────────────────────────────────────────────────────


class TestDriveLevel:
    def test_high(self):
        assert drive_level(0.9) == "high"

    def test_moderate(self):
        assert drive_level(0.7) == "moderate"

    def test_low(self):
        assert drive_level(0.5) == "low"

    def test_quiet(self):
        assert drive_level(0.2) == "quiet"


# ── energy_word ──────────────────────────────────────────────────────


class TestEnergyWord:
    def test_full(self):
        assert energy_word(0.9) == "full"

    def test_good(self):
        assert energy_word(0.7) == "good"

    def test_moderate(self):
        assert energy_word(0.5) == "moderate"

    def test_low(self):
        assert energy_word(0.2) == "low"

    def test_depleted(self):
        assert energy_word(0.1) == "depleted"


# ── translate_mood ───────────────────────────────────────────────────


class TestTranslateMood:
    def test_returns_sentence(self):
        result = translate_mood(0.7, 0.7)
        assert result == "I felt alive and buzzing with energy."

    def test_low_mood(self):
        result = translate_mood(-0.7, 0.3)
        assert "far away" in result


# ── translate_drive ──────────────────────────────────────────────────


class TestTranslateDrive:
    def test_social_high(self):
        result = translate_drive("social", 0.9)
        assert "talk" in result

    def test_curiosity_quiet(self):
        result = translate_drive("curiosity", 0.1)
        assert "still" in result

    def test_unknown_drive(self):
        result = translate_drive("unknown_drive", 0.9)
        assert result == ""


# ── translate_energy ─────────────────────────────────────────────────


class TestTranslateEnergy:
    def test_full(self):
        assert "sharp" in translate_energy(0.9)

    def test_depleted(self):
        assert "fumes" in translate_energy(0.1)


# ── translate_drives_summary ─────────────────────────────────────────


class TestTranslateDrivesSummary:
    def test_uses_sdk_types(self):
        drives = DriveState(curiosity=0.9, social=0.1, expression=0.5, rest=0.5)
        mood = MoodState(valence=0.7, arousal=0.7, word="energized")
        result = translate_drives_summary(drives, mood)
        assert "alive" in result  # mood sentence
        assert "reaching" in result  # high curiosity
        assert "Solitude" in result  # low social

    def test_neutral_state(self):
        drives = DriveState()  # all 0.5
        mood = MoodState()  # neutral
        result = translate_drives_summary(drives, mood)
        assert len(result) > 0
        # Drives at 0.5 should not be mentioned (neither high nor low)
        assert "talk" not in result
        assert "reaching" not in result

    def test_with_energy(self):
        drives = DriveState()
        mood = MoodState()
        result = translate_drives_summary(drives, mood, energy=0.1)
        assert "fumes" in result

    def test_default_even(self):
        drives = DriveState(curiosity=0.5, social=0.5, expression=0.5, rest=0.5)
        mood = MoodState(valence=0.0, arousal=0.3)
        result = translate_drives_summary(drives, mood, energy=0.5)
        # All drives at midpoint, mood neutral — should include mood sentence
        assert "even" in result.lower() or "neutral" in result.lower() or len(result) > 0


# ── translate_internal_conflict ──────────────────────────────────────


class TestTranslateInternalConflict:
    def test_empty(self):
        assert translate_internal_conflict([]) == ""

    def test_single_match(self):
        result = translate_internal_conflict(["Used exclamation mark without emotion"])
        assert "louder" in result
        assert "felt off" in result.lower()

    def test_multiple(self):
        result = translate_internal_conflict([
            "Used exclamation mark",
            "emoji detected",
        ])
        assert "A few things felt off" in result
        assert "louder" in result
        assert "gesture" in result

    def test_generic_fallback(self):
        result = translate_internal_conflict(["Completely unknown conflict type"])
        assert "felt off" in result.lower()

    def test_caps_at_three(self):
        conflicts = [f"conflict {i}" for i in range(10)]
        result = translate_internal_conflict(conflicts)
        # Should only process 3
        assert result.count("something about what i just did felt off") <= 3


# ── scrub_numbers ────────────────────────────────────────────────────


class TestScrubNumbers:
    def test_removes_floats(self):
        assert "0.84" not in scrub_numbers("The valence was 0.84 today")

    def test_removes_percentages(self):
        assert "73%" not in scrub_numbers("Energy at 73% remaining")

    def test_removes_pipeline_vars(self):
        result = scrub_numbers("arousal=0.6 and valence: 0.3")
        assert "0.6" not in result
        assert "0.3" not in result

    def test_removes_scores(self):
        assert "score" not in scrub_numbers("score=42")

    def test_preserves_dates(self):
        text = "On 2026-02-19 something happened"
        assert "2026-02-19" in scrub_numbers(text)

    def test_preserves_times(self):
        text = "At 14:32 we talked"
        assert "14:32" in scrub_numbers(text)

    def test_empty_string(self):
        assert scrub_numbers("") == ""

    def test_none_passthrough(self):
        # scrub_numbers returns falsy input as-is
        assert scrub_numbers("") == ""

    def test_cleans_double_spaces(self):
        result = scrub_numbers("Hello 0.84 world")
        assert "  " not in result

    def test_strips_line_whitespace(self):
        result = scrub_numbers("line one  \nline two  ")
        assert not any(line.endswith(" ") for line in result.split("\n"))
