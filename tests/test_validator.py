"""Tests for pipeline/validator.py — schema, physics, policy, entropy checks."""

import pipeline.validator as validator
from pipeline.validator import (
    validate,
    disclosure_gate,
    canonical_consistency_check,
    entropy_check,
)


class TestSchemaDefaults:
    """validate() fills in missing schema fields with safe defaults."""

    def test_missing_dialogue_gets_silence(self):
        result = validate({}, {'cycle_type': 'idle'})
        assert result['dialogue'] == '...'

    def test_missing_fields_get_defaults(self):
        result = validate({}, {'cycle_type': 'idle'})
        assert result['expression'] == 'neutral'
        assert result['body_state'] == 'sitting'
        assert result['gaze'] == 'at_visitor'
        assert result['resonance'] is False
        assert result['actions'] == []
        assert result['memory_updates'] == []

    def test_existing_dialogue_preserved(self, sample_cortex_output, alone_state):
        result = validate(sample_cortex_output, alone_state)
        assert 'rain' in result['dialogue']


class TestEngagementGate:
    """Alone actions are blocked during engaged conversation."""

    def test_journal_blocked_during_engagement(self, sample_cortex_output, engaged_state):
        sample_cortex_output['actions'] = [{'type': 'write_journal'}]
        result = validate(sample_cortex_output, engaged_state)
        assert len(result['_approved_actions']) == 0
        assert len(result['_dropped_actions']) == 1
        assert result.get('_journal_deferred') is True

    def test_journal_allowed_when_alone(self, sample_cortex_output, alone_state):
        sample_cortex_output['actions'] = [{'type': 'write_journal'}]
        result = validate(sample_cortex_output, alone_state)
        assert len(result['_approved_actions']) == 1

    def test_end_engagement_blocked_before_turn_3(self, sample_cortex_output, engaged_state):
        engaged_state['turn_count'] = 1
        sample_cortex_output['actions'] = [{'type': 'end_engagement'}]
        result = validate(sample_cortex_output, engaged_state)
        assert len(result['_approved_actions']) == 0
        assert 'too early' in result['_dropped_actions'][0]['reason']

    def test_end_engagement_allowed_after_turn_3(self, sample_cortex_output, engaged_state):
        engaged_state['turn_count'] = 5
        sample_cortex_output['actions'] = [{'type': 'end_engagement'}]
        result = validate(sample_cortex_output, engaged_state)
        assert len(result['_approved_actions']) == 1

    def test_close_shop_allowed_when_exhausted(self, sample_cortex_output, engaged_state):
        engaged_state['energy'] = 0.1  # below 0.2 threshold
        sample_cortex_output['actions'] = [{'type': 'close_shop'}]
        result = validate(sample_cortex_output, engaged_state)
        assert len(result['_approved_actions']) == 1


class TestHandsPhysics:
    """Actions requiring hands are blocked when hands are occupied."""

    def test_journal_blocked_when_hands_full(self, sample_cortex_output, alone_state):
        alone_state['hands_held_item'] = 'teacup'
        sample_cortex_output['actions'] = [{'type': 'write_journal'}]
        result = validate(sample_cortex_output, alone_state)
        assert len(result['_approved_actions']) == 0
        assert 'let me put this down' in result['dialogue']

    def test_hands_free_allows_journal(self, sample_cortex_output, alone_state):
        alone_state['hands_held_item'] = None
        sample_cortex_output['actions'] = [{'type': 'write_journal'}]
        result = validate(sample_cortex_output, alone_state)
        assert len(result['_approved_actions']) == 1


class TestDisclosureGate:
    """disclosure_gate blocks assistant tropes."""

    def test_blocks_how_can_i_help(self):
        result = disclosure_gate("How can I help you today?")
        assert "how can i help" not in result.lower()
        assert "..." in result

    def test_blocks_feel_free_to(self):
        result = disclosure_gate("Feel free to ask me anything.")
        assert "feel free to" not in result.lower()

    def test_blocks_as_an_ai(self):
        result = disclosure_gate("As an AI, I cannot do that.")
        assert "as an ai" not in result.lower()

    def test_preserves_normal_dialogue(self):
        text = "The light is nice today."
        assert disclosure_gate(text) == text


class TestCanonicalConsistency:
    """canonical_consistency_check removes trait-contradicting sentences."""

    def test_flags_glasses_denial(self):
        text = "I don't wear glasses."
        cleaned, contradiction = canonical_consistency_check(text)
        assert contradiction is not None
        assert 'glasses' in contradiction.lower()

    def test_flags_do_not_wear_glasses(self):
        text = "I do not wear glasses."
        cleaned, contradiction = canonical_consistency_check(text)
        assert contradiction is not None

    def test_preserves_normal_dialogue(self):
        text = "The rain is nice today."
        cleaned, contradiction = canonical_consistency_check(text)
        assert cleaned == text
        assert contradiction is None

    def test_removes_only_offending_sentence(self):
        text = "The light is nice today. I don't wear glasses. But the tea is warm."
        cleaned, contradiction = canonical_consistency_check(text)
        assert "light" in cleaned
        assert "tea" in cleaned
        assert "glasses" not in cleaned

    def test_silence_and_ellipsis_passthrough(self):
        cleaned, contradiction = canonical_consistency_check("...")
        assert cleaned == "..."
        assert contradiction is None

    def test_empty_string_passthrough(self):
        cleaned, contradiction = canonical_consistency_check("")
        assert cleaned == ""
        assert contradiction is None


class TestEntropyCheck:
    """entropy_check flags repeated openings."""

    def setup_method(self):
        validator._recent_openings.clear()

    def test_no_warning_on_first_use(self):
        output = {'dialogue': 'Hello there, welcome.'}
        result = entropy_check(output)
        assert '_entropy_warning' not in result

    def test_warns_on_repeated_opening(self):
        opening = "The rain falls softly outside."
        for _ in range(6):
            entropy_check({'dialogue': opening})
        result = entropy_check({'dialogue': opening})
        assert '_entropy_warning' in result

    def test_silence_not_tracked(self):
        for _ in range(10):
            result = entropy_check({'dialogue': '...'})
        assert '_entropy_warning' not in result
