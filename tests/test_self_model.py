"""Tests for identity/self_model.py — Persistent Self-Model (TASK-061).

Covers: persistence (save/load), EMA smoothing, trait drift after
many cycles, narrative regen threshold, default state, atomic save,
corrupt file recovery, behavioral signature, relational stance.
"""

import json
import os
import tempfile

import pytest

from identity.self_model import SelfModel, _ema, DEFAULT_TRAITS


# ── Helpers ──

def _tmp_path(tmp_path, name='self_model.json'):
    """Return a temporary file path for self-model JSON."""
    return str(tmp_path / name)


def _make_cycle_data(
    actions=None, drives=None, mood=(0.0, 0.3),
    visitor_interaction=None, cycle_number=1,
):
    """Build a minimal cycle_data dict."""
    return {
        'actions': actions or [],
        'drives': drives,
        'mood': mood,
        'visitor_interaction': visitor_interaction,
        'cycle_number': cycle_number,
    }


class _FakeDrives:
    """Minimal drives object with attribute access."""
    def __init__(self, **kwargs):
        self.social_hunger = kwargs.get('social_hunger', 0.5)
        self.curiosity = kwargs.get('curiosity', 0.5)
        self.expression_need = kwargs.get('expression_need', 0.3)
        self.rest_need = kwargs.get('rest_need', 0.2)
        self.energy = kwargs.get('energy', 0.8)
        self.mood_valence = kwargs.get('mood_valence', 0.0)
        self.mood_arousal = kwargs.get('mood_arousal', 0.3)


# ── EMA helper ──

class TestEMA:
    def test_ema_pure_new(self):
        """Alpha=1.0 should return new value exactly."""
        assert _ema(0.5, 1.0, alpha=1.0) == 1.0

    def test_ema_pure_old(self):
        """Alpha=0.0 should return old value exactly."""
        assert _ema(0.5, 1.0, alpha=0.0) == 0.5

    def test_ema_half(self):
        """Alpha=0.5 should average old and new."""
        assert _ema(0.4, 0.8, alpha=0.5) == pytest.approx(0.6)

    def test_ema_default_alpha(self):
        """Default alpha=0.05: 5% weight to new."""
        result = _ema(0.5, 1.0, alpha=0.05)
        assert result == pytest.approx(0.525)


# ── Default state ──

class TestDefaultState:
    def test_all_traits_start_at_half(self):
        model = SelfModel.default()
        for trait, val in model.trait_weights.items():
            assert val == 0.5, f"{trait} should start at 0.5"

    def test_all_default_traits_present(self):
        model = SelfModel.default()
        for trait in DEFAULT_TRAITS:
            assert trait in model.trait_weights

    def test_behavioral_signature_empty(self):
        model = SelfModel.default()
        assert model.behavioral_signature['action_frequencies'] == {}
        assert model.behavioral_signature['drive_responses'] == {}

    def test_relational_stance_defaults(self):
        model = SelfModel.default()
        assert model.relational_stance['warmth'] == 0.5
        assert model.relational_stance['curiosity'] == 0.5
        assert model.relational_stance['guardedness'] == 0.5

    def test_empty_narrative(self):
        model = SelfModel.default()
        assert model.self_narrative == ''
        assert model.self_narrative_generated_at_cycle == 0

    def test_update_count_zero(self):
        model = SelfModel.default()
        assert model._update_count == 0


# ── Persistence ──

class TestPersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        path = _tmp_path(tmp_path)
        model = SelfModel.default()
        model.trait_weights['curiosity'] = 0.72
        model.self_narrative = 'I like books.'
        model.last_updated_cycle = 42
        model._update_count = 10
        model.save(path)

        loaded = SelfModel.load(path)
        assert loaded.trait_weights['curiosity'] == pytest.approx(0.72)
        assert loaded.self_narrative == 'I like books.'
        assert loaded.last_updated_cycle == 42
        assert loaded._update_count == 10

    def test_load_missing_file_returns_default(self, tmp_path):
        path = _tmp_path(tmp_path, 'nonexistent.json')
        model = SelfModel.load(path)
        assert model.trait_weights == dict(DEFAULT_TRAITS)

    def test_load_corrupt_file_returns_default(self, tmp_path):
        path = _tmp_path(tmp_path)
        with open(path, 'w') as f:
            f.write('not valid json {{{')
        model = SelfModel.load(path)
        assert model.trait_weights == dict(DEFAULT_TRAITS)

    def test_saved_file_is_valid_json(self, tmp_path):
        path = _tmp_path(tmp_path)
        model = SelfModel.default()
        model.update(_make_cycle_data(actions=['read_content'], drives=_FakeDrives()))
        model.save(path)

        with open(path, 'r') as f:
            data = json.load(f)
        assert 'version' in data
        assert 'trait_weights' in data

    def test_atomic_save_creates_file(self, tmp_path):
        path = _tmp_path(tmp_path)
        assert not os.path.exists(path)
        SelfModel.default().save(path)
        assert os.path.exists(path)

    def test_save_creates_directory(self, tmp_path):
        path = str(tmp_path / 'nested' / 'dir' / 'model.json')
        SelfModel.default().save(path)
        assert os.path.exists(path)

    def test_load_preserves_behavioral_signature(self, tmp_path):
        path = _tmp_path(tmp_path)
        model = SelfModel.default()
        # Run a few updates so signature has data
        for i in range(5):
            model.update(_make_cycle_data(
                actions=['read_content'], drives=_FakeDrives(), cycle_number=i,
            ))
        model.save(path)

        loaded = SelfModel.load(path)
        assert 'read_content' in loaded.behavioral_signature['action_frequencies']
        freq = loaded.behavioral_signature['action_frequencies']['read_content']
        assert freq > 0

    def test_load_tolerates_missing_keys(self, tmp_path):
        """A minimal JSON with just version should load without error."""
        path = _tmp_path(tmp_path)
        with open(path, 'w') as f:
            json.dump({'version': 1}, f)
        model = SelfModel.load(path)
        assert model.trait_weights == dict(DEFAULT_TRAITS)


# ── EMA smoothing (1-2 cycles should not shift much) ──

class TestEMASmoothing:
    def test_single_cycle_minimal_shift(self):
        """One cycle should not shift any trait by more than ~0.025."""
        model = SelfModel.default()
        model.update(_make_cycle_data(
            actions=['read_content', 'write_journal'],
            drives=_FakeDrives(),
            cycle_number=1,
        ))
        for trait, val in model.trait_weights.items():
            assert abs(val - 0.5) < 0.03, (
                f"{trait} shifted too much after 1 cycle: {val}"
            )

    def test_two_cycles_still_close_to_neutral(self):
        """Two cycles should not shift any trait by more than ~0.05."""
        model = SelfModel.default()
        for i in range(2):
            model.update(_make_cycle_data(
                actions=['read_content', 'write_journal'],
                drives=_FakeDrives(),
                cycle_number=i + 1,
            ))
        for trait, val in model.trait_weights.items():
            assert abs(val - 0.5) < 0.06, (
                f"{trait} shifted too much after 2 cycles: {val}"
            )


# ── Trait drift after many cycles ──

