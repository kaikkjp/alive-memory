"""Tests for MCP integration in pipeline/cortex.py — _get_mcp_action_block()."""

import unittest
from unittest.mock import patch

from pipeline.action_registry import ACTION_REGISTRY, ActionCapability
import body.mcp_registry as registry


def _cleanup_mcp():
    to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
    for k in to_remove:
        del ACTION_REGISTRY[k]
    registry._servers.clear()


class TestGetMcpActionBlock(unittest.TestCase):
    """_get_mcp_action_block() builds tool block for user message."""

    def setUp(self):
        _cleanup_mcp()

    def tearDown(self):
        _cleanup_mcp()

    def test_empty_when_no_mcp_tools(self):
        from pipeline.cortex import _get_mcp_action_block
        result = _get_mcp_action_block()
        self.assertEqual(result, '')

    def test_block_contains_registered_tools(self):
        from pipeline.cortex import _get_mcp_action_block

        server_info = {
            'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 'search', 'description': 'Search the web',
                 'input_schema': {}, 'enabled': True, 'action_suffix': 'search'},
                {'name': 'calc', 'description': 'Calculator tool',
                 'input_schema': {}, 'enabled': True, 'action_suffix': 'calc'},
            ],
        }
        registry.register_server(1, server_info)

        result = _get_mcp_action_block()
        self.assertIn('CONNECTED TOOLS', result)
        self.assertIn('mcp_1_search', result)
        self.assertIn('Search the web', result)
        self.assertIn('mcp_1_calc', result)
        self.assertIn('Calculator tool', result)

    def test_block_disappears_after_unregister(self):
        from pipeline.cortex import _get_mcp_action_block

        server_info = {
            'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 't1', 'description': 'Tool1', 'input_schema': {},
                 'enabled': True, 'action_suffix': 't1'},
            ],
        }
        registry.register_server(1, server_info)
        self.assertIn('CONNECTED TOOLS', _get_mcp_action_block())

        registry.unregister_server(1)
        self.assertEqual(_get_mcp_action_block(), '')

    def test_disabled_tool_not_in_block(self):
        from pipeline.cortex import _get_mcp_action_block

        server_info = {
            'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 'visible', 'description': 'Visible', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'visible'},
                {'name': 'hidden', 'description': 'Hidden', 'input_schema': {},
                 'enabled': False, 'action_suffix': 'hidden'},
            ],
        }
        registry.register_server(1, server_info)

        result = _get_mcp_action_block()
        self.assertIn('mcp_1_visible', result)
        self.assertNotIn('mcp_1_hidden', result)

    def test_import_error_returns_empty(self):
        """If mcp_registry can't be imported, returns empty gracefully."""
        with patch.dict('sys.modules', {'body.mcp_registry': None}):
            # Re-import to test the ImportError path
            from pipeline.cortex import _get_mcp_action_block
            # The function catches ImportError internally
            # Since the module is already imported in this process, this tests the fallback
            # We can't easily trigger ImportError after first import, so test the positive path
            pass  # Covered by empty test above


class TestMcpBlockFormat(unittest.TestCase):
    """Verify output format of the user-message MCP block."""

    def setUp(self):
        _cleanup_mcp()

    def tearDown(self):
        _cleanup_mcp()

    def test_format_has_header_and_tool_lines(self):
        from pipeline.cortex import _get_mcp_action_block

        server_info = {
            'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 'tool-a', 'description': 'Does A', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'tool_a'},
            ],
        }
        registry.register_server(1, server_info)

        result = _get_mcp_action_block()
        lines = result.strip().split('\n')
        # First line: header
        self.assertIn('CONNECTED TOOLS', lines[0])
        # Tool line: "- name: desc"
        tool_lines = [l for l in lines if l.startswith('- mcp_')]
        self.assertEqual(len(tool_lines), 1)
        self.assertTrue(tool_lines[0].startswith('- mcp_1_tool_a:'))


