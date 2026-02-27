"""Tests for TASK-095 v2: Capabilities toggle.

Verifies:
- actions_enabled=None allows all actions (Shopkeeper backward compat)
- actions_enabled=[] blocks all actions (digital lifeform default)
- actions_enabled=[...] filters to listed actions only
- Agent identity loads actions_enabled correctly from YAML
"""

import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config.agent_identity import AgentIdentity
from models.pipeline import Intention


class TestActionsEnabledIdentity(unittest.TestCase):
    """Test AgentIdentity actions_enabled field loading."""

    def test_actions_enabled_none_when_absent(self):
        """Identity YAML without actions_enabled → None (all allowed)."""
        yaml_content = """
identity_compact: "Test agent"
voice_rules:
  - "Be yourself"
voice_detection: {}
physical_traits_detection: []
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                identity = AgentIdentity.from_yaml(f.name)
                self.assertIsNone(identity.actions_enabled)
            finally:
                os.unlink(f.name)

    def test_actions_enabled_empty_when_empty_list(self):
        """Identity YAML with actions_enabled: [] → empty list (none allowed)."""
        yaml_content = """
identity_compact: "Test agent"
voice_rules:
  - "Be yourself"
voice_detection: {}
physical_traits_detection: []
actions_enabled: []
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                identity = AgentIdentity.from_yaml(f.name)
                self.assertEqual(identity.actions_enabled, [])
            finally:
                os.unlink(f.name)

    def test_actions_enabled_populated_list(self):
        """Identity YAML with actions_enabled: [items] → that list."""
        yaml_content = """
identity_compact: "Test agent"
voice_rules:
  - "Be yourself"
voice_detection: {}
physical_traits_detection: []
actions_enabled:
  - write_journal
  - browse_web
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                identity = AgentIdentity.from_yaml(f.name)
                self.assertEqual(identity.actions_enabled, ['write_journal', 'browse_web'])
            finally:
                os.unlink(f.name)

    def test_default_shopkeeper_has_explicit_actions(self):
        """Default Shopkeeper identity has an explicit actions_enabled list."""
        identity = AgentIdentity.default()
        # Shopkeeper YAML now has an explicit frozen action set
        self.assertIsNotNone(identity.actions_enabled)
        self.assertIsInstance(identity.actions_enabled, list)
        self.assertIn('idle', identity.actions_enabled)
        self.assertIn('speak', identity.actions_enabled)
        self.assertIn('write_journal', identity.actions_enabled)
        self.assertIn('rearrange', identity.actions_enabled)
        self.assertIn('close_shop', identity.actions_enabled)
        self.assertIn('tg_send', identity.actions_enabled)

    def test_digital_lifeform_blocks_all(self):
        """Digital lifeform identity should have actions_enabled=[]."""
        identity = AgentIdentity.digital_lifeform()
        self.assertEqual(identity.actions_enabled, [])


class TestCapabilitiesGate(unittest.IsolatedAsyncioTestCase):
    """Test basal ganglia Gate 2 with actions_enabled filtering."""

    def _make_identity(self, actions_enabled):
        """Helper to make a minimal identity mock."""
        identity = MagicMock()
        identity.actions_enabled = actions_enabled
        return identity

    def _make_context(self, identity):
        return {
            'visitor_present': False,
            'turn_count': 0,
            'mode': 'idle',
            'cycle_type': 'idle',
            'identity': identity,
        }

    @patch('pipeline.basal_ganglia.ACTION_REGISTRY')
    @patch('pipeline.basal_ganglia._resolve_dynamic_action')
    @patch('pipeline.basal_ganglia.check_prerequisites')
    @patch('pipeline.basal_ganglia._passes_shop_gate')
    @patch('pipeline.basal_ganglia.check_habits')
    @patch('pipeline.basal_ganglia.db')
    async def test_actions_enabled_none_allows_all(
        self, mock_db, mock_habits, mock_shop, mock_prereq, mock_resolve, mock_registry,
    ):
        """actions_enabled=None → all actions pass Gate 2."""
        from pipeline.basal_ganglia import select_actions
        from models.pipeline import ValidatedOutput

        identity = self._make_identity(None)
        context = self._make_context(identity)

        cap = MagicMock()
        cap.enabled = True
        cap.last_used = None
        cap.cooldown_seconds = 0
        cap.requires = []
        cap.energy_cost = 0.0
        cap.max_per_day = 999
        cap.max_per_cycle = 1
        mock_registry.__contains__ = MagicMock(return_value=True)
        mock_registry.__getitem__ = MagicMock(return_value=cap)
        mock_registry.get = MagicMock(return_value=cap)

        mock_prereq.return_value = MagicMock(passed=True)
        mock_shop.return_value = True
        mock_habits.return_value = ([], [])
        mock_db.get_executed_action_count_today = AsyncMock(return_value=0)

        validated = ValidatedOutput(
            intentions=[
                Intention(action='write_journal', content='Today was good',
                          target='journal', impulse=0.8),
            ],
        )

        drives = MagicMock()
        drives.energy = 0.8

        plan = await select_actions(validated, drives, context=context)
        # Should not be blocked by capabilities gate
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].status, 'approved')

    @patch('pipeline.basal_ganglia.ACTION_REGISTRY')
    @patch('pipeline.basal_ganglia._resolve_dynamic_action')
    @patch('pipeline.basal_ganglia.check_habits')
    @patch('pipeline.basal_ganglia.db')
    async def test_actions_enabled_empty_blocks_all(
        self, mock_db, mock_habits, mock_resolve, mock_registry,
    ):
        """actions_enabled=[] → all actions blocked at Gate 2."""
        from pipeline.basal_ganglia import select_actions
        from models.pipeline import ValidatedOutput

        identity = self._make_identity([])
        context = self._make_context(identity)

        cap = MagicMock()
        cap.enabled = True
        cap.last_used = None
        cap.cooldown_seconds = 0
        cap.requires = []
        cap.max_per_cycle = 1
        mock_registry.__contains__ = MagicMock(return_value=True)
        mock_registry.__getitem__ = MagicMock(return_value=cap)
        mock_registry.get = MagicMock(return_value=cap)

        mock_habits.return_value = ([], [])
        mock_db.get_executed_action_count_today = AsyncMock(return_value=0)

        validated = ValidatedOutput(
            intentions=[
                Intention(action='write_journal', content='Today was good',
                          target='journal', impulse=0.8),
            ],
        )

        drives = MagicMock()
        drives.energy = 0.8

        plan = await select_actions(validated, drives, context=context)
        # All should be blocked — incapable items go to suppressed list
        self.assertEqual(len(plan.actions), 0)
        self.assertEqual(len(plan.suppressed), 1)
        self.assertEqual(plan.suppressed[0].status, 'incapable')
        self.assertIn('Not enabled', plan.suppressed[0].suppression_reason)

    @patch('pipeline.basal_ganglia.ACTION_REGISTRY')
    @patch('pipeline.basal_ganglia._resolve_dynamic_action')
    @patch('pipeline.basal_ganglia.check_prerequisites')
    @patch('pipeline.basal_ganglia._passes_shop_gate')
    @patch('pipeline.basal_ganglia.check_habits')
    @patch('pipeline.basal_ganglia.db')
    async def test_actions_enabled_list_filters(
        self, mock_db, mock_habits, mock_shop, mock_prereq, mock_resolve, mock_registry,
    ):
        """actions_enabled=['speak','write_journal'] → only those pass."""
        from pipeline.basal_ganglia import select_actions
        from models.pipeline import ValidatedOutput

        identity = self._make_identity(['speak', 'write_journal'])
        context = self._make_context(identity)

        cap = MagicMock()
        cap.enabled = True
        cap.last_used = None
        cap.cooldown_seconds = 0
        cap.requires = []
        cap.energy_cost = 0.0
        cap.max_per_day = 999
        cap.max_per_cycle = 1
        mock_registry.__contains__ = MagicMock(return_value=True)
        mock_registry.__getitem__ = MagicMock(return_value=cap)
        mock_registry.get = MagicMock(return_value=cap)

        mock_prereq.return_value = MagicMock(passed=True)
        mock_shop.return_value = True
        mock_habits.return_value = ([], [])
        mock_db.get_executed_action_count_today = AsyncMock(return_value=0)

        validated = ValidatedOutput(
            intentions=[
                Intention(action='write_journal', content='Thoughts',
                          target='journal', impulse=0.8),
                Intention(action='browse_web', content='Search',
                          target='web', impulse=0.5),
            ],
        )

        drives = MagicMock()
        drives.energy = 0.8

        plan = await select_actions(validated, drives, context=context)

        # write_journal should pass (in actions), browse_web should be blocked (in suppressed)
        approved_names = [d.action for d in plan.actions]
        suppressed_statuses = {d.action: d.status for d in plan.suppressed}
        self.assertIn('write_journal', approved_names)
        self.assertEqual(suppressed_statuses.get('browse_web'), 'incapable')


class TestBackwardCompat(unittest.TestCase):
    """Ensure existing Shopkeeper identity continues to work."""

    def test_shopkeeper_identity_has_frozen_action_set(self):
        """Default identity.yaml (Shopkeeper) has explicit actions_enabled list."""
        identity = AgentIdentity.default()
        # Shopkeeper YAML now has an explicit frozen action set (19 actions)
        self.assertIsNotNone(identity.actions_enabled)
        self.assertEqual(len(identity.actions_enabled), 19)
        # Core actions present
        for action in ('idle', 'speak', 'write_journal', 'end_engagement',
                       'rearrange', 'close_shop', 'open_shop', 'browse_web'):
            self.assertIn(action, identity.actions_enabled)


if __name__ == '__main__':
    unittest.main()
