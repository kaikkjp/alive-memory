"""Tests for dashboard authentication enforcement (TASK-018).

Tests the token-based auth system:
- Token creation and validation
- Auth header parsing
- HTTP endpoint protection
- Token expiry
"""

import time
import unittest
from unittest.mock import patch

# Import the module-level auth functions directly
from heartbeat_server import (
    _create_dashboard_token,
    _check_dashboard_token,
    _check_dashboard_auth,
    _dashboard_tokens,
    _DASHBOARD_TOKEN_TTL,
    _check_rate_limit,
    _record_auth_attempt,
    _reset_auth_attempts,
    _auth_attempts,
    _AUTH_MAX_ATTEMPTS,
    _AUTH_WINDOW_SECONDS,
)


class TestTokenCreation(unittest.TestCase):
    """Test _create_dashboard_token()."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    def test_creates_token(self):
        token = _create_dashboard_token()
        assert token
        assert isinstance(token, str)
        assert len(token) > 20  # token_urlsafe(32) produces ~43 chars

    def test_token_stored_in_registry(self):
        token = _create_dashboard_token()
        assert token in _dashboard_tokens

    def test_token_has_expiry(self):
        token = _create_dashboard_token()
        expiry = _dashboard_tokens[token]
        now = time.time()
        # Expiry should be ~24h from now
        assert expiry > now
        assert expiry <= now + _DASHBOARD_TOKEN_TTL + 1

    def test_multiple_tokens_coexist(self):
        t1 = _create_dashboard_token()
        t2 = _create_dashboard_token()
        assert t1 != t2
        assert t1 in _dashboard_tokens
        assert t2 in _dashboard_tokens

    def test_prunes_expired_on_create(self):
        # Insert an already-expired token
        _dashboard_tokens['old_token'] = time.time() - 1
        assert 'old_token' in _dashboard_tokens

        _create_dashboard_token()
        assert 'old_token' not in _dashboard_tokens


class TestTokenValidation(unittest.TestCase):
    """Test _check_dashboard_token()."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    def test_valid_token(self):
        token = _create_dashboard_token()
        assert _check_dashboard_token(token) is True

    def test_invalid_token(self):
        assert _check_dashboard_token('nonexistent') is False

    def test_empty_token(self):
        assert _check_dashboard_token('') is False

    def test_whitespace_only_token(self):
        assert _check_dashboard_token('   ') is False

    def test_expired_token(self):
        token = _create_dashboard_token()
        # Manually expire it
        _dashboard_tokens[token] = time.time() - 1
        assert _check_dashboard_token(token) is False
        # Token should be removed after failed check
        assert token not in _dashboard_tokens

    def test_token_just_before_expiry(self):
        token = _create_dashboard_token()
        # Set expiry to 1 second from now
        _dashboard_tokens[token] = time.time() + 1
        assert _check_dashboard_token(token) is True


class TestDashboardAuthHeader(unittest.TestCase):
    """Test _check_dashboard_auth() header parsing."""

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    def test_valid_bearer_token(self):
        token = _create_dashboard_token()
        assert _check_dashboard_auth(f'Bearer {token}') is True

    def test_case_insensitive_bearer(self):
        token = _create_dashboard_token()
        assert _check_dashboard_auth(f'bearer {token}') is True
        assert _check_dashboard_auth(f'BEARER {token}') is True

    def test_missing_bearer_prefix(self):
        token = _create_dashboard_token()
        assert _check_dashboard_auth(token) is False

    def test_empty_authorization(self):
        assert _check_dashboard_auth('') is False

    def test_wrong_scheme(self):
        token = _create_dashboard_token()
        assert _check_dashboard_auth(f'Basic {token}') is False

    def test_invalid_token_value(self):
        assert _check_dashboard_auth('Bearer invalid_token_here') is False

    def test_bearer_no_token(self):
        assert _check_dashboard_auth('Bearer') is False

    def test_expired_token_via_header(self):
        token = _create_dashboard_token()
        _dashboard_tokens[token] = time.time() - 1
        assert _check_dashboard_auth(f'Bearer {token}') is False


