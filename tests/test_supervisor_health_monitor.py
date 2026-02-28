"""Tests for supervisor.health_monitor — Background health polling."""

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from supervisor.health_monitor import HealthMonitor, MAX_CONSECUTIVE_FAILURES
from supervisor.registry import Registry, Pod


@pytest_asyncio.fixture
async def registry(tmp_path):
    db_path = str(tmp_path / "test_supervisor.db")
    reg = Registry(db_path=db_path)
    await reg.init_db()
    yield reg
    await reg.close()


@pytest_asyncio.fixture
async def running_pod(registry):
    """Create a pod in running state."""
    pod = await registry.create_pod(
        pod_id="test-pod", name="Test", port=9001, data_dir="/d/test-pod"
    )
    await registry.transition("test-pod", "starting")
    await registry.transition("test-pod", "running")
    return await registry.get_pod("test-pod")


@pytest_asyncio.fixture
async def monitor(registry):
    mon = HealthMonitor(registry)
    yield mon
    if mon._running:
        await mon.stop()


# ---------------------------------------------------------------------------
# Health check logic
# ---------------------------------------------------------------------------

class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_response(self, registry, running_pod, monitor):
        """Pod returning status=alive should be marked healthy."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"status": "alive", "reason": "ok"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)

        await monitor._check_pod(mock_session, running_pod)

        pod = await registry.get_pod("test-pod")
        assert pod.health_status == "healthy"
        assert pod.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_degraded_response(self, registry, running_pod, monitor):
        """Pod returning status=degraded should be marked degraded."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"status": "degraded", "reason": "stale loop"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)

        await monitor._check_pod(mock_session, running_pod)

        pod = await registry.get_pod("test-pod")
        assert pod.health_status == "degraded"
        assert pod.consecutive_failures == 1


class TestStartingPodPolling:
    @pytest.mark.asyncio
    async def test_starting_pod_promoted_on_healthy(self, registry, monitor):
        """P1: Starting pod should transition to running when healthy."""
        pod = await registry.create_pod(
            pod_id="start-pod", name="Start", port=9002, data_dir="/d/start-pod"
        )
        await registry.transition("start-pod", "starting")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"status": "alive", "reason": "ok"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)

        pod = await registry.get_pod("start-pod")
        await monitor._check_pod(mock_session, pod)

        pod = await registry.get_pod("start-pod")
        assert pod.state == "running"
        assert pod.health_status == "healthy"

    @pytest.mark.asyncio
    async def test_starting_pod_enters_error_on_max_failures(self, registry, monitor):
        """P1: Starting pod that never becomes healthy should enter error state."""
        import aiohttp as _aiohttp

        pod = await registry.create_pod(
            pod_id="fail-pod", name="Fail", port=9003, data_dir="/d/fail-pod"
        )
        await registry.transition("fail-pod", "starting")

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=_aiohttp.ClientError("connection refused"))

        for i in range(MAX_CONSECUTIVE_FAILURES):
            pod = await registry.get_pod("fail-pod")
            await monitor._check_pod(mock_session, pod)

        pod = await registry.get_pod("fail-pod")
        assert pod.state == "error"
        assert pod.health_status == "dead"

    @pytest.mark.asyncio
    async def test_poll_once_includes_starting_pods(self, registry, monitor):
        """P1: _poll_once should include starting pods, not just running."""
        pod = await registry.create_pod(
            pod_id="poll-pod", name="Poll", port=9004, data_dir="/d/poll-pod"
        )
        await registry.transition("poll-pod", "starting")

        with patch.object(monitor, "_check_pod", new_callable=AsyncMock) as mock_check:
            mock_session_cls = AsyncMock()
            mock_session_instance = AsyncMock()
            mock_session_cls.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_cls.__aexit__ = AsyncMock(return_value=False)

            with patch("aiohttp.ClientSession", return_value=mock_session_cls):
                await monitor._poll_once()

            assert mock_check.call_count == 1
            called_pod = mock_check.call_args[0][1]
            assert called_pod.id == "poll-pod"
            assert called_pod.state == "starting"


class TestFailureTracking:
    @pytest.mark.asyncio
    async def test_consecutive_failures_increment(self, registry, running_pod, monitor):
        """Each failure should increment consecutive_failures."""
        import aiohttp

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=aiohttp.ClientError("connection refused"))

        # Patch _try_restart to avoid Docker calls
        with patch.object(monitor, "_try_restart", new_callable=AsyncMock):
            for i in range(MAX_CONSECUTIVE_FAILURES):
                pod = await registry.get_pod("test-pod")
                await monitor._check_pod(mock_session, pod)

        pod = await registry.get_pod("test-pod")
        assert pod.consecutive_failures == MAX_CONSECUTIVE_FAILURES
        assert pod.health_status == "dead"

    @pytest.mark.asyncio
    async def test_healthy_resets_failures(self, registry, running_pod, monitor):
        """A healthy response should reset consecutive_failures to 0."""
        # First, set some failures
        await registry.update_health("test-pod", "degraded", "test", consecutive_failures=2)

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"status": "alive", "reason": "ok"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)

        pod = await registry.get_pod("test-pod")
        await monitor._check_pod(mock_session, pod)

        pod = await registry.get_pod("test-pod")
        assert pod.consecutive_failures == 0
        assert pod.health_status == "healthy"


# ---------------------------------------------------------------------------
# Auto-restart
# ---------------------------------------------------------------------------

class TestAutoRestart:
    @pytest.mark.asyncio
    async def test_restart_on_dead(self, registry, running_pod, monitor):
        """When pod is marked dead, auto-restart should be triggered."""
        await registry.update_health("test-pod", "dead", "timeout", consecutive_failures=3)

        pod = await registry.get_pod("test-pod")
        with patch("supervisor.docker_manager.restart_pod", new_callable=AsyncMock), \
             patch.object(monitor, "_wait_for_health", return_value=True):
            await monitor._try_restart(pod)

        pod = await registry.get_pod("test-pod")
        assert pod.restart_count == 1
        assert pod.health_status == "healthy"

    @pytest.mark.asyncio
    async def test_max_restarts_enters_error(self, registry, running_pod, monitor):
        """Exceeding max restarts per hour should put pod in error state."""
        import time
        # Fill up restart timestamps
        monitor._restart_timestamps["test-pod"] = [time.monotonic() for _ in range(5)]

        pod = await registry.get_pod("test-pod")
        await monitor._try_restart(pod)

        pod = await registry.get_pod("test-pod")
        assert pod.state == "error"


# ---------------------------------------------------------------------------
# Start/Stop lifecycle
# ---------------------------------------------------------------------------

class TestMonitorLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self, monitor):
        await monitor.start()
        assert monitor._running is True
        assert monitor._task is not None

        await monitor.stop()
        assert monitor._running is False
        assert monitor._task is None

    @pytest.mark.asyncio
    async def test_poll_once_with_no_running_pods(self, registry, monitor):
        """poll_once should be a no-op when no pods are running."""
        await monitor._poll_once()  # Should not raise
