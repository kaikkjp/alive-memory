"""Shared fixtures for the shopkeeper test suite."""

import asyncio
import sys
import os

import pytest

from models.pipeline import CortexOutput, ValidatorState

# Add project root to path so tests can import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Parameter cache seeding (TASK-055) ──
# Pipeline modules now read constants via db.parameters.p() which requires
# a populated cache. This fixture seeds the cache with default values from
# migration 020_self_parameters.sql so tests don't need a real DB.

_PARAM_DEFAULTS: dict[str, float] = {
    'hypothalamus.equilibria.social_hunger': 0.45,
    'hypothalamus.equilibria.diversive_curiosity': 0.40,
    'hypothalamus.equilibria.expression_need': 0.35,
    'hypothalamus.equilibria.rest_need': 0.25,
    'hypothalamus.equilibria.energy': 0.70,
    'hypothalamus.equilibria.mood_valence': 0.05,
    'hypothalamus.equilibria.mood_arousal': 0.30,
    'hypothalamus.homeostatic_pull_rate': 0.15,
    'hypothalamus.time_decay.social_hunger_per_hour': 0.05,
    'hypothalamus.time_decay.curiosity_per_hour': 0.02,
    'hypothalamus.time_decay.expression_per_hour': 0.04,
    'hypothalamus.time_decay.rest_engaged_per_hour': 0.06,
    'hypothalamus.time_decay.rest_idle_per_hour': 0.03,
    'hypothalamus.event.visitor_speech_social_relief': 0.08,
    'hypothalamus.event.visitor_speech_rest_cost': 0.04,
    'hypothalamus.event.action_speak_expression_relief': 0.05,
    'hypothalamus.event.visitor_connect_arousal': 0.1,
    'hypothalamus.event.visitor_disconnect_arousal': -0.05,
    'hypothalamus.event.visitor_disconnect_social': 0.03,
    'hypothalamus.event.content_consumed_arousal': 0.05,
    'hypothalamus.event.thread_updated_arousal': 0.04,
    'hypothalamus.event.action_variety_arousal': 0.03,
    'hypothalamus.resonance.social_relief': 0.15,
    'hypothalamus.resonance.valence_boost': 0.1,
    'hypothalamus.resonance.arousal_boost': 0.08,
    'hypothalamus.conversation.curiosity_suppress_per_hour': 0.02,
    'hypothalamus.coupling.social_valence_threshold': 0.4,
    'hypothalamus.coupling.social_valence_pressure': -0.02,
    'hypothalamus.coupling.social_valence_floor': 0.15,
    'hypothalamus.coupling.visitor_relief_factor': 0.05,
    'hypothalamus.coupling.idle_arousal_threshold': 5.0,
    'hypothalamus.coupling.idle_arousal_pressure': -0.01,
    'hypothalamus.coupling.idle_arousal_cap': -0.05,
    'hypothalamus.coupling.visitor_connect_extra_arousal': 0.2,
    'hypothalamus.coupling.gap_detection_arousal': 0.1,
    'hypothalamus.coupling.thread_breakthrough_arousal': 0.15,
    'hypothalamus.coupling.expression_frustration_threshold': 0.5,
    'hypothalamus.coupling.expression_frustration_pressure': -0.01,
    'hypothalamus.expression_relief.speak_expression': -0.05,
    'hypothalamus.expression_relief.speak_social': -0.03,
    'hypothalamus.expression_relief.write_journal_expression': -0.12,
    'hypothalamus.expression_relief.write_journal_rest': 0.02,
    'hypothalamus.expression_relief.write_journal_skipped_expression': -0.06,
    'hypothalamus.expression_relief.post_x_expression': -0.10,
    'hypothalamus.expression_relief.post_x_rest': 0.02,
    'hypothalamus.expression_relief.rearrange_expression': -0.06,
    'thalamus.routing.connect_salience_threshold': 0.5,
    'thalamus.routing.silence_salience_threshold': 0.4,
    'thalamus.routing.express_drive_threshold': 0.7,
    'thalamus.routing.rest_drive_threshold': 0.7,
    'thalamus.budget.flashbulb_daily_limit': 5.0,
    'thalamus.budget.flashbulb_tokens': 10000.0,
    'thalamus.budget.deep_tokens': 5000.0,
    'thalamus.budget.casual_tokens': 3000.0,
    'thalamus.budget.autonomous_tokens': 3000.0,
    'thalamus.memory.totem_max_large': 5.0,
    'thalamus.memory.totem_max_small': 3.0,
    'thalamus.memory.totem_min_weight_large': 0.3,
    'thalamus.memory.totem_min_weight_small': 0.6,
    'thalamus.memory.day_context_salience_engage': 0.3,
    'thalamus.memory.day_context_salience_idle': 0.5,
    'thalamus.notification.salience_threshold': 0.03,
    'thalamus.notification.visitor_suppress': 0.3,
    'thalamus.notification.topic_match_boost': 1.5,
    'thalamus.notification.low_energy_suppress': 0.2,
    'thalamus.notification.high_curiosity_boost': 1.3,
    'sensorium.salience.base': 0.5,
    'sensorium.salience.trust_stranger': 0.0,
    'sensorium.salience.trust_returner': 0.1,
    'sensorium.salience.trust_regular': 0.2,
    'sensorium.salience.trust_familiar': 0.3,
    'sensorium.salience.gift_bonus': 0.2,
    'sensorium.salience.question_bonus': 0.1,
    'sensorium.salience.personal_bonus': 0.15,
    'sensorium.salience.social_hunger_bonus': 0.15,
    'sensorium.salience.low_energy_penalty': -0.1,
    'sensorium.connect.base': 0.3,
    'sensorium.connect.trust_stranger': 0.0,
    'sensorium.connect.trust_returner': 0.15,
    'sensorium.connect.trust_regular': 0.3,
    'sensorium.connect.trust_familiar': 0.45,
    'sensorium.connect.social_hunger_high_bonus': 0.2,
    'sensorium.connect.social_hunger_mid_bonus': 0.1,
    'sensorium.connect.expression_penalty': -0.15,
    'sensorium.connect.low_energy_penalty': -0.1,
    'sensorium.fidget.recency_seconds': 300.0,
    'sensorium.fidget.mismatch_salience': 0.4,
    'sensorium.perception.max_count': 6.0,
    'basal_ganglia.trust_bonus.stranger': 0.0,
    'basal_ganglia.trust_bonus.returner': 0.05,
    'basal_ganglia.trust_bonus.regular': 0.10,
    'basal_ganglia.trust_bonus.familiar': 0.15,
    'basal_ganglia.priority.social_hunger_factor': 0.3,
    'basal_ganglia.priority.interest_bonus': 0.1,
    'basal_ganglia.priority.disengagement_factor': 0.5,
    'basal_ganglia.inhibition.strength_threshold': 0.2,
    'basal_ganglia.habit.strength_threshold': 0.6,
    'basal_ganglia.habit.cooldown_cycles': 3.0,
    'basal_ganglia.habit.open_shop_rest_gate': 0.6,
    'output.drives.end_engagement_rest_relief': -0.03,
    'output.drives.failure_valence_penalty': -0.05,
    'output.drives.success_bonus_base': 0.02,
    'output.drives.success_habituation_divisor': 10.0,
    'output.drives.quiet_cycle_rest_relief': -0.06,
    'output.drives.non_routine_arousal_bump': 0.04,
    'output.resonance.social_relief': 0.15,
    'output.resonance.valence_boost': 0.1,
    'output.resonance.curiosity_relief': 0.03,
    'output.resonance.arousal_boost': 0.06,
    'output.inhibition.strength_increment': 0.15,
    'output.inhibition.initial_strength': 0.3,
    'output.inhibition.decay_amount': 0.1,
    'output.inhibition.delete_threshold': 0.05,
    'output.habit.strength_cap': 0.9,
    'output.habit.decay_rate': 0.01,
    'output.habit.delete_threshold': 0.05,
    'output.habit.delta_fast': 0.12,
    'output.habit.delta_medium': 0.06,
    'output.habit.delta_slow': 0.03,
    'output.reflection.totem_weight_boost': 0.1,
    'output.reflection.new_totem_weight': 0.3,
    'output.reflection.topic_similarity_threshold': 0.5,
    'output.reflection.boring_curiosity_drain': -0.02,
    'output.reflection.resolved_curiosity_drain': -0.05,
    'output.reflection.memory_valence_bump': 0.03,
    'output.reflection.question_arousal_bump': 0.05,
    'sleep.consolidation.max_reflections': 7.0,
    'sleep.consolidation.min_salience': 0.45,
    'sleep.consolidation.max_retries': 3.0,
    'sleep.consolidation.nap_top_n': 3.0,
    'sleep.cleanup.stale_day_memory_days': 2.0,
    'sleep.cleanup.dormant_thread_hours': 48.0,
    'sleep.cleanup.archive_thread_days': 7.0,
    'sleep.morning.social_hunger': 0.5,
    'sleep.morning.curiosity': 0.5,
    'sleep.morning.expression_need': 0.3,
    'sleep.morning.rest_need': 0.2,
    'sleep.morning.energy': 1.0,
}


