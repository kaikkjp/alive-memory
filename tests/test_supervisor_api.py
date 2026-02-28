"""Tests for supervisor.api — HTTP API endpoints."""

import importlib
import json
import sys
import types
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

# Fix: test_backfill_embeddings may install a SimpleNamespace stub for aiohttp
# before this module is collected. Restore the real module if that happened.
_aiohttp_mod = sys.modules.get("aiohttp")
if isinstance(_aiohttp_mod, types.SimpleNamespace):
    del sys.modules["aiohttp"]
    # Also clear submodules that might have been partially loaded
    for key in list(sys.modules):
        if key.startswith("aiohttp."):
            del sys.modules[key]

import aiohttp  # noqa: E402 — must come after stub cleanup
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient

from supervisor.api import ApiServer
from supervisor.health_monitor import HealthMonitor
from supervisor.nginx_manager import NginxManager
from supervisor.registry import Registry


@pytest_asyncio.fixture
async def registry(tmp_path):
    db_path = str(tmp_path / "test_supervisor.db")
    reg = Registry(db_path=db_path)
    await reg.init_db()
    yield reg
    await reg.close()


@pytest_asyncio.fixture
async def api_client(registry, tmp_path):
    """Create an aiohttp test client for the API."""
    health_monitor = HealthMonitor(registry)
    nginx_manager = NginxManager(conf_path=str(tmp_path / "nonexistent"))  # dev mode
    api = ApiServer(registry, health_monitor, nginx_manager)
    app = api.create_app()

    # Clear SUPERVISOR_TOKEN for tests (no auth)
    with patch("supervisor.api.SUPERVISOR_TOKEN", ""):
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        yield client
        await client.close()


# ---------------------------------------------------------------------------
# System endpoints
# ---------------------------------------------------------------------------

