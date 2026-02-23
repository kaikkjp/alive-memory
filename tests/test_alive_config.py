"""tests/test_alive_config.py — Unit tests for alive_config.py merge semantics."""

import os
import tempfile

import pytest
import yaml


def _write_yaml(tmp_dir: str, name: str, data: dict) -> str:
    path = os.path.join(tmp_dir, name)
    with open(path, 'w') as f:
        yaml.safe_dump(data, f)
    return path


class TestDeepMerge:
    """Test _deep_merge helper."""

    def test_flat_override(self):
        from alive_config import _deep_merge
        base = {'a': 1, 'b': 2}
        override = {'b': 99}
        assert _deep_merge(base, override) == {'a': 1, 'b': 99}

    def test_nested_override(self):
        from alive_config import _deep_merge
        base = {'x': {'a': 1, 'b': 2, 'c': 3}}
        override = {'x': {'b': 99}}
        result = _deep_merge(base, override)
        assert result == {'x': {'a': 1, 'b': 99, 'c': 3}}

    def test_new_key_added(self):
        from alive_config import _deep_merge
        base = {'a': 1}
        override = {'b': 2}
        assert _deep_merge(base, override) == {'a': 1, 'b': 2}

    def test_override_replaces_non_dict_with_dict(self):
        from alive_config import _deep_merge
        base = {'a': 1}
        override = {'a': {'nested': True}}
        assert _deep_merge(base, override) == {'a': {'nested': True}}

    def test_empty_override_preserves_base(self):
        from alive_config import _deep_merge
        base = {'a': 1, 'b': {'c': 2}}
        assert _deep_merge(base, {}) == base

    def test_base_not_mutated(self):
        from alive_config import _deep_merge
        base = {'x': {'a': 1}}
        override = {'x': {'b': 2}}
        _deep_merge(base, override)
        assert base == {'x': {'a': 1}}


class TestConfigMergeLayers:
    """Test that partial override configs deep-merge onto base, not replace."""

    def test_partial_override_preserves_base_keys(self):
        """A partial --config file should not erase keys it doesn't mention."""
        from alive_config import ALIVEConfig

        with tempfile.TemporaryDirectory() as tmp:
            override = _write_yaml(tmp, 'partial.yaml', {
                'cortex': {'daily_cycle_cap': 999},
            })
            config = ALIVEConfig(override_path=override)

            # Overridden value
            assert config.get('cortex.daily_cycle_cap') == 999
            # Base values still present (not wiped)
            assert config.get('basal_ganglia.drive_gates') is not None
            assert isinstance(config.get('basal_ganglia.drive_gates'), dict)
            assert 'write_journal' in config.get('basal_ganglia.drive_gates')
            assert config.get('hypothalamus.valence_hard_floor') == -0.85

    def test_nested_override_preserves_sibling_keys(self):
        """Overriding one nested key shouldn't erase siblings."""
        from alive_config import ALIVEConfig

        with tempfile.TemporaryDirectory() as tmp:
            override = _write_yaml(tmp, 'nested.yaml', {
                'habit_policy': {'journal': {'cooldown_cycles': 200}},
            })
            config = ALIVEConfig(override_path=override)

            assert config.get('habit_policy.journal.cooldown_cycles') == 200
            # Sibling keys preserved
            assert config.get('habit_policy.journal.expression_threshold') == 0.6
            assert config.get('habit_policy.journal.max_per_day') == 3

    def test_env_override_deep_merges(self):
        """ALIVE_CONFIG env var should deep-merge, not replace."""
        from alive_config import ALIVEConfig

        with tempfile.TemporaryDirectory() as tmp:
            env_file = _write_yaml(tmp, 'env_override.yaml', {
                'cortex': {'idle_temperature': 0.9},
            })
            old_env = os.environ.get('ALIVE_CONFIG')
            try:
                os.environ['ALIVE_CONFIG'] = env_file
                config = ALIVEConfig()

                assert config.get('cortex.idle_temperature') == 0.9
                # Base keys still present
                assert config.get('cortex.daily_cycle_cap') == 500
                assert config.get('basal_ganglia.drive_gates') is not None
            finally:
                if old_env is None:
                    os.environ.pop('ALIVE_CONFIG', None)
                else:
                    os.environ['ALIVE_CONFIG'] = old_env

    def test_three_layer_precedence(self):
        """CLI --config overrides ALIVE_CONFIG which overrides base."""
        from alive_config import ALIVEConfig

        with tempfile.TemporaryDirectory() as tmp:
            env_file = _write_yaml(tmp, 'env.yaml', {
                'cortex': {'daily_cycle_cap': 300, 'idle_temperature': 0.9},
            })
            cli_file = _write_yaml(tmp, 'cli.yaml', {
                'cortex': {'daily_cycle_cap': 100},
            })
            old_env = os.environ.get('ALIVE_CONFIG')
            try:
                os.environ['ALIVE_CONFIG'] = env_file
                config = ALIVEConfig(override_path=cli_file)

                # CLI wins over env
                assert config.get('cortex.daily_cycle_cap') == 100
                # Env wins over base
                assert config.get('cortex.idle_temperature') == 0.9
                # Base preserved
                assert config.get('cortex.engage_temperature') == 0.7
                assert config.get('basal_ganglia.drive_gates') is not None
            finally:
                if old_env is None:
                    os.environ.pop('ALIVE_CONFIG', None)
                else:
                    os.environ['ALIVE_CONFIG'] = old_env

    def test_drive_gates_intact_with_experiment_config(self):
        """Regression: experiment configs must not zero out drive gates."""
        from alive_config import ALIVEConfig

        with tempfile.TemporaryDirectory() as tmp:
            # Simulate a typical experiment config (no drive_gates key)
            experiment = _write_yaml(tmp, 'high_curiosity.yaml', {
                'hypothalamus': {'feeling_curiosity_high': 0.55},
                'cortex': {'rumination_threshold': 8},
            })
            config = ALIVEConfig(override_path=experiment)

            gates = config.get('basal_ganglia.drive_gates')
            assert gates is not None
            assert len(gates) > 0
            assert 'write_journal' in gates
            assert 'speak' in gates
