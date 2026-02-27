"""Tests for body/mcp_registry.py — MCP registry + ACTION_REGISTRY injection."""

import unittest
from unittest.mock import AsyncMock, patch

from pipeline.action_registry import ACTION_REGISTRY, ActionCapability
from body.mcp_client import McpToolSchema
import body.mcp_registry as registry


class TestNormalizeToolName(unittest.TestCase):
    """Tool name normalization."""

    def test_lowercase(self):
        self.assertEqual(registry._normalize_tool_name('SearchProducts'), 'searchproducts')

    def test_replace_dashes(self):
        self.assertEqual(registry._normalize_tool_name('search-products'), 'search_products')

    def test_replace_dots(self):
        self.assertEqual(registry._normalize_tool_name('api.search'), 'api_search')

    def test_replace_spaces(self):
        self.assertEqual(registry._normalize_tool_name('search items'), 'search_items')

    def test_strip_edges(self):
        self.assertEqual(registry._normalize_tool_name('-search-'), 'search')

    def test_empty_returns_tool(self):
        self.assertEqual(registry._normalize_tool_name(''), 'tool')

    def test_all_special_chars_returns_tool(self):
        self.assertEqual(registry._normalize_tool_name('---'), 'tool')


class TestComputeActionSuffixes(unittest.TestCase):
    """Suffix computation and deduplication."""

    def test_basic_suffix(self):
        tools = [McpToolSchema(name='search-products', description='Search', input_schema={})]
        result, warnings = registry.compute_action_suffixes(tools)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['action_suffix'], 'search_products')
        self.assertEqual(warnings, [])

    def test_collision_suffixes(self):
        """Two tools that normalize to same name get _2 suffix."""
        tools = [
            McpToolSchema(name='Get-Data', description='A', input_schema={}),
            McpToolSchema(name='get_data', description='B', input_schema={}),
        ]
        result, warnings = registry.compute_action_suffixes(tools)
        self.assertEqual(len(result), 2)
        suffixes = {r['action_suffix'] for r in result}
        self.assertIn('get_data', suffixes)
        self.assertIn('get_data_2', suffixes)

    def test_duplicate_raw_name_last_wins(self):
        """Duplicate raw names → last definition wins, warning emitted."""
        tools = [
            McpToolSchema(name='search', description='First', input_schema={}),
            McpToolSchema(name='search', description='Second', input_schema={}),
        ]
        result, warnings = registry.compute_action_suffixes(tools)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['description'], 'Second')
        self.assertTrue(any('Duplicate' in w for w in warnings))

    def test_sorted_deterministic(self):
        """Tools are sorted by raw name for deterministic suffix assignment."""
        tools = [
            McpToolSchema(name='z-tool', description='Z', input_schema={}),
            McpToolSchema(name='a-tool', description='A', input_schema={}),
        ]
        result, _ = registry.compute_action_suffixes(tools)
        # Sorted by raw name: a-tool first, z-tool second
        self.assertEqual(result[0]['name'], 'a-tool')
        self.assertEqual(result[1]['name'], 'z-tool')

    def test_all_tools_enabled_by_default(self):
        tools = [McpToolSchema(name='t1', description='', input_schema={})]
        result, _ = registry.compute_action_suffixes(tools)
        self.assertTrue(result[0]['enabled'])


class TestRegisterServer(unittest.TestCase):
    """Server registration into ACTION_REGISTRY."""

    def setUp(self):
        # Clean up any MCP entries from previous tests
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()

    def tearDown(self):
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()

    def test_register_injects_into_registry(self):
        server_info = {
            'url': 'http://test',
            'enabled': 1,
            'discovered_tools': [
                {'name': 'search', 'description': 'Search', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'search'},
            ],
        }
        registered = registry.register_server(99, server_info)
        self.assertEqual(registered, ['mcp_99_search'])
        self.assertIn('mcp_99_search', ACTION_REGISTRY)
        cap = ACTION_REGISTRY['mcp_99_search']
        self.assertEqual(cap.description, 'Search')
        self.assertTrue(cap.enabled)

    def test_register_skips_disabled_tools(self):
        server_info = {
            'url': 'http://test',
            'enabled': 1,
            'discovered_tools': [
                {'name': 'a', 'description': 'A', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'a'},
                {'name': 'b', 'description': 'B', 'input_schema': {},
                 'enabled': False, 'action_suffix': 'b'},
            ],
        }
        registered = registry.register_server(99, server_info)
        self.assertEqual(registered, ['mcp_99_a'])
        self.assertNotIn('mcp_99_b', ACTION_REGISTRY)

    def test_register_disabled_server_no_registry_entries(self):
        server_info = {
            'url': 'http://test',
            'enabled': 0,  # server disabled
            'discovered_tools': [
                {'name': 'search', 'description': 'Search', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'search'},
            ],
        }
        registered = registry.register_server(99, server_info)
        self.assertEqual(registered, [])
        self.assertNotIn('mcp_99_search', ACTION_REGISTRY)

    def test_servers_cache_covers_all_tools(self):
        """_servers cache includes disabled tools (for resolve)."""
        server_info = {
            'url': 'http://test',
            'enabled': 1,
            'discovered_tools': [
                {'name': 'a', 'description': 'A', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'a'},
                {'name': 'b', 'description': 'B', 'input_schema': {},
                 'enabled': False, 'action_suffix': 'b'},
            ],
        }
        registry.register_server(99, server_info)
        self.assertIn('a', registry._servers[99]['tools'])
        self.assertIn('b', registry._servers[99]['tools'])


