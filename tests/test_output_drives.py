"""Tests for drive relief in pipeline/output.py (TASK-024)."""

import pytest

from pipeline.output import ACTION_DRIVE_EFFECTS
from pipeline.hypothalamus import clamp


class TestActionDriveEffects:
    """ACTION_DRIVE_EFFECTS dict coverage and correctness."""

    def test_speak_reduces_curiosity(self):
        effects = ACTION_DRIVE_EFFECTS.get('speak', {})
        assert effects.get('curiosity', 0) < 0

    def test_write_journal_reduces_curiosity(self):
        effects = ACTION_DRIVE_EFFECTS.get('write_journal', {})
        assert effects.get('curiosity', 0) < 0

    def test_end_engagement_reduces_rest_need(self):
        effects = ACTION_DRIVE_EFFECTS.get('end_engagement', {})
        assert effects.get('rest_need', 0) < 0
        assert effects.get('energy', 0) > 0

    def test_all_effects_bounded(self):
        """All delta values should be small adjustments, not extreme."""
        for action, effects in ACTION_DRIVE_EFFECTS.items():
            for field, delta in effects.items():
                assert -0.2 <= delta <= 0.2, (
                    f"Delta for {action}.{field} = {delta} seems too large"
                )

    def test_effects_apply_correctly(self):
        """Applying effects via clamp produces valid drive values."""
        for action, effects in ACTION_DRIVE_EFFECTS.items():
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
