"""Tests for TASK-095 v2: Sleep whisper system.

Verifies:
- Whisper creation and pending state
- Whisper processing applies config changes
- Dream text generation from translation table
- Fallback template for unknown params
- No-op when empty
- Integration with sleep cycle ordering
"""

import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from sleep.whisper import (
    translate_whisper,
    process_whispers,
    apply_config_change,
    _humanize_param_path,
    _direction,
)


class TestTranslateWhisper(unittest.TestCase):
    """Test whisper → dream perception translation."""

    def test_translate_known_param_curiosity_increase(self):
        whisper = {
            'id': 1,
            'param_path': 'hypothalamus.equilibria.diversive_curiosity',
            'old_value': '0.4',
            'new_value': '0.7',
        }
        result = translate_whisper(whisper)
        self.assertIn('pull toward the unknown', result)
        self.assertIn('dig deeper', result)

    def test_translate_known_param_curiosity_decrease(self):
        whisper = {
            'id': 2,
            'param_path': 'hypothalamus.equilibria.diversive_curiosity',
            'old_value': '0.7',
            'new_value': '0.3',
        }
        result = translate_whisper(whisper)
        self.assertIn('softens', result)

    def test_translate_known_param_social_hunger(self):
        whisper = {
            'id': 3,
            'param_path': 'hypothalamus.equilibria.social_hunger',
            'old_value': '0.3',
            'new_value': '0.7',
        }
        result = translate_whisper(whisper)
        self.assertIn('longing for connection', result)

    def test_translate_known_param_formality(self):
        whisper = {
            'id': 4,
            'param_path': 'communication_style.formality',
            'old_value': '0.7',
            'new_value': '0.3',
        }
        result = translate_whisper(whisper)
        self.assertIn('looser', result)

    def test_translate_known_param_mood_valence(self):
        whisper = {
            'id': 5,
            'param_path': 'hypothalamus.equilibria.mood_valence',
            'old_value': '0.0',
            'new_value': '0.3',
        }
        result = translate_whisper(whisper)
        self.assertIn('warmer', result)

    def test_translate_fallback_unknown_param(self):
        whisper = {
            'id': 6,
            'param_path': 'some.unknown.parameter',
            'old_value': '1.0',
            'new_value': '2.0',
        }
        result = translate_whisper(whisper)
        self.assertIn('Something within you shifts', result)
        self.assertIn('1.0', result)
        self.assertIn('2.0', result)

    def test_translate_fallback_no_old_value(self):
        whisper = {
            'id': 7,
            'param_path': 'hypothalamus.equilibria.diversive_curiosity',
            'old_value': None,
            'new_value': '0.5',
        }
        result = translate_whisper(whisper)
        self.assertIn('shifts', result)

    def test_translate_all_known_params_produce_unique_text(self):
        """Each known param should produce unique (non-fallback) text."""
        known_params = [
            'hypothalamus.equilibria.diversive_curiosity',
            'hypothalamus.equilibria.social_hunger',
            'hypothalamus.equilibria.expression_need',
            'hypothalamus.equilibria.rest_need',
            'hypothalamus.equilibria.mood_valence',
            'hypothalamus.equilibria.mood_arousal',
            'communication_style.formality',
            'communication_style.verbosity',
            'sleep.morning.energy',
            'sleep.morning.social_hunger',
            'sleep.morning.curiosity',
        ]
        results = set()
        for param in known_params:
            whisper = {'id': 0, 'param_path': param, 'old_value': '0.3', 'new_value': '0.7'}
            text = translate_whisper(whisper)
            self.assertNotIn('Something within you shifts', text,
                             f"Known param {param} fell through to fallback")
            results.add(text)
        # All should be unique
        self.assertEqual(len(results), len(known_params))


class TestHumanizeParamPath(unittest.TestCase):
    def test_known_path(self):
        self.assertEqual(
            _humanize_param_path('hypothalamus.equilibria.diversive_curiosity'),
            'your sense of curiosity',
        )

    def test_unknown_path(self):
        result = _humanize_param_path('some.deeply.nested_param')
        self.assertEqual(result, 'nested param')


