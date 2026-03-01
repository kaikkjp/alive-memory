"""
preflight.py — Startup validation for the ALIVE engine.

Runs synchronously before db.init_db() in heartbeat_server.py.
Collects all errors and prints a numbered list with fix instructions.
Returns True if all checks pass, False otherwise.
"""

import importlib
import os
import socket
import sqlite3
import sys
from pathlib import Path


def _check_env_vars() -> list[str]:
    """Check required environment variables."""
    errors = []
    if not os.environ.get('OPENROUTER_API_KEY'):
        errors.append(
            "OPENROUTER_API_KEY not set.\n"
            "   Fix: export OPENROUTER_API_KEY='sk-or-v1-...'"
        )
    if not os.environ.get('SHOPKEEPER_SERVER_TOKEN'):
        errors.append(
            "SHOPKEEPER_SERVER_TOKEN not set.\n"
            "   Fix: export SHOPKEEPER_SERVER_TOKEN='$(openssl rand -hex 32)'"
        )
    return errors


def _check_python_version() -> list[str]:
    """Check Python >= 3.12."""
    if sys.version_info < (3, 12):
        return [
            f"Python {sys.version_info[0]}.{sys.version_info[1]} detected, "
            f"but 3.12+ is required.\n"
            f"   Fix: install Python 3.12 or newer"
        ]
    return []


def _check_packages() -> list[str]:
    """Check required packages are importable."""
    required = ['aiosqlite', 'yaml', 'httpx']
    errors = []
    for pkg in required:
        try:
            importlib.import_module(pkg)
        except ImportError:
            errors.append(
                f"Required package '{pkg}' not installed.\n"
                f"   Fix: pip install {pkg}"
            )
    return errors


def _check_port(port: int) -> list[str]:
    """Check if a port is already in use (socket probe, 0.5s timeout)."""
    if port <= 0:
        return []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            result = s.connect_ex(('127.0.0.1', port))
            if result == 0:
                return [
                    f"Port {port} is already in use.\n"
                    f"   Fix: stop the process using port {port}, or use a different port"
                ]
    except OSError:
        pass  # Socket error — port is likely free
    return []


def _check_config_dir() -> list[str]:
    """If AGENT_CONFIG_DIR is set, validate its structure."""
    config_dir = os.environ.get('AGENT_CONFIG_DIR')
    if not config_dir:
        return []

    errors = []
    config_path = Path(config_dir)

    if not config_path.is_dir():
        errors.append(
            f"AGENT_CONFIG_DIR '{config_dir}' does not exist or is not a directory.\n"
            f"   Fix: mkdir -p {config_dir}"
        )
        return errors  # Can't check further

    # Check identity.yaml
    identity_file = config_path / 'identity.yaml'
    if identity_file.exists():
        try:
            import yaml
            with open(identity_file) as f:
                yaml.safe_load(f)
        except Exception as e:
            errors.append(
                f"identity.yaml failed to parse: {e}\n"
                f"   Fix: check YAML syntax in {identity_file}"
            )
    # identity.yaml is optional — agent can start without it

    # Check alive_config.yaml
    config_file = config_path / 'alive_config.yaml'
    if config_file.exists():
        try:
            import yaml
            with open(config_file) as f:
                yaml.safe_load(f)
        except Exception as e:
            errors.append(
                f"alive_config.yaml failed to parse: {e}\n"
                f"   Fix: check YAML syntax in {config_file}"
            )

    # Check db/ directory is writable
    db_dir = config_path / 'db'
    if db_dir.exists():
        if not os.access(db_dir, os.W_OK):
            errors.append(
                f"DB directory '{db_dir}' is not writable.\n"
                f"   Fix: chmod 755 {db_dir} && chown 1000:1000 {db_dir}"
            )
    else:
        # db/ not existing is fine — it will be created

        pass

    return errors


def _check_db_lock() -> list[str]:
    """Check if the DB file is locked by another process."""
    # Determine DB path
    config_dir = os.environ.get('AGENT_CONFIG_DIR')
    agent_id = os.environ.get('AGENT_ID', 'default')

    if config_dir:
        db_path = Path(config_dir) / 'db' / f'{agent_id}.db'
    else:
        db_path = Path(os.environ.get('SHOPKEEPER_DB_PATH', 'data/shopkeeper.db'))

    if not db_path.exists():
        return []  # No DB yet — will be created

    try:
        conn = sqlite3.connect(str(db_path), timeout=1.0)
        # Try to get an exclusive lock
        conn.execute("BEGIN EXCLUSIVE")
        conn.execute("ROLLBACK")
        conn.close()
    except sqlite3.OperationalError as e:
        if 'locked' in str(e).lower() or 'busy' in str(e).lower():
            return [
                f"Database '{db_path}' is locked by another process.\n"
                f"   Fix: stop other instances, or check for stale lock files"
            ]
    except Exception:
        pass  # Other errors — let db.init_db() handle them

    return []


def run_preflight(http_port: int = 0, ws_port: int = 0) -> bool:
    """
    Run all preflight checks. Returns True if all pass.

    Args:
        http_port: HTTP server port to check (0 = skip)
        ws_port: WebSocket server port to check (0 = skip)
    """
    all_errors: list[str] = []

    all_errors.extend(_check_env_vars())
    all_errors.extend(_check_python_version())
    all_errors.extend(_check_packages())
    all_errors.extend(_check_port(http_port))
    if ws_port and ws_port != http_port:
        all_errors.extend(_check_port(ws_port))
    all_errors.extend(_check_config_dir())
    all_errors.extend(_check_db_lock())

    if not all_errors:
        print("  [Preflight] OK")
        return True

    print(f"\n  [Preflight] {len(all_errors)} error(s) found:\n")
    for i, err in enumerate(all_errors, 1):
        print(f"  {i}. {err}")
    print()

    return False
