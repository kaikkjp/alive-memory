"""Tests for runtime_context lazy metadata resolution."""

from __future__ import annotations

import importlib
from unittest.mock import patch


def test_config_hash_resolved_lazily(monkeypatch):
    """When CONFIG_HASH is unset, default hash is computed on first access."""
    monkeypatch.delenv("CONFIG_HASH", raising=False)
    monkeypatch.setenv("GIT_COMMIT_HASH", "test-commit")

    import runtime_context

    rc = importlib.reload(runtime_context)
    assert rc._run_meta.config_hash == ""

    with patch.object(rc, "_default_config_hash", return_value="cfg-lazy") as mock_default:
        meta = rc.get_run_metadata()
        assert meta.config_hash == "cfg-lazy"
        mock_default.assert_called_once()

        # Cached after first resolution.
        meta2 = rc.get_run_metadata()
        assert meta2.config_hash == "cfg-lazy"
        mock_default.assert_called_once()


def test_env_config_hash_skips_default_hash(monkeypatch):
    """When CONFIG_HASH is provided, default hash helper is not called."""
    monkeypatch.setenv("CONFIG_HASH", "cfg-from-env")
    monkeypatch.setenv("GIT_COMMIT_HASH", "test-commit")

    import runtime_context

    rc = importlib.reload(runtime_context)
    assert rc._run_meta.config_hash == "cfg-from-env"

    with patch.object(rc, "_default_config_hash", side_effect=AssertionError("should not run")):
        meta = rc.get_run_metadata()
        assert meta.config_hash == "cfg-from-env"
