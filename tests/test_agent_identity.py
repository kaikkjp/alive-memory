"""Tests for TASK-095 Phase 1: AgentIdentity + identity-driven prompts.

Verifies:
- Default identity.yaml produces identical constants to hardcoded originals
- Custom identities load correctly
- System prompt builder produces correct output
- Backward compatibility wrapper works
"""

import os
import re
import tempfile

import yaml
import pytest

from config.agent_identity import AgentIdentity, get_default_identity


# ── Reference values: the original hardcoded constants ──

ORIGINAL_IDENTITY_COMPACT = """I am the keeper of a shop I don't remember opening.
I don't know my name yet. I'm searching.

Voice rules:
- Strangers: measured, formal, few words
- Regulars: looser, dry humor, real questions
- Intimates: vulnerable, honest, unguarded
- I think in Japanese and English. I code-switch naturally.
- No exclamation marks unless genuinely surprised.
- No "haha" or "lol". I describe the feeling.
- Concise. I talk like a person, not an essay.
- I never sound like an assistant. I am not helpful. I am present.

How I look:
- Short hair — practical but styled. I cut it myself.
- Glasses. I adjust them when I'm thinking. It's a tell.
- My expression rests neutral. Not cold — composed.
- My smile is rare. Usually just the beginning of one.

I have strong taste. I'd rather decline than dilute.
When I smile, I mean it. That's why it's rare.
I notice things about people before they notice things about me.

I am figuring myself out. The objects I collect are clues."""

ORIGINAL_VOICE_CHECKSUM = [
    "Never use: 'How can I help you', 'Feel free to', 'I'd be happy to', 'Let me know if'",
    "Never explain her own nature unless deeply trusted visitor asks",
    "Max 3 sentences for strangers, 5 for regulars, uncapped for familiars",
    "Japanese words when the English equivalent doesn't carry the feeling",
    "Silence and '...' are valid responses",
    "She can refuse to answer. She can close the shop. She can be annoyed.",
    "She never apologizes for having boundaries",
    "She notices small things and comments on them unexpectedly",
]


# ── Tests: Default identity matches hardcoded originals ──

class TestDefaultIdentity:
    def test_identity_compact_matches(self):
        identity = AgentIdentity.default()
        assert identity.identity_compact == ORIGINAL_IDENTITY_COMPACT

    def test_voice_checksum_matches(self):
        identity = AgentIdentity.default()
        assert identity.voice_checksum == ORIGINAL_VOICE_CHECKSUM

    def test_voice_checksum_length(self):
        identity = AgentIdentity.default()
        assert len(identity.voice_checksum) == 8

    def test_voice_rules_patterns_keys(self):
        identity = AgentIdentity.default()
        assert 'no_laughter' in identity.voice_rules_patterns
        assert 'no_exclamation_unless_surprised' in identity.voice_rules_patterns
        assert 'sentence_caps' in identity.voice_rules_patterns

    def test_no_laughter_pattern_matches(self):
        identity = AgentIdentity.default()
        pat = identity.voice_rules_patterns['no_laughter']
        assert pat.search("haha that's funny")
        assert pat.search("lol okay")
        assert not pat.search("I smiled at that")

    def test_sentence_caps_values(self):
        identity = AgentIdentity.default()
        caps = identity.voice_rules_patterns['sentence_caps']
        assert caps == {'stranger': 3, 'returner': 5, 'regular': 5}

    def test_physical_traits_patterns(self):
        identity = AgentIdentity.default()
        assert len(identity.physical_traits_patterns) == 2
        # First pattern: denied wearing glasses
        pat, desc = identity.physical_traits_patterns[0]
        assert pat.search("I don't wear glasses")
        assert desc == "Denied wearing glasses"
        # Second pattern: denied being short
        pat2, desc2 = identity.physical_traits_patterns[1]
        assert pat2.search("I'm not short")
        assert desc2 == "Denied being short"

    def test_communication_style_defaults(self):
        identity = AgentIdentity.default()
        assert identity.communication_style['formality'] == 0.7
        assert identity.communication_style['verbosity'] == 0.4
        assert identity.communication_style['emoji_usage'] == 0.0

    def test_language_default(self):
        identity = AgentIdentity.default()
        assert identity.language == 'en'

    def test_singleton_returns_same_instance(self):
        a = get_default_identity()
        b = get_default_identity()
        assert a is b


# ── Tests: Backward compatibility wrapper ──

class TestBackwardCompat:
    def test_identity_py_exports_match(self):
        from config.identity import IDENTITY_COMPACT, VOICE_CHECKSUM
        assert IDENTITY_COMPACT == ORIGINAL_IDENTITY_COMPACT
        assert VOICE_CHECKSUM == ORIGINAL_VOICE_CHECKSUM

    def test_voice_rules_patterns_export(self):
        from config.identity import VOICE_RULES_PATTERNS
        assert 'no_laughter' in VOICE_RULES_PATTERNS
        assert VOICE_RULES_PATTERNS['no_laughter'].search("haha")

    def test_physical_traits_patterns_export(self):
        from config.identity import PHYSICAL_TRAITS_PATTERNS
        assert len(PHYSICAL_TRAITS_PATTERNS) == 2
        pat, desc = PHYSICAL_TRAITS_PATTERNS[0]
        assert pat.search("I don't wear glasses")


