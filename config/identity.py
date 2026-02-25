"""Backward-compatible identity constants.

TASK-095: This module is now a thin wrapper around AgentIdentity.
All constants are loaded from config/default_identity.yaml via the
AgentIdentity class. Existing importers continue working unchanged.

For new code, use config.agent_identity.AgentIdentity directly.
"""

from config.agent_identity import get_default_identity

_default = get_default_identity()

IDENTITY_COMPACT = _default.identity_compact
VOICE_CHECKSUM = _default.voice_checksum
VOICE_RULES_PATTERNS = _default.voice_rules_patterns
PHYSICAL_TRAITS_PATTERNS = _default.physical_traits_patterns
