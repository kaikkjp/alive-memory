"""Tests for sleep.review_self_modifications() — TASK-056 Phase 4."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sleep
from models.state import DrivesState


class ReviewSelfModificationsTests(unittest.IsolatedAsyncioTestCase):
    """Unit tests for review_self_modifications()."""

    def _drives(self, **overrides) -> DrivesState:
        """Return a DrivesState with sensible defaults, overrideable per field."""
        defaults = dict(
            social_hunger=0.5,
            curiosity=0.5,
            expression_need=0.5,
            rest_need=0.5,
            energy=0.8,
            mood_valence=0.0,
            mood_arousal=0.3,
        )
        defaults.update(overrides)
        return DrivesState(**defaults)

    def _mod(self, param_key: str, new_value: float = 0.7) -> dict:
        """Return a minimal parameter_modifications row dict."""
        return {
            'id': 1,
            'param_key': param_key,
            'old_value': 0.5,
            'new_value': new_value,
            'modified_by': 'self',
            'reason': 'test',
            'ts': '2026-02-18T10:00:00',
        }

    async def test_no_mods_no_revert(self):
        """When get_todays_self_modifications returns [], reset_param must NOT be called."""
        with patch('sleep.db.get_drives_state', new=AsyncMock(return_value=self._drives())):
            with patch(
                'db.parameters.get_todays_self_modifications',
                new=AsyncMock(return_value=[]),
            ):
                with patch('db.parameters.reset_param', new=AsyncMock()) as mock_reset:
                    # Import inside the patch context so the function body resolves correctly
                    await sleep.review_self_modifications()
                    mock_reset.assert_not_awaited()

    async def test_degraded_drive_reverts_param(self):
        """When a governed drive deviates > 0.4 from equilibrium, reset_param IS called."""
        # social_hunger equilibrium defaults to 0.5 via p_or fallback.
        # Set social_hunger to 0.95 → deviation = 0.45 > 0.4 → should revert.
        drives = self._drives(social_hunger=0.95)
        mod = self._mod('sensorium.some_param')

        with patch('sleep.db.get_drives_state', new=AsyncMock(return_value=drives)):
            with patch(
                'db.parameters.get_todays_self_modifications',
                new=AsyncMock(return_value=[mod]),
            ):
                # p_or returns 0.5 for any key (equilibrium default)
                with patch('db.parameters.p_or', return_value=0.5):
                    with patch('db.parameters.reset_param', new=AsyncMock()) as mock_reset:
                        await sleep.review_self_modifications()
                        mock_reset.assert_awaited_once_with(
                            'sensorium.some_param', modified_by='meta_sleep_revert'
                        )

    async def test_healthy_drive_keeps_param(self):
        """When all governed drives are within 0.4 of equilibrium, reset_param is NOT called."""
        # social_hunger at 0.6, equilibrium 0.5 → deviation 0.1 < 0.4 → keep.
        drives = self._drives(social_hunger=0.6)
        mod = self._mod('sensorium.some_param')

        with patch('sleep.db.get_drives_state', new=AsyncMock(return_value=drives)):
            with patch(
                'db.parameters.get_todays_self_modifications',
                new=AsyncMock(return_value=[mod]),
            ):
                with patch('db.parameters.p_or', return_value=0.5):
                    with patch('db.parameters.reset_param', new=AsyncMock()) as mock_reset:
                        await sleep.review_self_modifications()
                        mock_reset.assert_not_awaited()

    async def test_reset_exception_is_swallowed(self):
        """If reset_param raises, the exception must be caught and not propagate."""
        drives = self._drives(social_hunger=0.95)
        mod = self._mod('sensorium.some_param')

        with patch('sleep.db.get_drives_state', new=AsyncMock(return_value=drives)):
            with patch(
                'db.parameters.get_todays_self_modifications',
                new=AsyncMock(return_value=[mod]),
            ):
                with patch('db.parameters.p_or', return_value=0.5):
                    with patch(
                        'db.parameters.reset_param',
                        new=AsyncMock(side_effect=ValueError("unknown param")),
                    ):
                        # Should not raise
                        await sleep.review_self_modifications()

    async def test_multiple_mods_independent_evaluation(self):
        """Each modification is evaluated independently."""
        # hypothalamus param governs mood_valence among others.
        # mood_valence deviation = |0.9 - 0.5| = 0.4 — NOT > 0.4, so should keep.
        # curiosity deviation = |0.95 - 0.5| = 0.45 > 0.4, so hypothalamus param reverted.
        drives = self._drives(mood_valence=0.9, curiosity=0.95)
        mods = [
            self._mod('hypothalamus.equilibria.social_hunger'),
            self._mod('thalamus.gate_bias'),
        ]

        with patch('sleep.db.get_drives_state', new=AsyncMock(return_value=drives)):
            with patch(
                'db.parameters.get_todays_self_modifications',
                new=AsyncMock(return_value=mods),
            ):
                with patch('db.parameters.p_or', return_value=0.5):
                    with patch('db.parameters.reset_param', new=AsyncMock()) as mock_reset:
                        await sleep.review_self_modifications()
                        # hypothalamus governs curiosity (0.45 > 0.4) → revert
                        # thalamus governs curiosity (0.45 > 0.4) → revert
                        self.assertEqual(mock_reset.await_count, 2)

    async def test_unknown_category_skips_gracefully(self):
        """Param with category not in _CATEGORY_DRIVE_MAP is kept (no governed drives)."""
        drives = self._drives()
        mod = self._mod('unknown_category.some_param')

        with patch('sleep.db.get_drives_state', new=AsyncMock(return_value=drives)):
            with patch(
                'db.parameters.get_todays_self_modifications',
                new=AsyncMock(return_value=[mod]),
            ):
                with patch('db.parameters.reset_param', new=AsyncMock()) as mock_reset:
                    await sleep.review_self_modifications()
                    mock_reset.assert_not_awaited()