# Seed cache at import time so module-level p() calls work during collection.
import db.parameters as _params_mod
_params_mod._cache = dict(_PARAM_DEFAULTS)
_params_mod._known_keys = set(_PARAM_DEFAULTS.keys())


@pytest.fixture(autouse=True)
def _seed_params_cache():
    """Re-seed db.parameters cache before each test so p() is reliable."""
    _params_mod._cache = dict(_PARAM_DEFAULTS)
    yield
    # Don't clear — other fixtures/teardown may still need p()


@pytest.fixture
def sample_cortex_output():
    """Minimal valid CortexOutput."""
    return CortexOutput(
        dialogue='The rain sounds different today.',
        dialogue_language='en',
        expression='neutral',
        body_state='sitting',
        gaze='at_window',
        resonance=False,
        internal_monologue='The sound on the roof has changed.',
    )


@pytest.fixture
def engaged_state():
    """ValidatorState simulating an engaged conversation."""
    return ValidatorState(
        cycle_type='engage',
        energy=0.6,
        hands_held_item=None,
        turn_count=5,
    )


@pytest.fixture
def alone_state():
    """ValidatorState simulating idle/alone time."""
    return ValidatorState(
        cycle_type='idle',
        energy=0.7,
        hands_held_item=None,
        turn_count=0,
    )
