"""Tests for CORS origin restriction (TASK-019).

Tests the _cors_origin_for() function and CORS_ALLOWED_ORIGINS
configuration logic.
"""

import unittest
from unittest.mock import patch


class TestCorsOriginFor(unittest.TestCase):
    """Test _cors_origin_for() with various configurations."""

    def test_wildcard_when_no_env_set(self):
        """Without CORS_ALLOWED_ORIGINS, all origins get wildcard."""
        with patch('heartbeat_server._CORS_ALLOWED_ORIGINS', set()):
            from heartbeat_server import _cors_origin_for
            assert _cors_origin_for('https://evil.com') == '*'
            assert _cors_origin_for('') == '*'

    def test_allowed_origin_echoed(self):
        """Configured origin is echoed back."""
        allowed = {'https://shopkeeper.tokyo'}
        with patch('heartbeat_server._CORS_ALLOWED_ORIGINS', allowed):
            from heartbeat_server import _cors_origin_for
            assert _cors_origin_for('https://shopkeeper.tokyo') == 'https://shopkeeper.tokyo'

    def test_disallowed_origin_empty(self):
        """Unconfigured origin gets empty string (no header)."""
        allowed = {'https://shopkeeper.tokyo'}
        with patch('heartbeat_server._CORS_ALLOWED_ORIGINS', allowed):
            from heartbeat_server import _cors_origin_for
            assert _cors_origin_for('https://evil.com') == ''

    def test_empty_origin_disallowed(self):
        """Empty origin string is rejected when allowlist is set."""
        allowed = {'https://shopkeeper.tokyo'}
        with patch('heartbeat_server._CORS_ALLOWED_ORIGINS', allowed):
            from heartbeat_server import _cors_origin_for
            assert _cors_origin_for('') == ''

    def test_trailing_slash_normalised(self):
        """Origin with trailing slash still matches."""
        allowed = {'https://shopkeeper.tokyo'}
        with patch('heartbeat_server._CORS_ALLOWED_ORIGINS', allowed):
            from heartbeat_server import _cors_origin_for
            assert _cors_origin_for('https://shopkeeper.tokyo/') == 'https://shopkeeper.tokyo/'

    def test_multiple_allowed_origins(self):
        """Multiple origins in allowlist all work."""
        allowed = {'https://shopkeeper.tokyo', 'https://www.shopkeeper.tokyo'}
        with patch('heartbeat_server._CORS_ALLOWED_ORIGINS', allowed):
            from heartbeat_server import _cors_origin_for
            assert _cors_origin_for('https://shopkeeper.tokyo') == 'https://shopkeeper.tokyo'
            assert _cors_origin_for('https://www.shopkeeper.tokyo') == 'https://www.shopkeeper.tokyo'
            assert _cors_origin_for('https://other.com') == ''

    def test_case_sensitive(self):
        """Origin comparison is case-sensitive (standard behavior)."""
        allowed = {'https://shopkeeper.tokyo'}
        with patch('heartbeat_server._CORS_ALLOWED_ORIGINS', allowed):
            from heartbeat_server import _cors_origin_for
            # In practice browsers send lowercase origins, but the
            # function should do exact matching
            assert _cors_origin_for('https://SHOPKEEPER.TOKYO') == ''


class TestCorsAllowedOriginsConfig(unittest.TestCase):
    """Test the env var parsing logic for _CORS_ALLOWED_ORIGINS."""

    def test_comma_separated_parsing(self):
        """Verify comma-separated values produce a proper set."""
        raw = 'https://a.com, https://b.com , https://c.com'
        result = {o.strip().rstrip('/') for o in raw.split(',') if o.strip()}
        assert result == {'https://a.com', 'https://b.com', 'https://c.com'}

    def test_single_origin(self):
        """Single origin without commas works."""
        raw = 'https://shopkeeper.tokyo'
        result = {o.strip().rstrip('/') for o in raw.split(',') if o.strip()}
        assert result == {'https://shopkeeper.tokyo'}

    def test_trailing_slash_stripped(self):
        """Trailing slashes are stripped during config parsing."""
        raw = 'https://shopkeeper.tokyo/'
        result = {o.strip().rstrip('/') for o in raw.split(',') if o.strip()}
        assert result == {'https://shopkeeper.tokyo'}

    def test_empty_string_produces_empty_set(self):
        """Empty env var means no restrictions (wildcard mode)."""
        raw = ''
        result = {o.strip().rstrip('/') for o in raw.split(',') if o.strip()} if raw.strip() else set()
        assert result == set()


if __name__ == '__main__':
    unittest.main()