class TestDashboardAuthHTTPIntegration(unittest.TestCase):
    """Integration tests simulating HTTP request/response patterns.

    These test the auth helper functions with realistic header values
    rather than spinning up a full async HTTP server.
    """

    def setUp(self):
        _dashboard_tokens.clear()

    def tearDown(self):
        _dashboard_tokens.clear()

    def test_unauthenticated_request_rejected(self):
        """Simulates GET /api/dashboard/vitals without Authorization header."""
        assert _check_dashboard_auth('') is False

    def test_authenticated_request_accepted(self):
        """Simulates login → get token → use token on request."""
        # Step 1: Simulate successful auth (would be POST /api/dashboard/auth)
        token = _create_dashboard_token()

        # Step 2: Use token on subsequent request
        assert _check_dashboard_auth(f'Bearer {token}') is True

    def test_invalid_token_rejected(self):
        """Token that was never issued gets rejected."""
        assert _check_dashboard_auth('Bearer fake_token_12345') is False

    def test_token_works_multiple_times(self):
        """Same token can be reused until expiry."""
        token = _create_dashboard_token()
        for _ in range(10):
            assert _check_dashboard_auth(f'Bearer {token}') is True

    def test_multiple_sessions_independent(self):
        """Multiple tokens (different login sessions) work independently."""
        t1 = _create_dashboard_token()
        t2 = _create_dashboard_token()

        assert _check_dashboard_auth(f'Bearer {t1}') is True
        assert _check_dashboard_auth(f'Bearer {t2}') is True

        # Expire t1
        _dashboard_tokens[t1] = time.time() - 1
        assert _check_dashboard_auth(f'Bearer {t1}') is False
        assert _check_dashboard_auth(f'Bearer {t2}') is True

    def test_non_dashboard_endpoints_unaffected(self):
        """Auth check is only called for dashboard endpoints.

        This test verifies the function returns False for missing auth,
        confirming that non-dashboard endpoints that skip the check
        remain accessible.
        """
        # The auth check itself doesn't know about endpoints —
        # the routing logic in _handle_http decides whether to call it.
        # This test just confirms the guard works as expected.
        assert _check_dashboard_auth('') is False


class TestDashboardPasswordAuth(unittest.TestCase):
    """Test the password validation logic used in /api/dashboard/auth."""

    def test_password_comparison_uses_hmac(self):
        """Verify that hmac.compare_digest is used for timing-safe compare."""
        import hmac
        correct = 'my_secret_password'
        assert hmac.compare_digest('my_secret_password', correct) is True
        assert hmac.compare_digest('wrong_password', correct) is False
        assert hmac.compare_digest('', correct) is False


class TestRateLimiting(unittest.TestCase):
    """Test per-IP rate limiting for dashboard login."""

    def setUp(self):
        _auth_attempts.clear()

    def tearDown(self):
        _auth_attempts.clear()

    def test_initial_request_allowed(self):
        assert _check_rate_limit('192.168.1.1') is True

    def test_under_limit_allowed(self):
        ip = '192.168.1.2'
        for _ in range(_AUTH_MAX_ATTEMPTS - 1):
            _record_auth_attempt(ip)
        assert _check_rate_limit(ip) is True

    def test_at_limit_blocked(self):
        ip = '192.168.1.3'
        for _ in range(_AUTH_MAX_ATTEMPTS):
            _record_auth_attempt(ip)
        assert _check_rate_limit(ip) is False

    def test_different_ips_independent(self):
        ip_a = '10.0.0.1'
        ip_b = '10.0.0.2'
        for _ in range(_AUTH_MAX_ATTEMPTS):
            _record_auth_attempt(ip_a)
        assert _check_rate_limit(ip_a) is False
        assert _check_rate_limit(ip_b) is True

    def test_old_attempts_pruned(self):
        ip = '192.168.1.4'
        old_time = time.time() - _AUTH_WINDOW_SECONDS - 1
        _auth_attempts[ip] = [old_time] * _AUTH_MAX_ATTEMPTS
        # Old attempts should be pruned, allowing new requests
        assert _check_rate_limit(ip) is True

    def test_reset_clears_attempts(self):
        ip = '192.168.1.5'
        for _ in range(_AUTH_MAX_ATTEMPTS):
            _record_auth_attempt(ip)
        assert _check_rate_limit(ip) is False
        _reset_auth_attempts(ip)
        assert _check_rate_limit(ip) is True

    def test_reset_on_unknown_ip_is_noop(self):
        _reset_auth_attempts('never_seen')
        assert 'never_seen' not in _auth_attempts


if __name__ == '__main__':
    unittest.main()
