"""Tests for TASK-095 Phase 2: Agent Isolation.

Verifies:
- Default paths when no env vars set
- AGENT_CONFIG_DIR configures DB path, memory root, identity, config
- Agent ID affects DB filename
- Identity loaded from config dir when present
"""

import os
import tempfile

import yaml
import pytest

from unittest.mock import patch, MagicMock, call


class TestDefaultPaths:
    """Without AGENT_ID/AGENT_CONFIG_DIR, everything uses defaults."""

    def test_default_agent_id(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('AGENT_ID', None)
            os.environ.pop('AGENT_CONFIG_DIR', None)
            from heartbeat_server import ShopkeeperServer
            server = ShopkeeperServer()
            assert server._agent_id == 'default'
            assert server._agent_config_dir == ''
            assert server._identity is None

    def test_custom_agent_id_without_config_dir(self):
        with patch.dict(os.environ, {'AGENT_ID': 'test-bot'}, clear=False):
            os.environ.pop('AGENT_CONFIG_DIR', None)
            from heartbeat_server import ShopkeeperServer
            server = ShopkeeperServer()
            assert server._agent_id == 'test-bot'
            assert server._agent_config_dir == ''


class TestConfigureAgentIsolation:
    """Test _configure_agent_isolation directly to avoid test-ordering issues."""

    def _make_server_stub(self, agent_id, config_dir):
        """Create a minimal object to call _configure_agent_isolation on."""
        from heartbeat_server import ShopkeeperServer
        # Don't call __init__ — just set the fields we need
        obj = object.__new__(ShopkeeperServer)
        obj._agent_id = agent_id
        obj._agent_config_dir = config_dir
        obj._identity = None
        return obj

    def test_db_path_computed_correctly(self):
        """set_db_path is called with {config_dir}/db/{agent_id}.db."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch set_db_path at the object level on the already-imported module
            import db.connection as _mod
            with patch.object(_mod, 'set_db_path') as mock_set:
                stub = self._make_server_stub('agent1', tmpdir)
                stub._configure_agent_isolation()

                expected_db = os.path.join(tmpdir, 'db', 'agent1.db')
                mock_set.assert_called_once_with(expected_db)

    def test_db_dir_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('db.connection.set_db_path'):
                stub = self._make_server_stub('x', tmpdir)
                stub._configure_agent_isolation()
                assert os.path.isdir(os.path.join(tmpdir, 'db'))

    def test_memory_root_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_mem = os.environ.get('MEMORY_ROOT')
            try:
                with patch('db.connection.set_db_path'):
                    stub = self._make_server_stub('m1', tmpdir)
                    stub._configure_agent_isolation()

                    expected_memory = os.path.join(tmpdir, 'memory')
                    assert os.environ.get('MEMORY_ROOT') == expected_memory
                    assert os.path.isdir(expected_memory)
            finally:
                if old_mem is not None:
                    os.environ['MEMORY_ROOT'] = old_mem
                else:
                    os.environ.pop('MEMORY_ROOT', None)

    def test_identity_loaded_from_config_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            identity_data = {
                'identity_compact': 'I am TestBot.',
                'voice_rules': ['Be direct'],
            }
            with open(os.path.join(tmpdir, 'identity.yaml'), 'w') as f:
                yaml.dump(identity_data, f)

            with patch('db.connection.set_db_path'):
                stub = self._make_server_stub('testbot', tmpdir)
                stub._configure_agent_isolation()

                assert stub._identity is not None
                assert stub._identity.identity_compact == 'I am TestBot.'
                assert stub._identity.voice_checksum == ['Be direct']

    def test_no_identity_file_leaves_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('db.connection.set_db_path'):
                stub = self._make_server_stub('plain', tmpdir)
                stub._configure_agent_isolation()
                assert stub._identity is None

    def test_alive_config_override_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, 'alive_config.yaml')
            with open(config_path, 'w') as f:
                yaml.dump({'drives': {'social_hunger_decay': 0.01}}, f)

            old_alive = os.environ.get('ALIVE_CONFIG')
            try:
                with patch('db.connection.set_db_path'):
                    stub = self._make_server_stub('cfg', tmpdir)
                    stub._configure_agent_isolation()
                    assert os.environ.get('ALIVE_CONFIG') == config_path
            finally:
                if old_alive is not None:
                    os.environ['ALIVE_CONFIG'] = old_alive
                else:
                    os.environ.pop('ALIVE_CONFIG', None)

    def test_alive_config_not_set_without_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_alive = os.environ.get('ALIVE_CONFIG')
            os.environ.pop('ALIVE_CONFIG', None)
            try:
                with patch('db.connection.set_db_path'):
                    stub = self._make_server_stub('nocfg', tmpdir)
                    stub._configure_agent_isolation()
                    # Should not have set ALIVE_CONFIG
                    assert os.environ.get('ALIVE_CONFIG') is None
            finally:
                if old_alive is not None:
                    os.environ['ALIVE_CONFIG'] = old_alive


class TestServerInit:
    """Integration test: ShopkeeperServer.__init__ reads env vars."""

    def test_init_without_config_dir(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('AGENT_CONFIG_DIR', None)
            os.environ.pop('AGENT_ID', None)
            from heartbeat_server import ShopkeeperServer
            server = ShopkeeperServer()
            assert server._agent_id == 'default'
            assert server._identity is None

    def test_init_with_config_dir_calls_isolation(self):
        """When AGENT_CONFIG_DIR is set, __init__ calls _configure_agent_isolation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {
                'AGENT_ID': 'init-test',
                'AGENT_CONFIG_DIR': tmpdir,
            }, clear=False):
                with patch('db.connection.set_db_path'):
                    from heartbeat_server import ShopkeeperServer
                    server = ShopkeeperServer()
                    assert server._agent_id == 'init-test'
                    assert os.path.isdir(os.path.join(tmpdir, 'db'))
