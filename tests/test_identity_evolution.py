"""Tests for identity evolution stub (TASK-063)."""

import json
from pathlib import Path

import pytest

from identity.evolution import (
    DriftReport,
    EvolutionAction,
    EvolutionDecision,
    GuardRailConfig,
    IdentityEvolution,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config_path():
    return Path(__file__).parent.parent / "identity" / "evolution_config.json"


@pytest.fixture
def drift_report():
    return DriftReport(
        trait_name="curiosity",
        baseline_value=0.7,
        current_value=0.85,
        drift_magnitude=0.15,
        sustained_cycles=5,
        context="Increased curiosity after reading science articles",
    )


# ---------------------------------------------------------------------------
# Interface exists and is importable
# ---------------------------------------------------------------------------

class TestImportable:
    def test_can_import_identity_evolution(self):
        from identity.evolution import IdentityEvolution
        assert IdentityEvolution is not None

    def test_can_import_data_models(self):
        from identity.evolution import DriftReport, EvolutionDecision, EvolutionAction
        assert DriftReport is not None
        assert EvolutionDecision is not None
        assert EvolutionAction is not None

    def test_can_import_guard_rail_config(self):
        from identity.evolution import GuardRailConfig
        assert GuardRailConfig is not None


# ---------------------------------------------------------------------------
# Guard rail config loads and validates
# ---------------------------------------------------------------------------

class TestGuardRailConfig:
    def test_config_file_exists(self, config_path):
        assert config_path.exists(), f"Config file missing: {config_path}"

    def test_config_is_valid_json(self, config_path):
        with open(config_path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_config_loads(self):
        config = GuardRailConfig.load()
        assert isinstance(config, GuardRailConfig)

    def test_config_has_protected_traits(self):
        config = GuardRailConfig.load()
        assert len(config.protected_traits) > 0
        assert "non_hostility" in config.protected_traits

    def test_config_max_updates_per_sleep(self):
        config = GuardRailConfig.load()
        assert config.max_updates_per_sleep == 1

    def test_config_min_sustained_cycles(self):
        config = GuardRailConfig.load()
        assert config.min_sustained_cycles >= 1

    def test_config_operator_override_enabled(self):
        config = GuardRailConfig.load()
        assert config.operator_override_enabled is True

    def test_config_missing_file_falls_back_to_defaults(self, tmp_path):
        config = GuardRailConfig.load(tmp_path / "nonexistent.json")
        assert config.protected_traits == []
        assert config.max_updates_per_sleep == 1
        assert config.min_sustained_cycles == 3
        assert config.operator_override_enabled is True


# ---------------------------------------------------------------------------
# All methods raise NotImplementedError
# ---------------------------------------------------------------------------

class TestStubMethods:
    def test_evaluate_drift_raises(self, drift_report):
        evo = IdentityEvolution()
        with pytest.raises(NotImplementedError, match="pending philosophical review"):
            evo.evaluate_drift(drift_report)

    def test_accept_drift_raises(self, drift_report):
        evo = IdentityEvolution()
        with pytest.raises(NotImplementedError, match="pending philosophical review"):
            evo.accept_drift(drift_report)

    def test_correct_drift_raises(self, drift_report):
        evo = IdentityEvolution()
        with pytest.raises(NotImplementedError, match="pending philosophical review"):
            evo.correct_drift(drift_report)

    def test_defer_raises(self, drift_report):
        evo = IdentityEvolution()
        with pytest.raises(NotImplementedError, match="pending philosophical review"):
            evo.defer(drift_report)


# ---------------------------------------------------------------------------
# Status properties
# ---------------------------------------------------------------------------

class TestStatus:
    def test_enabled_is_false(self):
        evo = IdentityEvolution()
        assert evo.enabled is False

    def test_status_message_shows_disabled(self):
        evo = IdentityEvolution()
        assert "disabled" in evo.status_message
        assert "pending review" in evo.status_message


# ---------------------------------------------------------------------------
# Data model construction
# ---------------------------------------------------------------------------

class TestDataModels:
    def test_drift_report_creation(self, drift_report):
        assert drift_report.trait_name == "curiosity"
        assert drift_report.drift_magnitude == 0.15
        assert drift_report.sustained_cycles == 5

    def test_evolution_decision_creation(self):
        decision = EvolutionDecision(
            action=EvolutionAction.DEFER,
            trait_name="curiosity",
            reason="Insufficient observation period",
            confidence=0.3,
        )
        assert decision.action == EvolutionAction.DEFER
        assert decision.confidence == 0.3

    def test_evolution_action_values(self):
        assert EvolutionAction.ACCEPT.value == "accept"
        assert EvolutionAction.CORRECT.value == "correct"
        assert EvolutionAction.DEFER.value == "defer"