class TestSystemEndpoints:
    @pytest.mark.asyncio
    async def test_supervisor_health(self, api_client):
        resp = await api_client.get("/api/v1/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert data["total_pods"] == 0


# ---------------------------------------------------------------------------
# Pod CRUD
# ---------------------------------------------------------------------------

class TestPodCRUD:
    @pytest.mark.asyncio
    async def test_list_empty(self, api_client):
        resp = await api_client.get("/api/v1/pods")
        assert resp.status == 200
        data = await resp.json()
        assert data["pods"] == []

    @pytest.mark.asyncio
    async def test_create_pod(self, api_client):
        with patch("supervisor.docker_manager.create_pod", new_callable=AsyncMock, return_value="abc123"), \
             patch.object(HealthMonitor, "check_pod_health", return_value=True):
            resp = await api_client.post("/api/v1/pods", json={
                "id": "test-pod",
                "name": "Test Pod",
                "openrouter_key": "sk-or-test",
                "manager_id": "mgr-1",
            })

        assert resp.status == 201
        data = await resp.json()
        assert data["pod"]["id"] == "test-pod"
        assert data["pod"]["state"] == "running"
        assert data["pod"]["port"] == 9001

    @pytest.mark.asyncio
    async def test_create_pod_missing_fields(self, api_client):
        resp = await api_client.post("/api/v1/pods", json={
            "name": "Test Pod",
        })
        assert resp.status == 400
        data = await resp.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_create_duplicate_pod(self, api_client, registry):
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")

        resp = await api_client.post("/api/v1/pods", json={
            "id": "test-pod",
            "name": "Test",
            "openrouter_key": "sk-test",
        })
        assert resp.status == 409

    @pytest.mark.asyncio
    async def test_get_pod(self, api_client, registry):
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        resp = await api_client.get("/api/v1/pods/test-pod")
        assert resp.status == 200
        data = await resp.json()
        assert data["pod"]["id"] == "test-pod"

    @pytest.mark.asyncio
    async def test_get_nonexistent_pod(self, api_client):
        resp = await api_client.get("/api/v1/pods/nonexistent")
        assert resp.status == 404


# ---------------------------------------------------------------------------
# Pod lifecycle
# ---------------------------------------------------------------------------

class TestPodLifecycle:
    @pytest.mark.asyncio
    async def test_stop_pod(self, api_client, registry):
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        await registry.transition("test-pod", "starting")
        await registry.transition("test-pod", "running")

        with patch("supervisor.docker_manager.stop_pod", new_callable=AsyncMock):
            resp = await api_client.post("/api/v1/pods/test-pod/stop")

        assert resp.status == 200
        data = await resp.json()
        assert data["pod"]["state"] == "stopped"

    @pytest.mark.asyncio
    async def test_start_stopped_pod(self, api_client, registry):
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        await registry.transition("test-pod", "starting")
        await registry.transition("test-pod", "running")
        await registry.transition("test-pod", "stopping")
        await registry.transition("test-pod", "stopped")

        with patch("supervisor.docker_manager.start_pod", new_callable=AsyncMock), \
             patch.object(HealthMonitor, "check_pod_health", return_value=True):
            resp = await api_client.post("/api/v1/pods/test-pod/start")

        assert resp.status == 200
        data = await resp.json()
        assert data["pod"]["state"] == "running"

    @pytest.mark.asyncio
    async def test_destroy_pod(self, api_client, registry):
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        await registry.transition("test-pod", "starting")
        await registry.transition("test-pod", "running")

        with patch("supervisor.docker_manager.stop_pod", new_callable=AsyncMock), \
             patch("supervisor.docker_manager.destroy_pod", new_callable=AsyncMock):
            resp = await api_client.delete("/api/v1/pods/test-pod")

        assert resp.status == 200
        data = await resp.json()
        assert data["pod"]["state"] == "destroyed"

    @pytest.mark.asyncio
    async def test_invalid_transition_returns_409(self, api_client, registry):
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        # Pod is in 'creating' state, can't stop directly

        resp = await api_client.post("/api/v1/pods/test-pod/stop")
        assert resp.status == 409


# ---------------------------------------------------------------------------
# Logs and events
# ---------------------------------------------------------------------------

class TestPodRecreateAfterDestroy:
    @pytest.mark.asyncio
    async def test_recreate_pod_after_destroy(self, api_client, registry):
        """P1: Re-creating a destroyed pod should succeed (hard-deletes old row)."""
        # Create initial pod
        with patch("supervisor.docker_manager.create_pod", new_callable=AsyncMock, return_value="abc123"), \
             patch.object(HealthMonitor, "check_pod_health", return_value=True):
            resp = await api_client.post("/api/v1/pods", json={
                "id": "recycle-pod",
                "name": "Recycle",
                "openrouter_key": "sk-or-test",
            })
        assert resp.status == 201

        # Destroy it
        with patch("supervisor.docker_manager.stop_pod", new_callable=AsyncMock), \
             patch("supervisor.docker_manager.destroy_pod", new_callable=AsyncMock):
            resp = await api_client.delete("/api/v1/pods/recycle-pod")
        assert resp.status == 200

        # Re-create with same ID — should not fail
        with patch("supervisor.docker_manager.create_pod", new_callable=AsyncMock, return_value="def456"), \
             patch.object(HealthMonitor, "check_pod_health", return_value=True):
            resp = await api_client.post("/api/v1/pods", json={
                "id": "recycle-pod",
                "name": "Recycle v2",
                "openrouter_key": "sk-or-test2",
            })
        assert resp.status == 201
        data = await resp.json()
        assert data["pod"]["id"] == "recycle-pod"
        assert data["pod"]["state"] == "running"

    @pytest.mark.asyncio
    async def test_port_reuse_after_destroy(self, api_client, registry):
        """P1: Destroyed pod's port should be reusable by a new pod."""
        # Create pod on port 9001
        with patch("supervisor.docker_manager.create_pod", new_callable=AsyncMock, return_value="abc123"), \
             patch.object(HealthMonitor, "check_pod_health", return_value=True):
            resp = await api_client.post("/api/v1/pods", json={
                "id": "port-pod",
                "name": "Port Test",
                "openrouter_key": "sk-or-test",
            })
        assert resp.status == 201
        data = await resp.json()
        first_port = data["pod"]["port"]

        # Destroy it
        with patch("supervisor.docker_manager.stop_pod", new_callable=AsyncMock), \
             patch("supervisor.docker_manager.destroy_pod", new_callable=AsyncMock):
            await api_client.delete("/api/v1/pods/port-pod")

        # Create new pod — should get same port via gap-filling
        with patch("supervisor.docker_manager.create_pod", new_callable=AsyncMock, return_value="def456"), \
             patch.object(HealthMonitor, "check_pod_health", return_value=True):
            resp = await api_client.post("/api/v1/pods", json={
                "id": "new-pod",
                "name": "New Pod",
                "openrouter_key": "sk-or-test2",
            })
        assert resp.status == 201
        data = await resp.json()
        assert data["pod"]["port"] == first_port


class TestRestartEndpoint:
    @pytest.mark.asyncio
    async def test_restart_running_pod(self, api_client, registry):
        """P2: Restart should update state and regenerate nginx."""
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        await registry.transition("test-pod", "starting")
        await registry.transition("test-pod", "running")

        with patch("supervisor.docker_manager.restart_pod", new_callable=AsyncMock), \
             patch.object(HealthMonitor, "check_pod_health", return_value=True):
            resp = await api_client.post("/api/v1/pods/test-pod/restart")

        assert resp.status == 200
        data = await resp.json()
        assert data["pod"]["state"] == "running"
        assert data["pod"]["restart_count"] == 1

    @pytest.mark.asyncio
    async def test_restart_stopped_pod_rejected(self, api_client, registry):
        """P2: Cannot restart a stopped pod via restart endpoint."""
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        await registry.transition("test-pod", "starting")
        await registry.transition("test-pod", "running")
        await registry.transition("test-pod", "stopping")
        await registry.transition("test-pod", "stopped")

        resp = await api_client.post("/api/v1/pods/test-pod/restart")
        assert resp.status == 409

    @pytest.mark.asyncio
    async def test_restart_error_pod(self, api_client, registry):
        """P2: Can restart a pod in error state."""
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        await registry.transition("test-pod", "error")

        with patch("supervisor.docker_manager.restart_pod", new_callable=AsyncMock), \
             patch.object(HealthMonitor, "check_pod_health", return_value=True):
            resp = await api_client.post("/api/v1/pods/test-pod/restart")

        assert resp.status == 200
        data = await resp.json()
        assert data["pod"]["state"] == "running"

    @pytest.mark.asyncio
    async def test_restart_failure_from_error_state(self, api_client, registry):
        """P1: Docker failure during restart of error pod should not crash with InvalidTransitionError."""
        from supervisor.docker_manager import DockerError

        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        await registry.transition("test-pod", "error")

        with patch("supervisor.docker_manager.restart_pod", new_callable=AsyncMock,
                    side_effect=DockerError("container not found")):
            resp = await api_client.post("/api/v1/pods/test-pod/restart")

        assert resp.status == 500
        data = await resp.json()
        assert "Restart failed" in data["error"]

        pod = await registry.get_pod("test-pod")
        assert pod.state == "error"


class TestLogsAndEvents:
    @pytest.mark.asyncio
    async def test_get_logs(self, api_client, registry):
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")

        with patch("supervisor.docker_manager.get_logs", new_callable=AsyncMock, return_value="log output"):
            resp = await api_client.get("/api/v1/pods/test-pod/logs")

        assert resp.status == 200
        data = await resp.json()
        assert data["logs"] == "log output"

    @pytest.mark.asyncio
    async def test_get_health(self, api_client, registry):
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        await registry.update_health("test-pod", "healthy", "ok", 0)

        resp = await api_client.get("/api/v1/pods/test-pod/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["health_status"] == "healthy"

    @pytest.mark.asyncio
    async def test_get_events(self, api_client, registry):
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        await registry.transition("test-pod", "starting")

        resp = await api_client.get("/api/v1/pods/test-pod/events")
        assert resp.status == 200
        data = await resp.json()
        assert len(data["events"]) >= 2  # created + state_starting

    @pytest.mark.asyncio
    async def test_events_invalid_limit_returns_400(self, api_client, registry):
        """P3: Non-numeric limit should return 400, not 500."""
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        resp = await api_client.get("/api/v1/pods/test-pod/events?limit=abc")
        assert resp.status == 400
        data = await resp.json()
        assert "limit" in data["error"]


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

class TestReconcile:
    @pytest.mark.asyncio
    async def test_reconcile_running_pod_missing_container(self, api_client, registry):
        """P1: Reconcile should not crash on running pod with missing container."""
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        await registry.transition("test-pod", "starting")
        await registry.transition("test-pod", "running")

        # Reconcile with no Docker containers — should adopt as stopped
        with patch("supervisor.docker_manager.list_containers", new_callable=AsyncMock, return_value=[]):
            resp = await api_client.post("/api/v1/reconcile")

        assert resp.status == 200
        data = await resp.json()
        assert data["reconciled"] is True

        pod = await registry.get_pod("test-pod")
        assert pod.state == "stopped"

    @pytest.mark.asyncio
    async def test_reconcile_starting_pod_missing_container(self, api_client, registry):
        """P1: Reconcile should not crash on starting pod with missing container."""
        await registry.create_pod("test-pod", "Test", 9001, "/d/test")
        await registry.transition("test-pod", "starting")

        with patch("supervisor.docker_manager.list_containers", new_callable=AsyncMock, return_value=[]):
            resp = await api_client.post("/api/v1/reconcile")

        assert resp.status == 200
        pod = await registry.get_pod("test-pod")
        assert pod.state == "stopped"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:
    @pytest.mark.asyncio
    async def test_auth_required_when_token_set(self, registry, tmp_path):
        health_monitor = HealthMonitor(registry)
        nginx_manager = NginxManager(conf_path=str(tmp_path / "nonexistent"))
        api = ApiServer(registry, health_monitor, nginx_manager)
        app = api.create_app()

        with patch("supervisor.api.SUPERVISOR_TOKEN", "secret-token"):
            server = TestServer(app)
            client = TestClient(server)
            await client.start_server()
            try:
                # No auth header
                resp = await client.get("/api/v1/pods")
                assert resp.status == 401

                # Wrong token
                resp = await client.get("/api/v1/pods", headers={"Authorization": "Bearer wrong"})
                assert resp.status == 403

                # Correct token
                resp = await client.get("/api/v1/pods", headers={"Authorization": "Bearer secret-token"})
                assert resp.status == 200
            finally:
                await client.close()

    @pytest.mark.asyncio
    async def test_health_endpoint_always_open(self, registry, tmp_path):
        health_monitor = HealthMonitor(registry)
        nginx_manager = NginxManager(conf_path=str(tmp_path / "nonexistent"))
        api = ApiServer(registry, health_monitor, nginx_manager)
        app = api.create_app()

        with patch("supervisor.api.SUPERVISOR_TOKEN", "secret-token"):
            server = TestServer(app)
            client = TestClient(server)
            await client.start_server()
            try:
                resp = await client.get("/api/v1/health")
                assert resp.status == 200
            finally:
                await client.close()