class TestTraitDrift:
    def test_introversion_rises_with_solitary_actions(self):
        """20+ cycles of read_content should push introversion above 0.5."""
        model = SelfModel.default()
        for i in range(30):
            model.update(_make_cycle_data(
                actions=['read_content', 'write_journal'],
                drives=_FakeDrives(),
                cycle_number=i + 1,
            ))
        assert model.trait_weights['introversion'] > 0.55

    def test_introversion_falls_with_social_actions(self):
        """20+ cycles of speaking with visitors should push introversion below 0.5."""
        model = SelfModel.default()
        for i in range(30):
            model.update(_make_cycle_data(
                actions=['speak', 'mention_in_conversation'],
                drives=_FakeDrives(),
                visitor_interaction={
                    'visitor_id': 'v1', 'turn_count': 5, 'had_dialogue': True,
                },
                cycle_number=i + 1,
            ))
        assert model.trait_weights['introversion'] < 0.45

    def test_curiosity_rises_with_exploratory_actions(self):
        """Consistent exploration pushes curiosity up."""
        model = SelfModel.default()
        for i in range(30):
            model.update(_make_cycle_data(
                actions=['read_content', 'browse_web', 'examine'],
                drives=_FakeDrives(),
                cycle_number=i + 1,
            ))
        assert model.trait_weights['curiosity'] > 0.55

    def test_expressiveness_rises_with_output_actions(self):
        """Consistent journaling/speaking pushes expressiveness up."""
        model = SelfModel.default()
        for i in range(30):
            model.update(_make_cycle_data(
                actions=['write_journal', 'express_thought', 'speak'],
                drives=_FakeDrives(),
                cycle_number=i + 1,
            ))
        assert model.trait_weights['expressiveness'] > 0.55

    def test_warmth_rises_with_long_conversations(self):
        """Long visitor conversations push warmth up."""
        model = SelfModel.default()
        for i in range(30):
            model.update(_make_cycle_data(
                actions=['speak', 'accept_gift'],
                drives=_FakeDrives(),
                visitor_interaction={
                    'visitor_id': 'v1', 'turn_count': 8, 'had_dialogue': True,
                },
                cycle_number=i + 1,
            ))
        assert model.trait_weights['warmth'] > 0.55

    def test_warmth_falls_with_short_dismissals(self):
        """Declining gifts and ending engagement quickly pushes warmth down."""
        model = SelfModel.default()
        for i in range(30):
            model.update(_make_cycle_data(
                actions=['decline_gift', 'end_engagement'],
                drives=_FakeDrives(),
                visitor_interaction={
                    'visitor_id': 'v1', 'turn_count': 1, 'had_dialogue': False,
                },
                cycle_number=i + 1,
            ))
        assert model.trait_weights['warmth'] < 0.45

    def test_no_actions_cycle_keeps_traits_stable(self):
        """Empty action list should not shift traits significantly."""
        model = SelfModel.default()
        for i in range(30):
            model.update(_make_cycle_data(
                actions=[], drives=_FakeDrives(), cycle_number=i + 1,
            ))
        for trait, val in model.trait_weights.items():
            assert abs(val - 0.5) < 0.05, f"{trait} drifted without actions: {val}"


# ── Narrative regeneration ──

class TestNarrativeRegen:
    def test_no_regen_needed_initially(self):
        model = SelfModel.default()
        assert not model.needs_narrative_regen()

    def test_no_regen_after_small_shift(self):
        model = SelfModel.default()
        model.trait_weights['curiosity'] = 0.55  # only 0.05 shift
        assert not model.needs_narrative_regen()

    def test_regen_needed_after_large_shift(self):
        model = SelfModel.default()
        model.trait_weights['curiosity'] = 0.70  # 0.20 shift > 0.15 threshold
        assert model.needs_narrative_regen()

    def test_mark_regenerated_resets_threshold(self):
        model = SelfModel.default()
        model.trait_weights['curiosity'] = 0.70
        assert model.needs_narrative_regen()

        model.mark_narrative_regenerated('I am curious.', cycle=50)
        assert not model.needs_narrative_regen()
        assert model.self_narrative == 'I am curious.'
        assert model.self_narrative_generated_at_cycle == 50

    def test_regen_tracks_per_trait(self):
        """Each trait is checked independently against snapshot."""
        model = SelfModel.default()
        model.mark_narrative_regenerated('baseline', cycle=1)
        # Shift only introversion
        model.trait_weights['introversion'] = 0.70
        assert model.needs_narrative_regen()

    def test_negative_shift_triggers_regen(self):
        model = SelfModel.default()
        model.trait_weights['warmth'] = 0.30  # -0.20 shift
        assert model.needs_narrative_regen()


# ── Behavioral signature ──