class TestUnregisterServer(unittest.TestCase):
    """Server unregistration."""

    def setUp(self):
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()

    def tearDown(self):
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()

    def test_unregister_removes_entries(self):
        server_info = {
            'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 'a', 'description': 'A', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'a'},
                {'name': 'b', 'description': 'B', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'b'},
            ],
        }
        registry.register_server(99, server_info)
        self.assertIn('mcp_99_a', ACTION_REGISTRY)

        removed = registry.unregister_server(99)
        self.assertNotIn('mcp_99_a', ACTION_REGISTRY)
        self.assertNotIn('mcp_99_b', ACTION_REGISTRY)
        self.assertEqual(set(removed), {'mcp_99_a', 'mcp_99_b'})
        self.assertNotIn(99, registry._servers)

    def test_unregister_nonexistent_returns_empty(self):
        removed = registry.unregister_server(999)
        self.assertEqual(removed, [])


class TestResolveMcpAction(unittest.TestCase):
    """Action name resolution."""

    def setUp(self):
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()

    def tearDown(self):
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()

    def test_resolve_valid_action(self):
        server_info = {
            'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 'search-products', 'description': 'S', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'search_products'},
            ],
        }
        registry.register_server(5, server_info)
        result = registry.resolve_mcp_action('mcp_5_search_products')
        self.assertIsNotNone(result)
        server_id, raw_name, url = result
        self.assertEqual(server_id, 5)
        self.assertEqual(raw_name, 'search-products')
        self.assertEqual(url, 'http://test')

    def test_resolve_non_mcp_action(self):
        self.assertIsNone(registry.resolve_mcp_action('speak'))

    def test_resolve_unknown_server(self):
        self.assertIsNone(registry.resolve_mcp_action('mcp_999_search'))

    def test_resolve_bad_format(self):
        self.assertIsNone(registry.resolve_mcp_action('mcp_abc'))
        self.assertIsNone(registry.resolve_mcp_action('mcp_'))


class TestGetMcpActions(unittest.TestCase):
    """Query functions."""

    def setUp(self):
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()

    def tearDown(self):
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()

    def test_get_mcp_action_names_empty(self):
        self.assertEqual(registry.get_mcp_action_names(), [])

    def test_get_mcp_action_names_with_registered(self):
        server_info = {
            'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 't1', 'description': 'D1', 'input_schema': {},
                 'enabled': True, 'action_suffix': 't1'},
            ],
        }
        registry.register_server(1, server_info)
        names = registry.get_mcp_action_names()
        self.assertIn('mcp_1_t1', names)

    def test_get_mcp_action_descriptions(self):
        server_info = {
            'url': 'http://test', 'enabled': 1,
            'discovered_tools': [
                {'name': 't1', 'description': 'Do stuff', 'input_schema': {},
                 'enabled': True, 'action_suffix': 't1'},
            ],
        }
        registry.register_server(1, server_info)
        descs = registry.get_mcp_action_descriptions()
        self.assertEqual(len(descs), 1)
        self.assertEqual(descs[0], ('mcp_1_t1', 'Do stuff'))


