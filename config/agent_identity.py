"""AgentIdentity — data-driven identity loaded from YAML.

TASK-095 Phase 1: Extracts the hardcoded identity from config/identity.py
into a YAML-backed class. Each agent can have its own identity.yaml.

Usage:
    from config.agent_identity import AgentIdentity

    # Default (original Shopkeeper)
    identity = AgentIdentity.default()

    # Custom agent
    identity = AgentIdentity.from_yaml('/path/to/identity.yaml')

    # Build system prompt
    from pipeline.cortex import build_system_prompt
    prompt = build_system_prompt(identity)
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass(frozen=True)
class AgentIdentity:
    """Immutable identity for an ALIVE agent."""

    identity_compact: str
    voice_checksum: list[str]
    voice_rules_patterns: dict = field(repr=False)
    physical_traits_patterns: list = field(repr=False)

    # Tier 1 manager-facing config
    communication_style: dict = field(default_factory=lambda: {
        'formality': 0.7, 'verbosity': 0.4, 'emoji_usage': 0.0,
    })
    language: str = 'en'
    domain_context: str = ''
    greeting: str = ''
    boundaries: list[str] = field(default_factory=list)
    manager_interaction: dict = field(default_factory=lambda: {
        'reveal_inner_state': False, 'accept_instructions': False,
    })

    # Capabilities gating (TASK-095 v2)
    # None  = key absent from YAML → all actions allowed (Shopkeeper backward compat)
    # []    = key present, empty   → no actions allowed (digital lifeform default)
    # [...] = key present, list    → only listed actions pass basal ganglia Gate 2
    actions_enabled: Optional[list[str]] = None

    @classmethod
    def from_yaml(cls, path: str) -> 'AgentIdentity':
        """Load identity from a YAML file."""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Empty or invalid identity YAML: {path}")

        identity_compact = data.get('identity_compact', '').rstrip('\n')

        voice_rules = data.get('voice_rules', [])

        # Compile voice detection patterns
        voice_detection = data.get('voice_detection', {})
        voice_rules_patterns = _compile_voice_patterns(voice_detection)

        # Compile physical traits patterns
        physical_raw = data.get('physical_traits_detection', [])
        physical_traits_patterns = _compile_physical_patterns(physical_raw)

        # actions_enabled: None = absent (all allowed), [] = empty (none), list = filter
        _SENTINEL = object()
        raw_actions = data.get('actions_enabled', _SENTINEL)
        if raw_actions is _SENTINEL:
            actions_enabled = None  # Key absent → backward compat, all allowed
        else:
            actions_enabled = list(raw_actions) if raw_actions else []

        return cls(
            identity_compact=identity_compact,
            voice_checksum=voice_rules,
            voice_rules_patterns=voice_rules_patterns,
            physical_traits_patterns=physical_traits_patterns,
            communication_style=data.get('communication_style', {
                'formality': 0.7, 'verbosity': 0.4, 'emoji_usage': 0.0,
            }),
            language=data.get('language', 'en'),
            domain_context=data.get('domain_context', '') or '',
            greeting=data.get('greeting', '') or '',
            boundaries=data.get('boundaries', []) or [],
            manager_interaction=data.get('manager_interaction', {
                'reveal_inner_state': False, 'accept_instructions': False,
            }),
            actions_enabled=actions_enabled,
        )

    @classmethod
    def default(cls) -> 'AgentIdentity':
        """Load the default Shopkeeper identity."""
        default_path = os.path.join(os.path.dirname(__file__), 'default_identity.yaml')
        return cls.from_yaml(default_path)

    @classmethod
    def digital_lifeform(cls) -> 'AgentIdentity':
        """Load the digital lifeform blank-slate identity (TASK-095 v2)."""
        dl_path = os.path.join(os.path.dirname(__file__), 'default_digital_lifeform.yaml')
        return cls.from_yaml(dl_path)


# ── Module-level singleton for backward compat ──

_default_identity: Optional[AgentIdentity] = None


def get_default_identity() -> AgentIdentity:
    """Get the default identity singleton (lazy-loaded)."""
    global _default_identity
    if _default_identity is None:
        _default_identity = AgentIdentity.default()
    return _default_identity


# ── Pattern compilation helpers ──

def _compile_voice_patterns(voice_detection: dict) -> dict:
    """Compile voice detection config into regex patterns dict."""
    patterns = {}

    # no_laughter
    laughter_pat = voice_detection.get('no_laughter_pattern')
    if laughter_pat:
        patterns['no_laughter'] = re.compile(laughter_pat, re.IGNORECASE)
    else:
        patterns['no_laughter'] = re.compile(r'\b(?:haha+|lol+)\b', re.IGNORECASE)

    # no_exclamation_unless_surprised — checked with expression context, not a regex
    patterns['no_exclamation_unless_surprised'] = voice_detection.get(
        'no_exclamation_unless_surprised'
    )

    # sentence_caps
    caps = voice_detection.get('sentence_caps', {})
    patterns['sentence_caps'] = caps if caps else {'stranger': 3, 'returner': 5, 'regular': 5}

    return patterns


_RE_FLAGS = {
    'IGNORECASE': re.IGNORECASE,
    'I': re.IGNORECASE,
    'MULTILINE': re.MULTILINE,
    'M': re.MULTILINE,
    'DOTALL': re.DOTALL,
    'S': re.DOTALL,
}


def _compile_physical_patterns(raw: list) -> list:
    """Compile physical traits detection patterns from YAML config."""
    result = []
    for entry in raw:
        pattern_str = entry.get('pattern', '')
        flags_str = entry.get('flags', '')
        description = entry.get('description', '')

        flags = 0
        if flags_str:
            for flag_name in flags_str.split('|'):
                flag_name = flag_name.strip()
                flags |= _RE_FLAGS.get(flag_name, 0)

        compiled = re.compile(pattern_str, flags)
        result.append((compiled, description))

    return result
