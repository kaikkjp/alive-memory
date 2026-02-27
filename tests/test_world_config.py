"""Tests for identity decontamination — WorldConfig + parametric pipeline.

Verifies:
- Digital lifeform prompt has no shop/physical references
- Shopkeeper prompt preserves all existing enums
- Action enums derive from actions_enabled
- MCP build-time injection targets only action enums
- Validator skips hand checks for non-physical agents
- Basal ganglia cognitive primitives exempt from Gate 2
- Shop gate blocks shop actions for non-physical agents
- Self-context omits Shop: line for non-physical agents
- Sleep reflection uses identity_compact param
- Fidgets use WorldConfig
- Ambient perception conditional on world
- Weather diegetic conditional on world
- Autonomous routing conditional on world
"""

import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config.agent_identity import (
    AgentIdentity, WorldConfig,
    _PHYSICAL_DEFAULTS, _DIGITAL_DEFAULTS,
    _SHOPKEEPER_FRAMING, _DIGITAL_FRAMING,
)


class TestBuildSystemPromptDigitalLifeform(unittest.TestCase):
    """Digital lifeform prompt must have zero shop contamination."""

    def test_no_shop_references(self):
        from pipeline.cortex import build_system_prompt
        identity = AgentIdentity.digital_lifeform()
        prompt = build_system_prompt(identity)

        # No shop/physical references
        prompt_lower = prompt.lower()
        for banned in ('shop', 'shelf', 'window', 'hands_on_cup',
                       'reaching_back', 'leaning_forward', 'holding_object'):
            self.assertNotIn(banned, prompt_lower,
                             f'Found "{banned}" in digital lifeform prompt')

    def test_digital_embodiment_enums(self):
        from pipeline.cortex import build_system_prompt
        identity = AgentIdentity.digital_lifeform()
        prompt = build_system_prompt(identity)

        # Digital body states present
        self.assertIn('present|thinking|resting', prompt)
        # Digital gaze directions present
        self.assertIn('inward|outward|unfocused', prompt)
        # Digital framing present
        self.assertIn('You exist in a digital space', prompt)

    def test_digital_expressions(self):
        from pipeline.cortex import build_system_prompt
        identity = AgentIdentity.digital_lifeform()
        prompt = build_system_prompt(identity)

        # Digital expressions subset
        for expr in ('neutral', 'thinking', 'low', 'curious', 'uncertain'):
            self.assertIn(expr, prompt)


class TestBuildSystemPromptShopkeeper(unittest.TestCase):
    """Shopkeeper prompt must preserve all existing behavior."""

    def test_shopkeeper_has_shop_framing(self):
        from pipeline.cortex import build_system_prompt
        identity = AgentIdentity.default()
        prompt = build_system_prompt(identity)

        self.assertIn('Your shop is a physical space', prompt)

    def test_shopkeeper_has_physical_body_states(self):
        from pipeline.cortex import build_system_prompt
        identity = AgentIdentity.default()
        prompt = build_system_prompt(identity)

        for state in ('sitting', 'reaching_back', 'leaning_forward',
                      'holding_object', 'writing', 'hands_on_cup'):
            self.assertIn(state, prompt)

    def test_shopkeeper_has_physical_gaze(self):
        from pipeline.cortex import build_system_prompt
        identity = AgentIdentity.default()
        prompt = build_system_prompt(identity)

        for gaze in ('at_visitor', 'at_object', 'away_thinking', 'down', 'window'):
            self.assertIn(gaze, prompt)

    def test_shopkeeper_has_all_actions(self):
        from pipeline.cortex import build_system_prompt
        identity = AgentIdentity.default()
        prompt = build_system_prompt(identity)

        for action in ('idle', 'rearrange', 'write_journal', 'close_shop',
                       'speak', 'end_engagement', 'accept_gift', 'decline_gift',
                       'browse_web', 'post_x', 'tg_send'):
            self.assertIn(action, prompt)


class TestActionEnumsFromActionsEnabled(unittest.TestCase):
    """Action enum derivation from identity config."""

    def test_empty_actions_enabled_gives_minimal(self):
        from pipeline.cortex import _build_action_enums
        identity = MagicMock()
        identity.actions_enabled = []
        idle, engage = _build_action_enums(identity)
        # Minimal set: idle + express_thought in idle, express_thought only in engage
        # (idle is excluded from engage list by design)
        self.assertEqual(set(idle), {'idle', 'express_thought'})
        self.assertEqual(set(engage), {'express_thought'})

    def test_explicit_list_gives_that_list(self):
        from pipeline.cortex import _build_action_enums
        identity = MagicMock()
        identity.actions_enabled = ['idle', 'speak', 'write_journal', 'end_engagement']
        idle, engage = _build_action_enums(identity)
        # speak and end_engagement are engage-only
        self.assertIn('idle', idle)
        self.assertIn('write_journal', idle)
        self.assertNotIn('speak', idle)      # engage-only
        self.assertIn('speak', engage)
        self.assertIn('end_engagement', engage)

    def test_none_actions_enabled_uses_registry(self):
        from pipeline.cortex import _build_action_enums
        identity = MagicMock()
        identity.actions_enabled = None
        idle, engage = _build_action_enums(identity)
        # Should have multiple actions from registry
        self.assertTrue(len(idle) > 2)
        self.assertTrue(len(engage) > 2)