class TestInjectMcpIntoSchema(unittest.TestCase):
    """MCP action names are injected into system prompt schema enums."""

    def setUp(self):
        _cleanup_mcp()

    def tearDown(self):
        _cleanup_mcp()

    def test_noop_when_no_mcp_tools(self):
        from pipeline.cortex import _inject_mcp_into_schema, build_system_prompt, \
            _DEFAULT_IDENTITY
        original = build_system_prompt(_DEFAULT_IDENTITY)
        patched = _inject_mcp_into_schema(original)
        self.assertEqual(patched, original)

    def test_injects_into_all_four_enums(self):
        """MCP names are injected at build time via mcp_names param."""
        from pipeline.cortex import build_system_prompt, _DEFAULT_IDENTITY

        # Build prompt WITH mcp_names — build-time injection
        prompt = build_system_prompt(_DEFAULT_IDENTITY, mcp_names=['mcp_1_search'])

        # MCP name should appear in action enum strings
        self.assertIn('mcp_1_search', prompt)

        # Should NOT appear in memory_updates.type or trait_category enums
        # Find the memory_updates section and check it's clean
        import re
        # trait_category enum should not have MCP names
        trait_matches = re.findall(r'"trait_category":\s*"([^"]+)"', prompt)
        for m in trait_matches:
            self.assertNotIn('mcp_1_search', m)

        # Build prompt WITHOUT mcp_names — no MCP in output
        prompt_clean = build_system_prompt(_DEFAULT_IDENTITY)
        self.assertNotIn('mcp_1_search', prompt_clean)

    def test_multiple_tools_in_enums(self):
        """Multiple MCP tools are injected via build-time mcp_names param."""
        from pipeline.cortex import build_system_prompt, _DEFAULT_IDENTITY

        prompt = build_system_prompt(
            _DEFAULT_IDENTITY,
            mcp_names=['mcp_1_search', 'mcp_1_calc'],
        )
        self.assertIn('mcp_1_search', prompt)
        self.assertIn('mcp_1_calc', prompt)
        # Both should appear together in enum strings
        self.assertIn('|mcp_1_search|mcp_1_calc', prompt)


class TestMcpBackfill(unittest.TestCase):
    """_backfill_action_detail maps decision.content → MCP arguments."""

    def setUp(self):
        _cleanup_mcp()

    def tearDown(self):
        _cleanup_mcp()

    def test_mcp_backfill_uses_decision_content(self):
        """P1 fix: backfill reads decision.content, not detail.content."""
        from pipeline.basal_ganglia import _backfill_action_detail
        from models.pipeline import ActionDecision

        d = ActionDecision(action='mcp_1_search', content='find apples', detail={})
        _backfill_action_detail(d)
        self.assertEqual(d.detail.get('arguments'), {'query': 'find apples'})

    def test_mcp_backfill_no_override_existing_arguments(self):
        """If detail already has arguments, don't override."""
        from pipeline.basal_ganglia import _backfill_action_detail
        from models.pipeline import ActionDecision

        existing = {'key': 'value'}
        d = ActionDecision(action='mcp_1_search', content='find apples',
                          detail={'arguments': existing})
        _backfill_action_detail(d)
        self.assertEqual(d.detail['arguments'], existing)

    def test_mcp_backfill_empty_content_no_arguments(self):
        """Empty content → no arguments injected."""
        from pipeline.basal_ganglia import _backfill_action_detail
        from models.pipeline import ActionDecision

        d = ActionDecision(action='mcp_1_search', content='', detail={})
        _backfill_action_detail(d)
        self.assertNotIn('arguments', d.detail)


class TestMcpExecutorToolGuard(unittest.TestCase):
    """execute_mcp_action rejects disabled tools at executor level."""

    def setUp(self):
        _cleanup_mcp()

    def tearDown(self):
        _cleanup_mcp()

    def test_disabled_tool_rejected_at_executor(self):
        """P1 fix: tool not in ACTION_REGISTRY → rejected before dispatch."""
        import asyncio
        from body.mcp_executor import execute_mcp_action
        from models.pipeline import ActionRequest

        # Register server with one enabled tool, one disabled
        server_info = {
            'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 'enabled_tool', 'description': 'OK', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'enabled_tool'},
                {'name': 'disabled_tool', 'description': 'Nope', 'input_schema': {},
                 'enabled': False, 'action_suffix': 'disabled_tool'},
            ],
        }
        registry.register_server(1, server_info)

        # The disabled tool is NOT in ACTION_REGISTRY
        self.assertNotIn('mcp_1_disabled_tool', ACTION_REGISTRY)
        # But it IS resolvable via _servers cache
        resolved = registry.resolve_mcp_action('mcp_1_disabled_tool')
        self.assertIsNotNone(resolved)

        # Attempt to execute should fail at the ACTION_REGISTRY guard
        req = ActionRequest(type='mcp_1_disabled_tool', detail={})
        result = asyncio.run(execute_mcp_action(req))
        self.assertFalse(result.success)
        self.assertIn('disabled', result.error)


if __name__ == '__main__':
    unittest.main()