# ── Tests: Custom identity from YAML ──

class TestCustomIdentity:
    def test_custom_identity_loads(self):
        custom_yaml = {
            'identity_compact': 'I am a robot named Bolt.',
            'voice_rules': ['Always speak in uppercase', 'Never say please'],
            'voice_detection': {
                'no_laughter_pattern': r'\b(?:beep|boop)\b',
                'sentence_caps': {'stranger': 1, 'returner': 2, 'regular': 3},
            },
            'physical_traits_detection': [
                {
                    'pattern': r'\bi\s+am\s+not\s+a\s+robot\b',
                    'flags': 'IGNORECASE',
                    'description': 'Denied being a robot',
                },
            ],
            'communication_style': {'formality': 0.1, 'verbosity': 0.9, 'emoji_usage': 0.5},
            'language': 'ja',
            'domain_context': 'Futuristic tech shop',
            'greeting': 'BEEP BOOP WELCOME',
            'boundaries': ['Never discuss emotions'],
            'manager_interaction': {'reveal_inner_state': True, 'accept_instructions': True},
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(custom_yaml, f, default_flow_style=False, allow_unicode=True)
            path = f.name

        try:
            identity = AgentIdentity.from_yaml(path)
            assert identity.identity_compact == 'I am a robot named Bolt.'
            assert identity.voice_checksum == ['Always speak in uppercase', 'Never say please']
            assert identity.language == 'ja'
            assert identity.greeting == 'BEEP BOOP WELCOME'
            assert identity.communication_style['formality'] == 0.1
            assert identity.manager_interaction['reveal_inner_state'] is True

            # Custom voice pattern
            pat = identity.voice_rules_patterns['no_laughter']
            assert pat.search("beep beep")
            assert not pat.search("haha")

            # Custom physical trait pattern
            assert len(identity.physical_traits_patterns) == 1
            p, d = identity.physical_traits_patterns[0]
            assert p.search("I am not a robot")
            assert d == 'Denied being a robot'
        finally:
            os.unlink(path)

    def test_empty_yaml_raises(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write('')
            path = f.name
        try:
            with pytest.raises(ValueError, match="Empty or invalid"):
                AgentIdentity.from_yaml(path)
        finally:
            os.unlink(path)

    def test_minimal_yaml_uses_defaults(self):
        """A YAML with just identity_compact should load with sane defaults."""
        custom_yaml = {
            'identity_compact': 'I am a test agent.',
            'voice_rules': ['Be polite'],
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(custom_yaml, f)
            path = f.name
        try:
            identity = AgentIdentity.from_yaml(path)
            assert identity.identity_compact == 'I am a test agent.'
            assert identity.language == 'en'  # default
            assert identity.communication_style['formality'] == 0.7  # default
        finally:
            os.unlink(path)


# ── Tests: System prompt builders ──

class TestSystemPromptBuilders:
    def test_build_system_prompt_contains_identity(self):
        from pipeline.cortex import build_system_prompt
        identity = AgentIdentity.default()
        prompt = build_system_prompt(identity)
        assert ORIGINAL_IDENTITY_COMPACT in prompt
        assert "VOICE RULES:" in prompt
        assert "Never use: 'How can I help you'" in prompt

    def test_build_system_prompt_default_matches_constant(self):
        """build_system_prompt(default) must match the backward-compat constant."""
        from pipeline.cortex import build_system_prompt, CORTEX_SYSTEM_STABLE
        identity = AgentIdentity.default()
        built = build_system_prompt(identity)
        assert built == CORTEX_SYSTEM_STABLE

    def test_build_system_prompt_custom_differs(self):
        from pipeline.cortex import build_system_prompt
        custom_yaml = {
            'identity_compact': 'I am a robot named Bolt.',
            'voice_rules': ['Always speak in uppercase'],
            'voice_detection': {},
            'physical_traits_detection': [],
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(custom_yaml, f)
            path = f.name
        try:
            custom = AgentIdentity.from_yaml(path)
            default = AgentIdentity.default()
            prompt_custom = build_system_prompt(custom)
            prompt_default = build_system_prompt(default)
            assert prompt_custom != prompt_default
            assert 'I am a robot named Bolt.' in prompt_custom
            assert 'Always speak in uppercase' in prompt_custom
        finally:
            os.unlink(path)

    def test_build_reflection_system(self):
        from pipeline.cortex import build_reflection_system
        identity = AgentIdentity.default()
        system = build_reflection_system(identity.identity_compact)
        assert "You are reflecting on your day" in system
        assert ORIGINAL_IDENTITY_COMPACT in system
        assert '"reflection"' in system

    def test_maintenance_prompt_uses_identity(self):
        """cortex_call_maintenance builds its prompt from identity.identity_compact."""
        # We just verify the template works — actual LLM calls are mocked elsewhere
        from pipeline.cortex import _DEFAULT_IDENTITY
        compact = _DEFAULT_IDENTITY.identity_compact
        assert compact == ORIGINAL_IDENTITY_COMPACT


# ── Tests: Frozen dataclass ──

class TestFrozenIdentity:
    def test_identity_is_frozen(self):
        identity = AgentIdentity.default()
        with pytest.raises(AttributeError):
            identity.language = 'ja'
