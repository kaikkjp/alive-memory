"""Tests for config/identity.py — character identity configuration."""

from config.identity import IDENTITY_COMPACT, VOICE_CHECKSUM


class TestIdentityCompact:
    """IDENTITY_COMPACT contains essential character traits."""

    def test_not_empty(self):
        assert len(IDENTITY_COMPACT) > 0

    def test_mentions_glasses(self):
        assert 'glasses' in IDENTITY_COMPACT.lower()

    def test_mentions_short_hair(self):
        assert 'short hair' in IDENTITY_COMPACT.lower()

    def test_no_exclamation_rule(self):
        assert 'exclamation' in IDENTITY_COMPACT.lower()

    def test_not_an_assistant(self):
        assert 'not helpful' in IDENTITY_COMPACT.lower() or 'not an assistant' in IDENTITY_COMPACT.lower()


class TestVoiceChecksum:
    """VOICE_CHECKSUM contains the banned-phrase rules."""

    def test_is_list(self):
        assert isinstance(VOICE_CHECKSUM, list)

    def test_has_entries(self):
        assert len(VOICE_CHECKSUM) > 0

    def test_bans_assistant_phrases(self):
        combined = ' '.join(VOICE_CHECKSUM).lower()
        assert 'how can i help' in combined
        assert 'feel free to' in combined
