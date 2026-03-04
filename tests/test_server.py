"""Tests for the alive-memory REST API server (three-tier architecture)."""

from __future__ import annotations

import os
import tempfile

import pytest

pytest.importorskip("fastapi", reason="server tests require pip install alive-memory[server]")
pytest.importorskip("httpx", reason="server tests require httpx")

from httpx import ASGITransport, AsyncClient

from alive_memory import AliveMemory
from alive_memory.server.app import create_app
from alive_memory.server.config import ServerConfig


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def tmp_memory_dir():
    d = tempfile.mkdtemp(prefix="alive_server_test_")
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def server_config(tmp_db):
    config = ServerConfig()
    config.db_path = tmp_db
    config.api_key = None
    return config


@pytest.fixture
async def client(server_config, tmp_memory_dir):
    app = create_app(server_config)
    memory = AliveMemory(
        storage=server_config.db_path,
        memory_dir=tmp_memory_dir,
    )
    await memory.initialize()
    app.state.memory = memory
    app.state.config = server_config
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await memory.close()


# ── Health ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


# ── Intake + Recall ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_intake_and_recall(client):
    # Intake with high salience override
    resp = await client.post("/intake", json={
        "event_type": "conversation",
        "content": "The weather is beautiful today with sunshine and clear skies everywhere",
        "metadata": {"salience": 0.95},
    })
    assert resp.status_code == 200
    moment = resp.json()
    assert moment is not None
    assert moment["content"].startswith("The weather is beautiful")
    assert moment["event_type"] == "conversation"
    assert moment["salience"] == 0.95

    # Consolidate to push to hot memory
    await client.post("/consolidate", json={"depth": "full"})

    # Recall from hot memory
    resp = await client.post("/recall", json={"query": "weather sunshine"})
    assert resp.status_code == 200
    ctx = resp.json()
    assert "journal_entries" in ctx
    assert "total_hits" in ctx


@pytest.mark.asyncio
async def test_intake_returns_null_for_low_salience(client):
    resp = await client.post("/intake", json={
        "event_type": "system",
        "content": "ok",
    })
    assert resp.status_code == 200
    # Low salience system event should return null
    assert resp.json() is None


@pytest.mark.asyncio
async def test_intake_with_metadata(client):
    resp = await client.post("/intake", json={
        "event_type": "observation",
        "content": "A cat sitting on the roof looking at birds below",
        "metadata": {"location": "home", "salience": 0.9},
    })
    assert resp.status_code == 200
    moment = resp.json()
    assert moment is not None
    assert moment["metadata"]["location"] == "home"


# ── State ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_state(client):
    resp = await client.get("/state")
    assert resp.status_code == 200
    state = resp.json()
    assert "mood" in state
    assert "drives" in state
    assert "energy" in state
    assert state["mood"]["word"] == "neutral"


# ── Identity ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_identity(client):
    resp = await client.get("/identity")
    assert resp.status_code == 200
    identity = resp.json()
    assert "traits" in identity
    assert "behavioral_summary" in identity
    assert identity["version"] == 0


# ── Drives ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_drive(client):
    resp = await client.post("/drives/curiosity", json={"delta": 0.2})
    assert resp.status_code == 200
    drives = resp.json()
    assert drives["curiosity"] > 0.5


# ── Backstory ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inject_backstory(client):
    resp = await client.post("/backstory", json={
        "content": "I was born in a digital garden.",
        "title": "origin",
    })
    assert resp.status_code == 200
    moment = resp.json()
    assert moment["content"] == "I was born in a digital garden."
    assert moment["event_type"] == "system"
    assert moment["salience"] == 1.0
    assert moment["metadata"]["origin"] == "injected"


# ── Consolidation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consolidate(client):
    # Add some moments
    await client.post("/intake", json={
        "event_type": "conversation",
        "content": "First memory for consolidation is about interesting philosophical topics",
        "metadata": {"salience": 0.9},
    })
    await client.post("/intake", json={
        "event_type": "conversation",
        "content": "Second memory for consolidation discusses quantum computing breakthroughs",
        "metadata": {"salience": 0.9},
    })

    resp = await client.post("/consolidate", json={"depth": "nap"})
    assert resp.status_code == 200
    report = resp.json()
    assert "moments_processed" in report
    assert "duration_ms" in report
    assert report["depth"] == "nap"


# ── Auth ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_required():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tmp_dir = tempfile.mkdtemp(prefix="alive_auth_test_")
    try:
        config = ServerConfig()
        config.db_path = path
        config.api_key = "secret-key-123"

        app = create_app(config)
        memory = AliveMemory(storage=path, memory_dir=tmp_dir)
        await memory.initialize()
        app.state.memory = memory
        app.state.config = config

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Health always works
            resp = await ac.get("/health")
            assert resp.status_code == 200

            # Other endpoints require auth
            resp = await ac.get("/state")
            assert resp.status_code == 401

            # With wrong key
            resp = await ac.get("/state", headers={"Authorization": "Bearer wrong"})
            assert resp.status_code == 401

            # With correct key
            resp = await ac.get(
                "/state",
                headers={"Authorization": "Bearer secret-key-123"},
            )
            assert resp.status_code == 200

        await memory.close()
    finally:
        os.unlink(path)
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