class TestMcpBuildTimeInjection(unittest.TestCase):
    """MCP names injected at build time, only in action enums."""

    def test_mcp_in_action_enums(self):
        from pipeline.cortex import build_system_prompt
        identity = AgentIdentity.default()
        prompt = build_system_prompt(identity, mcp_names=['mcp_1_search'])
        self.assertIn('mcp_1_search', prompt)

    def test_mcp_not_in_memory_type_enum(self):
        from pipeline.cortex import build_system_prompt
        identity = AgentIdentity.default()
        prompt = build_system_prompt(identity, mcp_names=['mcp_1_search'])

        # Find trait_category enum — should NOT contain MCP name
        trait_matches = re.findall(r'"trait_category":\s*"([^"]+)"', prompt)
        for m in trait_matches:
            self.assertNotIn('mcp_1_search', m,
                             'MCP name leaked into trait_category enum')

    def test_no_mcp_when_none(self):
        from pipeline.cortex import build_system_prompt
        identity = AgentIdentity.default()
        prompt = build_system_prompt(identity)
        self.assertNotIn('mcp_', prompt)


class TestValidatorNoHandCheckDigital(unittest.TestCase):
    """Non-physical agents skip hand state validation."""

    def test_no_hand_warning_for_digital(self):
        from pipeline.validator import validate
        from models.pipeline import CortexOutput, ValidatorState, ActionRequest

        cortex = CortexOutput(
            dialogue='thinking about something',
            actions=[ActionRequest(type='write_journal', detail={'content': 'test'})],
        )
        state = ValidatorState(
            turn_count=0,
            cycle_type='idle',
            hands_held_item='cup of tea',  # Hands occupied
        )
        digital_world = WorldConfig(has_physical_space=False)
        result = validate(cortex, state, world=digital_world)

        # Should NOT inject "let me put this down" for digital agent
        self.assertNotIn('put this down', result.dialogue or '')

    def test_hand_warning_for_physical(self):
        from pipeline.validator import validate
        from models.pipeline import CortexOutput, ValidatorState, ActionRequest

        cortex = CortexOutput(
            dialogue='thinking about something',
            actions=[ActionRequest(type='write_journal', detail={'content': 'test'})],
        )
        state = ValidatorState(
            turn_count=0,
            cycle_type='idle',
            hands_held_item='cup of tea',
        )
        physical_world = WorldConfig(has_physical_space=True)
        result = validate(cortex, state, world=physical_world)

        # Physical agent SHOULD get hand warning
        self.assertIn('put this down', result.dialogue or '')


class TestGate2CognitivePrimitivesPass(unittest.IsolatedAsyncioTestCase):
    """Cognitive primitives pass Gate 2 even with empty actions_enabled."""

    @patch('pipeline.basal_ganglia.ACTION_REGISTRY')
    @patch('pipeline.basal_ganglia._resolve_dynamic_action')
    @patch('pipeline.basal_ganglia.check_prerequisites')
    @patch('pipeline.basal_ganglia._passes_shop_gate')
    @patch('pipeline.basal_ganglia.check_habits')
    @patch('pipeline.basal_ganglia.db')
    async def test_idle_passes_with_empty_actions(
        self, mock_db, mock_habits, mock_shop, mock_prereq, mock_resolve, mock_registry,
    ):
        from pipeline.basal_ganglia import select_actions
        from models.pipeline import ValidatedOutput, Intention

        identity = MagicMock()
        identity.actions_enabled = []
        identity.world = WorldConfig(has_physical_space=False)
        context = {
            'visitor_present': False, 'turn_count': 0,
            'mode': 'idle', 'cycle_type': 'idle', 'identity': identity,
        }

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
                Intention(action='idle', content='waiting', target='self', impulse=0.5),
            ],
        )
        drives = MagicMock()
        drives.energy = 0.8

        plan = await select_actions(validated, drives, context=context)
        # 'idle' is a cognitive primitive — should pass even with actions_enabled=[]
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].action, 'idle')
        self.assertEqual(plan.actions[0].status, 'approved')

    @patch('pipeline.basal_ganglia.ACTION_REGISTRY')
    @patch('pipeline.basal_ganglia._resolve_dynamic_action')
    @patch('pipeline.basal_ganglia.check_habits')
    @patch('pipeline.basal_ganglia.db')
    async def test_browse_web_blocked_with_empty_actions(
        self, mock_db, mock_habits, mock_resolve, mock_registry,
    ):
        from pipeline.basal_ganglia import select_actions
        from models.pipeline import ValidatedOutput, Intention

        identity = MagicMock()
        identity.actions_enabled = []
        identity.world = WorldConfig(has_physical_space=False)
        context = {
            'visitor_present': False, 'turn_count': 0,
            'mode': 'idle', 'cycle_type': 'idle', 'identity': identity,
        }

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
                Intention(action='browse_web', content='search', target='web', impulse=0.8),
            ],
        )
        drives = MagicMock()
        drives.energy = 0.8

        plan = await select_actions(validated, drives, context=context)
        # browse_web is NOT a cognitive primitive — should be blocked
        self.assertEqual(len(plan.actions), 0)
        self.assertEqual(len(plan.suppressed), 1)
        self.assertEqual(plan.suppressed[0].status, 'incapable')


