"""Tests for supervisor.docker_manager — Container lifecycle operations."""

import asyncio
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from supervisor.docker_manager import (
    run_cmd, CmdResult, DockerError, DockerTimeoutError,
    create_pod, start_pod, stop_pod, restart_pod, destroy_pod,
    get_logs, inspect_container, list_containers, ContainerInfo,
    _parse_host_port, _container_name,
)
from supervisor.registry import Pod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pod(**overrides) -> Pod:
    defaults = dict(
        id="test-abc123",
        name="Test",
        state="creating",
        port=9001,
        container_id=None,
        memory_limit_mb=512,
        cpu_limit=0.5,
        data_dir="/tmp/test-agents/test-abc123",
        health_status="unknown",
        health_reason=None,
        last_health_check=None,
        consecutive_failures=0,
        restart_count=0,
        manager_id=None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        started_at=None,
        stopped_at=None,
    )
    defaults.update(overrides)
    return Pod(**defaults)


def _mock_subprocess(stdout="", stderr="", returncode=0):
    """Create a mock for asyncio.create_subprocess_exec."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(
        return_value=(stdout.encode(), stderr.encode())
    )
    mock_proc.returncode = returncode
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()
    return mock_proc


# ---------------------------------------------------------------------------
# run_cmd
# ---------------------------------------------------------------------------

class TestRunCmd:
    @pytest.mark.asyncio
    async def test_successful_command(self):
        with patch("asyncio.create_subprocess_exec", return_value=_mock_subprocess("output\n")):
            result = await run_cmd("echo", "hello")
            assert result.returncode == 0
            assert result.stdout == "output\n"

    @pytest.mark.asyncio
    async def test_failed_command_raises(self):
        with patch("asyncio.create_subprocess_exec", return_value=_mock_subprocess("", "error", 1)):
            with pytest.raises(DockerError) as exc_info:
                await run_cmd("false")
            assert exc_info.value.returncode == 1

    @pytest.mark.asyncio
    async def test_failed_command_no_check(self):
        with patch("asyncio.create_subprocess_exec", return_value=_mock_subprocess("", "error", 1)):
            result = await run_cmd("false", check=False)
            assert result.returncode == 1

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(DockerTimeoutError):
                await run_cmd("sleep", "999", timeout=1)


# ---------------------------------------------------------------------------
# Container name
# ---------------------------------------------------------------------------

class TestContainerName:
    def test_container_name(self):
        assert _container_name("hina-abc") == "alive-agent-hina-abc"


# ---------------------------------------------------------------------------
# Port parsing
# ---------------------------------------------------------------------------

class TestParseHostPort:
    def test_standard_mapping(self):
        assert _parse_host_port("127.0.0.1:9001->8080/tcp") == 9001

    def test_wildcard_mapping(self):
        assert _parse_host_port("0.0.0.0:9002->8080/tcp") == 9002

    def test_empty_string(self):
        assert _parse_host_port("") is None

    def test_no_8080_mapping(self):
        assert _parse_host_port("127.0.0.1:3000->3000/tcp") is None

    def test_multiple_mappings(self):
        assert _parse_host_port("127.0.0.1:9001->8080/tcp, 127.0.0.1:9999->9999/tcp") == 9001


# ---------------------------------------------------------------------------
# create_pod
# ---------------------------------------------------------------------------

class TestCreatePod:
    @pytest.mark.asyncio
    async def test_create_pod_calls_docker_run(self, tmp_path):
        pod = _make_pod(data_dir=str(tmp_path / "test-abc123"))

        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = CmdResult(0, "container123456789\n", "")
            container_id = await create_pod(pod, "sk-or-key")

        assert container_id == "container123"  # truncated to 12 chars

        # Verify docker run was called
        calls = mock_cmd.call_args_list
        docker_run_call = [c for c in calls if "docker" in str(c) and "run" in str(c)]
        assert len(docker_run_call) >= 1

    @pytest.mark.asyncio
    async def test_create_pod_creates_directories(self, tmp_path):
        pod = _make_pod(data_dir=str(tmp_path / "test-abc123"))

        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = CmdResult(0, "abc123\n", "")
            await create_pod(pod, "sk-or-key")

        assert (tmp_path / "test-abc123" / "db").exists()
        assert (tmp_path / "test-abc123" / "memory").exists()


# ---------------------------------------------------------------------------
# start/stop/restart/destroy
# ---------------------------------------------------------------------------

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_pod(self):
        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = CmdResult(0, "", "")
            await start_pod("test-abc")
        mock_cmd.assert_called_with("docker", "start", "alive-agent-test-abc", timeout=15)

    @pytest.mark.asyncio
    async def test_stop_pod(self):
        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = CmdResult(0, "", "")
            await stop_pod("test-abc")
        mock_cmd.assert_called_with("docker", "stop", "alive-agent-test-abc", timeout=15)

    @pytest.mark.asyncio
    async def test_restart_pod(self):
        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = CmdResult(0, "", "")
            await restart_pod("test-abc")
        mock_cmd.assert_called_with("docker", "restart", "alive-agent-test-abc", timeout=30)

    @pytest.mark.asyncio
    async def test_destroy_no_purge(self):
        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = CmdResult(0, "", "")
            await destroy_pod("test-abc", purge=False)
        # Should have called stop and rm
        assert mock_cmd.call_count == 2

    @pytest.mark.asyncio
    async def test_destroy_with_purge(self, tmp_path):
        agent_dir = tmp_path / "test-abc"
        agent_dir.mkdir()
        (agent_dir / "db").mkdir()

        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd, \
             patch("supervisor.docker_manager.AGENTS_ROOT", tmp_path):
            mock_cmd.return_value = CmdResult(0, "", "")
            await destroy_pod("test-abc", purge=True)

        assert not agent_dir.exists()


# ---------------------------------------------------------------------------
# get_logs
# ---------------------------------------------------------------------------

class TestGetLogs:
    @pytest.mark.asyncio
    async def test_get_logs(self):
        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = CmdResult(0, "stdout logs\n", "stderr logs\n")
            logs = await get_logs("test-abc", tail=100)
        assert "stdout logs" in logs
        assert "stderr logs" in logs


# ---------------------------------------------------------------------------
# inspect_container
# ---------------------------------------------------------------------------

class TestInspectContainer:
    @pytest.mark.asyncio
    async def test_inspect_existing(self):
        inspect_data = [{"State": {"Running": True}}]
        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = CmdResult(0, json.dumps(inspect_data), "")
            result = await inspect_container("test-abc")
        assert result is not None
        assert result["State"]["Running"] is True

    @pytest.mark.asyncio
    async def test_inspect_nonexistent(self):
        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = CmdResult(1, "", "not found")
            result = await inspect_container("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# list_containers
# ---------------------------------------------------------------------------

class TestListContainers:
    @pytest.mark.asyncio
    async def test_list_containers(self):
        output = "alive-agent-hina\trunning\t127.0.0.1:9001->8080/tcp\nalive-agent-yuki\texited\t\n"
        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = CmdResult(0, output, "")
            containers = await list_containers()

        assert len(containers) == 2
        assert containers[0].agent_id == "hina"
        assert containers[0].state == "running"
        assert containers[0].port == 9001
        assert containers[1].agent_id == "yuki"
        assert containers[1].state == "exited"
        assert containers[1].port is None

    @pytest.mark.asyncio
    async def test_list_empty(self):
        with patch("supervisor.docker_manager.run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = CmdResult(0, "", "")
            containers = await list_containers()
        assert containers == []