class TestDirection(unittest.TestCase):
    def test_increase(self):
        self.assertEqual(_direction('0.3', '0.7'), 'increase')

    def test_decrease(self):
        self.assertEqual(_direction('0.7', '0.3'), 'decrease')

    def test_non_numeric(self):
        self.assertEqual(_direction('foo', 'bar'), 'increase')


class TestProcessWhispers(unittest.IsolatedAsyncioTestCase):
    """Test whisper processing end-to-end."""

    @patch('sleep.whisper.db')
    async def test_process_whispers_noop_when_empty(self, mock_db):
        mock_db.get_pending_whispers = AsyncMock(return_value=[])
        result = await process_whispers()
        self.assertEqual(result, [])

    @patch('sleep.whisper.db')
    async def test_process_whispers_applies_config(self, mock_db):
        whispers = [{
            'id': 1,
            'param_path': 'hypothalamus.equilibria.diversive_curiosity',
            'old_value': '0.4',
            'new_value': '0.7',
            'created_at': '2026-01-01T00:00:00',
        }]
        mock_db.get_pending_whispers = AsyncMock(return_value=whispers)
        mock_db.set_param = AsyncMock()
        mock_db.mark_whisper_processed = AsyncMock()

        result = await process_whispers()

        self.assertEqual(len(result), 1)
        self.assertIn('pull toward the unknown', result[0])

        # Verify config was applied
        mock_db.set_param.assert_called_once_with(
            key='hypothalamus.equilibria.diversive_curiosity',
            value=0.7,
            modified_by='manager_whisper',
            reason='Sleep whisper integration (whisper #1)',
        )

        # Verify marked as processed
        mock_db.mark_whisper_processed.assert_called_once()
        call_args = mock_db.mark_whisper_processed.call_args
        self.assertEqual(call_args[0][0], 1)  # whisper_id
        self.assertIn('pull toward the unknown', call_args[0][1])  # dream_text

    @patch('sleep.whisper.db')
    async def test_process_whispers_generates_dream_text(self, mock_db):
        whispers = [{
            'id': 2,
            'param_path': 'communication_style.verbosity',
            'old_value': '0.3',
            'new_value': '0.7',
            'created_at': '2026-01-01T00:00:00',
        }]
        mock_db.get_pending_whispers = AsyncMock(return_value=whispers)
        mock_db.set_param = AsyncMock()
        mock_db.mark_whisper_processed = AsyncMock()

        result = await process_whispers()
        self.assertEqual(len(result), 1)
        # Dream text should be stored
        dream_text = mock_db.mark_whisper_processed.call_args[0][1]
        self.assertTrue(len(dream_text) > 10)

    @patch('sleep.whisper.db')
    async def test_process_whispers_handles_failed_apply(self, mock_db):
        """If set_param fails, whisper is still marked processed."""
        whispers = [{
            'id': 3,
            'param_path': 'nonexistent.param',
            'old_value': '0.0',
            'new_value': '1.0',
            'created_at': '2026-01-01T00:00:00',
        }]
        mock_db.get_pending_whispers = AsyncMock(return_value=whispers)
        mock_db.set_param = AsyncMock(side_effect=ValueError("Unknown parameter"))
        mock_db.mark_whisper_processed = AsyncMock()

        result = await process_whispers()
        self.assertEqual(len(result), 1)
        # Still marked processed despite apply failure
        mock_db.mark_whisper_processed.assert_called_once()


class TestApplyConfigChange(unittest.IsolatedAsyncioTestCase):
    @patch('sleep.whisper.db')
    async def test_apply_calls_set_param(self, mock_db):
        mock_db.set_param = AsyncMock()
        whisper = {
            'id': 1,
            'param_path': 'hypothalamus.equilibria.social_hunger',
            'new_value': '0.8',
        }
        await apply_config_change(whisper)
        mock_db.set_param.assert_called_once_with(
            key='hypothalamus.equilibria.social_hunger',
            value=0.8,
            modified_by='manager_whisper',
            reason='Sleep whisper integration (whisper #1)',
        )

    @patch('sleep.whisper.db')
    async def test_apply_catches_value_error(self, mock_db):
        mock_db.set_param = AsyncMock(side_effect=ValueError("below min"))
        whisper = {'id': 2, 'param_path': 'bad.param', 'new_value': '-999'}
        # Should not raise
        await apply_config_change(whisper)


if __name__ == '__main__':
    unittest.main()