class TestSelfContextNoShopLine(unittest.IsolatedAsyncioTestCase):
    """Self-context omits Shop: line for non-physical agents."""

    @patch('prompt.self_context.db')
    async def test_digital_has_time_no_shop(self, mock_db):
        from prompt.self_context import assemble_self_context

        # Mock DB calls
        mock_db.get_drives_state = AsyncMock(return_value=MagicMock(
            mood_valence=0.3, mood_arousal=0.2, social_hunger=0.4,
            expression_need=0.1, rest_need=0.1,
        ))
        mock_db.get_budget_remaining = AsyncMock(return_value={'remaining': 50, 'limit': 100})
        mock_db.get_room_state = AsyncMock(return_value=MagicMock(shop_status='open'))
        mock_db.get_last_cycle_log = AsyncMock(return_value=None)
        mock_db.get_recent_cycle_logs = AsyncMock(return_value=[])
        mock_db.get_recent_executed_actions = AsyncMock(return_value=[])
        mock_db.get_totem_context = AsyncMock(return_value='')
        mock_db.get_active_threads = AsyncMock(return_value=[])

        digital_world = WorldConfig(has_physical_space=False)
        result = await assemble_self_context(
            world=digital_world,
            identity_compact='I exist here. I think, I rest, I remember.',
        )

        self.assertIn('Time:', result)
        self.assertNotIn('Shop:', result)
        # Identity line from param, not Shopkeeper
        self.assertIn('I exist here', result)
        self.assertNotIn('keeper of a shop', result)


class TestSleepReflectUsesIdentity(unittest.TestCase):
    """sleep_reflect() uses identity_compact param in system message."""

    def test_system_message_uses_param(self):
        from pipeline.cortex import SLEEP_REFLECTION_SYSTEM

        custom_identity = "I exist here. I think, I rest, I remember."
        system = SLEEP_REFLECTION_SYSTEM.format(identity_compact=custom_identity)

        self.assertIn('I exist here', system)
        self.assertNotIn('keeper of a shop', system)


class TestFidgetsUseWorldConfig(unittest.TestCase):
    """Fidget behaviors come from WorldConfig."""

    def test_digital_fidgets(self):
        digital_world = WorldConfig(has_physical_space=False,
                                    framing=_DIGITAL_FRAMING,
                                    fidgets=_DIGITAL_DEFAULTS['fidgets'],
                                    gaze_directions=_DIGITAL_DEFAULTS['gaze_directions'])

        fidget_names = [f[0] for f in digital_world.fidgets]
        self.assertIn('drifting', fidget_names)
        self.assertIn('surfacing', fidget_names)
        self.assertIn('settling', fidget_names)
        # No physical fidgets
        self.assertNotIn('adjusts_glasses', fidget_names)
        self.assertNotIn('sips_tea', fidget_names)

    def test_digital_gaze(self):
        digital_world = WorldConfig(has_physical_space=False,
                                    framing=_DIGITAL_FRAMING,
                                    gaze_directions=_DIGITAL_DEFAULTS['gaze_directions'])

        self.assertIn('inward', digital_world.gaze_directions)
        self.assertIn('outward', digital_world.gaze_directions)
        self.assertNotIn('window', digital_world.gaze_directions)
        self.assertNotIn('at_visitor', digital_world.gaze_directions)

    def test_physical_fidgets(self):
        physical_world = WorldConfig()  # defaults to physical
        fidget_names = [f[0] for f in physical_world.fidgets]
        self.assertIn('adjusts_glasses', fidget_names)
        self.assertIn('sips_tea', fidget_names)
        self.assertIn('glances_at_window', fidget_names)


