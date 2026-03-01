"""Tests for memory_translator — numbers to feelings conversion."""

import re
from types import SimpleNamespace

from memory_translator import (
    mood_word, drive_level, energy_word,
    translate_mood, translate_drive, translate_energy,
    translate_drives_summary, translate_internal_conflict,
    scrub_numbers,
)


# ── Single-word helpers ──

class TestMoodWord:
    def test_high_valence_high_arousal(self):
        assert mood_word(0.7, 0.7) == 'energized'

    def test_high_valence_low_arousal(self):
        assert mood_word(0.7, 0.3) == 'content'

    def test_mid_valence_high_arousal(self):
        assert mood_word(0.3, 0.7) == 'curious'

    def test_mid_valence_low_arousal(self):
        assert mood_word(0.3, 0.3) == 'calm'

    def test_neutral_high_arousal(self):
        assert mood_word(0.0, 0.7) == 'restless'

    def test_neutral_low_arousal(self):
        assert mood_word(0.0, 0.3) == 'neutral'

    def test_negative_high_arousal(self):
        assert mood_word(-0.3, 0.7) == 'agitated'

    def test_negative_low_arousal(self):
        assert mood_word(-0.3, 0.3) == 'subdued'

    def test_very_negative_high_arousal(self):
        assert mood_word(-0.7, 0.7) == 'distressed'

    def test_very_negative_low_arousal(self):
        assert mood_word(-0.7, 0.3) == 'low'


class TestDriveLevel:
    def test_high(self):
        assert drive_level(0.9) == 'high'

    def test_moderate(self):
        assert drive_level(0.7) == 'moderate'

    def test_low(self):
        assert drive_level(0.4) == 'low'

    def test_quiet(self):
        assert drive_level(0.2) == 'quiet'


class TestEnergyWord:
    def test_full(self):
        assert energy_word(0.9) == 'full'

    def test_good(self):
        assert energy_word(0.7) == 'good'

    def test_moderate(self):
        assert energy_word(0.4) == 'moderate'

    def test_low(self):
        assert energy_word(0.2) == 'low'

    def test_depleted(self):
        assert energy_word(0.1) == 'depleted'


# ── Sentence generators ──

class TestTranslateMood:
    def test_returns_sentence(self):
        result = translate_mood(0.7, 0.7)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_content_mood(self):
        result = translate_mood(0.7, 0.3)
        assert 'content' in result.lower()

    def test_distressed_mood(self):
        result = translate_mood(-0.7, 0.7)
        assert 'wrong' in result.lower() or 'unease' in result.lower()


class TestTranslateDrive:
    def test_high_social_hunger(self):
        result = translate_drive('social_hunger', 0.85)
        assert 'longed' in result.lower() or 'talk' in result.lower()

    def test_quiet_curiosity(self):
        result = translate_drive('diversive_curiosity', 0.2)
        assert 'still' in result.lower()

    def test_unknown_drive_returns_empty(self):
        assert translate_drive('nonexistent_drive', 0.5) == ''


class TestTranslateEnergy:
    def test_depleted(self):
        result = translate_energy(0.1)
        assert 'fumes' in result.lower()

    def test_full(self):
        result = translate_energy(0.9)
        assert 'sharp' in result.lower() or 'ready' in result.lower()


class TestTranslateDrivesSummary:
    def _make_drives(self, **kwargs):
        defaults = {
            'mood_valence': 0.0,
            'mood_arousal': 0.5,
            'social_hunger': 0.5,
            'diversive_curiosity': 0.5,
            'expression_need': 0.5,
            'rest_need': 0.5,
            'energy': 0.5,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_returns_string(self):
        result = translate_drives_summary(self._make_drives())
        assert isinstance(result, str)
        assert len(result) > 0

    def test_no_numbers(self):
        drives = self._make_drives(
            mood_valence=-0.3,
            mood_arousal=0.8,
            social_hunger=0.9,
            rest_need=0.85,
            energy=0.1,
        )
        result = translate_drives_summary(drives)
        # No raw floats or percentages
        assert not re.search(r'\d+\.\d+', result)
        assert not re.search(r'\d+%', result)

    def test_high_hunger_mentioned(self):
        drives = self._make_drives(social_hunger=0.85)
        result = translate_drives_summary(drives)
        assert 'longed' in result.lower() or 'talk' in result.lower()

    def test_notable_drives_included(self):
        drives = self._make_drives(energy=0.1)
        result = translate_drives_summary(drives)
        assert 'fumes' in result.lower() or 'thin' in result.lower()


# ── Internal conflict translation ──

class TestTranslateInternalConflict:
    def test_empty_list_returns_empty(self):
        assert translate_internal_conflict([]) == ''

    def test_exclamation_conflict(self):
        result = translate_internal_conflict(['Used exclamation mark without being surprised'])
        assert 'felt off' in result.lower() or 'louder' in result.lower()

    def test_help_conflict(self):
        result = translate_internal_conflict(['Offered to help like an assistant'])
        assert 'helpful' in result.lower() or 'felt off' in result.lower()

    def test_unknown_conflict_generic(self):
        result = translate_internal_conflict(['Some completely novel conflict type'])
        assert 'felt off' in result.lower()

    def test_multiple_conflicts(self):
        result = translate_internal_conflict([
            'Used exclamation mark',
            'Offered to help',
            'Spoke with absolute certainty',
        ])
        assert 'few things felt off' in result.lower()

    def test_caps_at_three(self):
        result = translate_internal_conflict([
            'conflict 1', 'conflict 2', 'conflict 3', 'conflict 4', 'conflict 5',
        ])
        # Should not have more than 3 felt parts
        assert result.count(';') <= 2


# ── scrub_numbers ──

class TestScrubNumbers:
    def test_strips_floats(self):
        result = scrub_numbers('arousal was 0.84 today')
        assert '0.84' not in result

    def test_strips_percentages(self):
        result = scrub_numbers('valence only 22%')
        assert '22%' not in result

    def test_strips_pipeline_variables(self):
        result = scrub_numbers('salience 0.7 detected')
        assert '0.7' not in result

    def test_preserves_dates(self):
        result = scrub_numbers('On 2026-02-19 something happened')
        assert '2026-02-19' in result

    def test_preserves_times_in_headers(self):
        result = scrub_numbers('## 14:32\n\nSomething happened')
        assert '14:32' in result

    def test_empty_string(self):
        assert scrub_numbers('') == ''

    def test_none_returns_none(self):
        assert scrub_numbers(None) is None

    def test_no_double_spaces(self):
        result = scrub_numbers('the value was 0.84 and now it is gone')
        assert '  ' not in result

    def test_full_drives_summary_clean(self):
        """The translate_drives_summary output should already be clean,
        but scrub_numbers adds a second safety layer."""
        text = 'Emotional tension — arousal 84% but valence only 22%'
        result = scrub_numbers(text)
        assert not re.search(r'\d+%', result)
        assert not re.search(r'\d+\.\d+', result)