class TestLoadFromDb(unittest.IsolatedAsyncioTestCase):
    """Startup rehydration."""

    async def test_load_from_db_injects_registry(self):
        """load_from_db reads DB and injects into ACTION_REGISTRY."""
        # Clean
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()

        mock_servers = [{
            'id': 10,
            'name': 'TestServer',
            'url': 'http://test',
            'enabled': 1,
            'discovered_tools': [
                {'name': 'search', 'description': 'S', 'input_schema': {},
                 'enabled': True, 'action_suffix': 'search'},
            ],
        }]

        with patch('db.get_mcp_servers', new_callable=AsyncMock, return_value=mock_servers):
            await registry.load_from_db()

        self.assertIn('mcp_10_search', ACTION_REGISTRY)

        # Cleanup
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()

    async def test_load_from_db_skips_bad_server(self):
        """One bad server doesn't block others."""
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()

        mock_servers = [
            {'id': 1, 'name': 'Bad', 'url': '', 'enabled': 1,
             'discovered_tools': None},  # Will cause issue
            {'id': 2, 'name': 'Good', 'url': 'http://good', 'enabled': 1,
             'discovered_tools': [
                 {'name': 'tool', 'description': 'D', 'input_schema': {},
                  'enabled': True, 'action_suffix': 'tool'},
             ]},
        ]

        with patch('db.get_mcp_servers', new_callable=AsyncMock, return_value=mock_servers):
            await registry.load_from_db()

        # Good server should still be registered
        self.assertIn('mcp_2_tool', ACTION_REGISTRY)

        # Cleanup
        to_remove = [k for k in ACTION_REGISTRY if k.startswith('mcp_')]
        for k in to_remove:
            del ACTION_REGISTRY[k]
        registry._servers.clear()


class TestMergeActionSuffixes(unittest.TestCase):
    """merge_action_suffixes preserves existing suffixes on reconnect."""

    def test_preserves_existing_suffix(self):
        """Tool that still exists keeps its persisted suffix."""
        new_tools = [McpToolSchema(name='search', description='Search')]
        existing = [{'name': 'search', 'description': 'Old Search',
                     'action_suffix': 'search', 'enabled': True}]

        result, _ = registry.merge_action_suffixes(new_tools, existing)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['action_suffix'], 'search')
        self.assertEqual(result[0]['description'], 'Search')  # updated description

    def test_preserves_enabled_state(self):
        """Disabled tool stays disabled after reconnect."""
        new_tools = [McpToolSchema(name='search', description='Search')]
        existing = [{'name': 'search', 'description': 'Search',
                     'action_suffix': 'search', 'enabled': False}]

        result, _ = registry.merge_action_suffixes(new_tools, existing)
        self.assertFalse(result[0]['enabled'])

    def test_new_tool_gets_suffix_avoiding_collision(self):
        """New tool gets a suffix that doesn't collide with existing."""
        new_tools = [
            McpToolSchema(name='search', description='Search'),
            McpToolSchema(name='Search', description='Search v2'),
        ]
        existing = [{'name': 'search', 'description': 'Search',
                     'action_suffix': 'search', 'enabled': True}]

        result, _ = registry.merge_action_suffixes(new_tools, existing)
        suffixes = {r['action_suffix'] for r in result}
        self.assertIn('search', suffixes)  # existing preserved
        self.assertEqual(len(suffixes), 2)  # no collision
        # The new tool should have search_2 (not search)
        new_entry = [r for r in result if r['name'] == 'Search'][0]
        self.assertEqual(new_entry['action_suffix'], 'search_2')

    def test_removed_tool_dropped(self):
        """Tool removed from server doesn't appear in result."""
        new_tools = [McpToolSchema(name='search', description='Search')]
        existing = [
            {'name': 'search', 'description': 'Search',
             'action_suffix': 'search', 'enabled': True},
            {'name': 'calc', 'description': 'Calc',
             'action_suffix': 'calc', 'enabled': True},
        ]

        result, _ = registry.merge_action_suffixes(new_tools, existing)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'search')

    def test_suffix_stable_across_reorders(self):
        """Even if server returns tools in different order, suffixes stay."""
        existing = [
            {'name': 'alpha', 'description': 'A', 'action_suffix': 'alpha', 'enabled': True},
            {'name': 'beta', 'description': 'B', 'action_suffix': 'beta', 'enabled': True},
        ]
        # Server returns in reverse order
        new_tools = [
            McpToolSchema(name='beta', description='B new'),
            McpToolSchema(name='alpha', description='A new'),
        ]

        result, _ = registry.merge_action_suffixes(new_tools, existing)
        by_name = {r['name']: r for r in result}
        self.assertEqual(by_name['alpha']['action_suffix'], 'alpha')
        self.assertEqual(by_name['beta']['action_suffix'], 'beta')


if __name__ == '__main__':
    unittest.main()