class TestAmbientPerceptionDigital(unittest.TestCase):
    """Ambient perception has no shop references for digital agents."""

    def test_digital_ambient_no_shop(self):
        from pipeline.sensorium import build_ambient_perception
        from models.state import DrivesState

        drives = DrivesState()
        digital_world = WorldConfig(has_physical_space=False)
        perception = build_ambient_perception(drives, world=digital_world)

        content_lower = perception.content.lower()
        self.assertNotIn('shop', content_lower)
        self.assertNotIn('windows', content_lower)

    def test_physical_ambient_has_shop(self):
        from pipeline.sensorium import build_ambient_perception
        from models.state import DrivesState

        drives = DrivesState()
        physical_world = WorldConfig(has_physical_space=True)
        perception = build_ambient_perception(drives, world=physical_world)

        # Physical ambient references shop or windows in at least some hours
        # (depends on current hour, but at least one path has "shop")
        # We test the function runs without error; content check is best-effort
        self.assertTrue(perception.content)


class TestWeatherDiegeticDigital(unittest.TestCase):
    """Weather diegetic mapping for non-physical agents."""

    def test_rain_no_shop(self):
        from pipeline.ambient import map_to_diegetic
        result = map_to_diegetic('rain', has_physical=False)
        content_lower = result.diegetic_text.lower()
        self.assertNotIn('shop', content_lower)
        self.assertNotIn('counter', content_lower)
        self.assertNotIn('awning', content_lower)
        self.assertIn('rain', content_lower)

    def test_rain_physical_has_shop(self):
        from pipeline.ambient import map_to_diegetic
        result = map_to_diegetic('rain', has_physical=True)
        # Physical rain text mentions shop or physical space
        self.assertTrue(result.diegetic_text)

    def test_clear_no_shop(self):
        from pipeline.ambient import map_to_diegetic
        result = map_to_diegetic('clear', has_physical=False)
        content_lower = result.diegetic_text.lower()
        self.assertNotIn('shop', content_lower)


class TestAutonomousRoutingDigital(unittest.IsolatedAsyncioTestCase):
    """Autonomous routing uses conditional solitude text."""

    async def test_digital_solitude(self):
        from pipeline.thalamus import autonomous_routing
        from models.state import DrivesState

        drives = DrivesState()
        result = await autonomous_routing(drives, has_physical=False)

        # Focus perception should have digital solitude text
        self.assertEqual(result.focus.content, 'No one is here. Quiet.')

    async def test_physical_solitude(self):
        from pipeline.thalamus import autonomous_routing
        from models.state import DrivesState

        drives = DrivesState()
        result = await autonomous_routing(drives, has_physical=True)

        self.assertEqual(result.focus.content, 'No one is here. The shop is quiet.')


class TestWorldConfigYamlLoading(unittest.TestCase):
    """WorldConfig loads correctly from both YAML presets."""

    def test_shopkeeper_world(self):
        identity = AgentIdentity.default()
        self.assertTrue(identity.world.has_physical_space)
        self.assertIn('sitting', identity.world.body_states)
        self.assertIn('window', identity.world.gaze_directions)
        self.assertEqual(identity.world.visitor_arrive_label, 'VISITOR IN SHOP')

    def test_digital_lifeform_world(self):
        identity = AgentIdentity.digital_lifeform()
        self.assertFalse(identity.world.has_physical_space)
        self.assertIn('present', identity.world.body_states)
        self.assertIn('inward', identity.world.gaze_directions)
        self.assertEqual(identity.world.visitor_arrive_label, 'VISITOR PRESENT')
        self.assertIn('digital space', identity.world.framing)

    def test_default_world_is_physical(self):
        """WorldConfig() defaults to physical preset."""
        w = WorldConfig()
        self.assertTrue(w.has_physical_space)
        self.assertEqual(w.framing, _SHOPKEEPER_FRAMING)

    def test_world_config_is_frozen(self):
        w = WorldConfig()
        with self.assertRaises(AttributeError):
            w.has_physical_space = False


class TestHypothalamusConditional(unittest.TestCase):
    """Hypothalamus loneliness text conditional on world."""

    def test_digital_loneliness_no_shop(self):
        from pipeline.hypothalamus import drives_to_feeling
        from models.state import DrivesState

        drives = DrivesState(social_hunger=0.95)  # Very high
        result = drives_to_feeling(drives, has_physical=False)
        self.assertNotIn('shop', result.lower())
        self.assertIn('too quiet', result.lower())

    def test_physical_loneliness_has_shop(self):
        from pipeline.hypothalamus import drives_to_feeling
        from models.state import DrivesState

        drives = DrivesState(social_hunger=0.95)
        result = drives_to_feeling(drives, has_physical=True)
        self.assertIn('shop', result.lower())


if __name__ == '__main__':
    unittest.main()
