"""Tests for drive relief in pipeline/output.py (TASK-024)."""

import pytest

from pipeline.output import _build_action_drive_effects
from pipeline.hypothalamus import clamp


class TestActionDriveEffects:
    """_build_action_drive_effects() dict coverage and correctness."""

    def test_speak_no_curiosity_drain(self):
        """TASK-044: Curiosity is stimulus-driven, not action-drained."""
        effects = _build_action_drive_effects().get('speak', {})
        assert 'curiosity' not in effects

    def test_write_journal_no_curiosity_drain(self):
        """TASK-044: Curiosity is stimulus-driven, not action-drained."""
        effects = _build_action_drive_effects().get('write_journal', {})
        assert 'curiosity' not in effects

    def test_end_engagement_reduces_rest_need(self):
        effects = _build_action_drive_effects().get('end_engagement', {})
        assert effects.get('rest_need', 0) < 0
        # TASK-050: energy is display-only, no longer adjusted by actions

    def test_all_effects_bounded(self):
        """All delta values should be small adjustments, not extreme."""
        for action, effects in _build_action_drive_effects().items():
            for field, delta in effects.items():
                assert -0.2 <= delta <= 0.2, (
                    f"Delta for {action}.{field} = {delta} seems too large"
                )

    def test_effects_apply_correctly(self):
        """Applying effects via clamp produces valid drive values."""
        for action, effects in _build_action_drive_effects().items():
            for field, delta in effects.items():
                # From midpoint
                result = clamp(0.5 + delta)
                assert 0.0 <= result <= 1.0
                # From extreme (test no overshoot)
                if delta < 0:
                    result = clamp(0.0 + delta)
                    assert result == 0.0
                else:
                    result = clamp(1.0 + delta)
                    assert result == 1.0