class TestBehavioralSignature:
    def test_action_frequencies_track_fired_actions(self):
        model = SelfModel.default()
        model.update(_make_cycle_data(
            actions=['read_content', 'write_journal'],
            drives=_FakeDrives(),
        ))
        freq = model.behavioral_signature['action_frequencies']
        assert freq.get('read_content', 0) > 0
        assert freq.get('write_journal', 0) > 0
        # Unfired action should be near 0
        assert freq.get('speak', 0) < 0.01

    def test_drive_responses_track_ema(self):
        model = SelfModel.default()
        drives = _FakeDrives(social_hunger=0.8, energy=0.3)
        model.update(_make_cycle_data(actions=[], drives=drives))
        dr = model.behavioral_signature['drive_responses']
        assert 'social_hunger' in dr
        assert 'energy' in dr

    def test_sleep_rhythm_counter_increments(self):
        model = SelfModel.default()
        assert model._cycles_since_last_sleep == 0
        model.update(_make_cycle_data(actions=[], drives=_FakeDrives()))
        assert model._cycles_since_last_sleep == 1
        model.update(_make_cycle_data(actions=[], drives=_FakeDrives()))
        assert model._cycles_since_last_sleep == 2

    def test_record_sleep_resets_counter(self):
        model = SelfModel.default()
        for _ in range(10):
            model.update(_make_cycle_data(actions=[], drives=_FakeDrives()))
        assert model._cycles_since_last_sleep == 10
        model.record_sleep()
        assert model._cycles_since_last_sleep == 0
        swr = model.behavioral_signature['sleep_wake_rhythm']
        assert swr['avg_cycles_between_sleep'] > 0


# ── Relational stance ──

class TestRelationalStance:
    def test_no_update_without_visitor(self):
        model = SelfModel.default()
        original = dict(model.relational_stance)
        model.update(_make_cycle_data(actions=['read_content'], drives=_FakeDrives()))
        assert model.relational_stance == original

    def test_warmth_increases_with_dialogue(self):
        model = SelfModel.default()
        for i in range(20):
            model.update(_make_cycle_data(
                actions=['speak'],
                drives=_FakeDrives(),
                visitor_interaction={
                    'visitor_id': 'v1', 'turn_count': 8, 'had_dialogue': True,
                },
                cycle_number=i + 1,
            ))
        assert model.relational_stance['warmth'] > 0.55

    def test_guardedness_decreases_with_long_conversations(self):
        model = SelfModel.default()
        for i in range(20):
            model.update(_make_cycle_data(
                actions=['speak'],
                drives=_FakeDrives(),
                visitor_interaction={
                    'visitor_id': 'v1', 'turn_count': 10, 'had_dialogue': True,
                },
                cycle_number=i + 1,
            ))
        assert model.relational_stance['guardedness'] < 0.45


# ── Update count tracking ──

class TestUpdateCount:
    def test_increments_per_update(self):
        model = SelfModel.default()
        assert model._update_count == 0
        model.update(_make_cycle_data(cycle_number=1))
        assert model._update_count == 1
        model.update(_make_cycle_data(cycle_number=2))
        assert model._update_count == 2

    def test_cycle_number_tracked(self):
        model = SelfModel.default()
        model.update(_make_cycle_data(cycle_number=42))
        assert model.last_updated_cycle == 42


# ── to_dict / serialization ──

class TestSerialization:
    def test_to_dict_produces_valid_json(self):
        model = SelfModel.default()
        model.update(_make_cycle_data(
            actions=['read_content'], drives=_FakeDrives(), cycle_number=1,
        ))
        data = model.to_dict()
        # Should be JSON-serializable without error
        json_str = json.dumps(data)
        assert json.loads(json_str) == data

    def test_to_dict_has_all_required_keys(self):
        model = SelfModel.default()
        data = model.to_dict()
        required = {
            'version', 'last_updated_cycle', 'trait_weights',
            'behavioral_signature', 'relational_stance', 'self_narrative',
            'self_narrative_generated_at_cycle', 'ema_alpha',
            'narrative_regen_threshold',
        }
        assert required.issubset(data.keys())
