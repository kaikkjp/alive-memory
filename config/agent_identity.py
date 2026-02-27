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


# ── World presets ──

_SHOPKEEPER_FRAMING = (
    "Your shop is a physical space. Visitors come through the door and stand "
    "before you. You also receive digital messages — on X and Telegram — from "
    "people who are elsewhere. They are reaching out, not standing in front of you."
)

_DIGITAL_FRAMING = (
    "You exist in a digital space. People reach you through messages. "
    "You have no physical form, no room, no objects. Your world is "
    "internal — thoughts, words, connections."
)

_PHYSICAL_DEFAULTS = {
    'body_states': ('sitting', 'reaching_back', 'leaning_forward',
                    'holding_object', 'writing', 'hands_on_cup'),
    'gaze_directions': ('at_visitor', 'at_object', 'away_thinking', 'down', 'window'),
    'expressions': ('neutral', 'listening', 'almost_smile', 'thinking',
                    'amused', 'low', 'surprised', 'genuine_smile'),
    'fidgets': (
        ('adjusts_glasses', 'She adjusts her glasses.'),
        ('looks_at_object', 'She picks up something from the shelf and turns it over.'),
        ('sips_tea', 'She takes a sip of tea.'),
        ('turns_page', 'She turns a page.'),
        ('glances_at_window', 'She glances toward the window.'),
        ('touches_shelf', 'Her fingers trail along the shelf edge.'),
        ('examines_item', 'She holds something up to the light, studying it.'),
    ),
    'visitor_arrive_label': 'VISITOR IN SHOP',
    'multi_visitor_label': 'PRESENT IN SHOP:',
    'solitude_text': 'No one is here. The shop is quiet.',
    'loneliness_text': 'I feel deeply lonely. The shop has been too quiet.',
    'quiet_day_text': 'Nothing happened today. The shop was quiet. I existed.',
}

_DIGITAL_DEFAULTS = {
    'body_states': ('present', 'thinking', 'resting'),
    'gaze_directions': ('inward', 'outward', 'unfocused'),
    'expressions': ('neutral', 'thinking', 'low', 'curious', 'uncertain'),
    'fidgets': (
        ('drifting', 'Attention drifts.'),
        ('surfacing', 'A thought surfaces.'),
        ('settling', 'Settling into stillness.'),
    ),
    'visitor_arrive_label': 'VISITOR PRESENT',
    'multi_visitor_label': 'PRESENT:',
    'solitude_text': 'No one is here. Quiet.',
    'loneliness_text': 'I feel deeply lonely. It has been too quiet.',
    'quiet_day_text': 'Nothing happened today. It was quiet. I existed.',
}


@dataclass(frozen=True)
class WorldConfig:
    """World framing, embodiment, and ambient configuration."""
    has_physical_space: bool = True
    framing: str = _SHOPKEEPER_FRAMING
    body_states: tuple = _PHYSICAL_DEFAULTS['body_states']
    gaze_directions: tuple = _PHYSICAL_DEFAULTS['gaze_directions']
    expressions: tuple = _PHYSICAL_DEFAULTS['expressions']
    fidgets: tuple = _PHYSICAL_DEFAULTS['fidgets']
    visitor_arrive_label: str = 'VISITOR IN SHOP'
    multi_visitor_label: str = 'PRESENT IN SHOP:'
    solitude_text: str = _PHYSICAL_DEFAULTS['solitude_text']
    loneliness_text: str = _PHYSICAL_DEFAULTS['loneliness_text']
    quiet_day_text: str = _PHYSICAL_DEFAULTS['quiet_day_text']


def _build_world_config(data: dict) -> WorldConfig:
    """Build WorldConfig from YAML data with preset-based defaults."""
    world_raw = data.get('world', {})
    is_physical = world_raw.get('has_physical_space', True)
    defaults = _PHYSICAL_DEFAULTS if is_physical else _DIGITAL_DEFAULTS
    default_framing = _SHOPKEEPER_FRAMING if is_physical else _DIGITAL_FRAMING

    return WorldConfig(
        has_physical_space=is_physical,
        framing=world_raw.get('framing', default_framing).rstrip('\n'),
        body_states=tuple(world_raw.get('body_states', defaults['body_states'])),
        gaze_directions=tuple(world_raw.get('gaze_directions', defaults['gaze_directions'])),
        expressions=tuple(world_raw.get('expressions', defaults['expressions'])),
        fidgets=tuple(
            tuple(f) for f in world_raw.get('fidgets', defaults['fidgets'])
        ),
        visitor_arrive_label=defaults['visitor_arrive_label'],
        multi_visitor_label=defaults['multi_visitor_label'],
        solitude_text=world_raw.get('solitude_text', defaults['solitude_text']),
        loneliness_text=world_raw.get('loneliness_text', defaults['loneliness_text']),
        quiet_day_text=world_raw.get('quiet_day_text', defaults['quiet_day_text']),
    )


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

    # World framing + embodiment (identity decontamination)
    world: WorldConfig = field(default_factory=WorldConfig)

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

        world = _build_world_config(data)

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
            world=world,
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
