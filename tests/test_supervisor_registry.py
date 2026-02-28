"""Tests for supervisor.registry — Pod state machine, DB CRUD, port allocation."""

import asyncio
import pytest
import pytest_asyncio

from supervisor.registry import (
    Registry, Pod, VALID_TRANSITIONS,
    InvalidTransitionError, PodNotFoundError, PortExhaustedError,
)


@pytest_asyncio.fixture
async def registry(tmp_path):
    """Create a registry with in-memory-like temp DB."""
    db_path = str(tmp_path / "test_supervisor.db")
    reg = Registry(db_path=db_path)
    await reg.init_db()
    yield reg
    await reg.close()


@pytest_asyncio.fixture
async def sample_pod(registry):
    """Create a sample pod in the registry."""
    return await registry.create_pod(
        pod_id="test-pod-abc123",
        name="Test Pod",
        port=9001,
        data_dir="/data/alive-agents/test-pod-abc123",
        manager_id="mgr-001",
        memory_limit_mb=512,
        cpu_limit=0.5,
    )


# ---------------------------------------------------------------------------
# DB Init
# ---------------------------------------------------------------------------

class TestRegistryInit:
    @pytest.mark.asyncio
    async def test_init_creates_tables(self, registry):
        cursor = await registry._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in await cursor.fetchall()}
        assert "pods" in tables
        assert "pod_events" in tables

    @pytest.mark.asyncio
    async def test_init_is_idempotent(self, registry):
        # Second init should not raise
        await registry.init_db()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestCRUD:
    @pytest.mark.asyncio
    async def test_create_pod(self, registry):
        pod = await registry.create_pod(
            pod_id="hina-a1b2c3",
            name="Hina",
            port=9001,
            data_dir="/data/alive-agents/hina-a1b2c3",
            manager_id="mgr-001",
        )
        assert pod.id == "hina-a1b2c3"
        assert pod.name == "Hina"
        assert pod.state == "creating"
        assert pod.port == 9001
        assert pod.health_status == "unknown"
        assert pod.memory_limit_mb == 512
        assert pod.cpu_limit == 0.5

    @pytest.mark.asyncio
    async def test_get_pod(self, registry, sample_pod):
        pod = await registry.get_pod("test-pod-abc123")
        assert pod is not None
        assert pod.name == "Test Pod"

    @pytest.mark.asyncio
    async def test_get_nonexistent_pod(self, registry):
        pod = await registry.get_pod("doesnt-exist")
        assert pod is None

    @pytest.mark.asyncio
    async def test_list_pods(self, registry, sample_pod):
        pods = await registry.list_pods()
        assert len(pods) == 1
        assert pods[0].id == "test-pod-abc123"

    @pytest.mark.asyncio
    async def test_list_pods_filter_by_state(self, registry, sample_pod):
        pods = await registry.list_pods(state="creating")
        assert len(pods) == 1
        pods = await registry.list_pods(state="running")
        assert len(pods) == 0

    @pytest.mark.asyncio
    async def test_list_pods_excludes_destroyed(self, registry, sample_pod):
        # Move to destroyed through valid transitions
        await registry.transition("test-pod-abc123", "starting")
        await registry.transition("test-pod-abc123", "stopping")
        await registry.transition("test-pod-abc123", "stopped")
        await registry.transition("test-pod-abc123", "destroying")
        await registry.transition("test-pod-abc123", "destroyed")

        pods = await registry.list_pods()
        assert len(pods) == 0

        pods = await registry.list_pods(exclude_destroyed=False)
        assert len(pods) == 1

    @pytest.mark.asyncio
    async def test_delete_pod(self, registry, sample_pod):
        await registry.delete_pod("test-pod-abc123")
        pod = await registry.get_pod("test-pod-abc123")
        assert pod is None

    @pytest.mark.asyncio
    async def test_pod_to_dict(self, sample_pod):
        d = sample_pod.to_dict()
        assert d["id"] == "test-pod-abc123"
        assert isinstance(d, dict)


# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------

class TestStateMachine:
    @pytest.mark.asyncio
    async def test_valid_transition(self, registry, sample_pod):
        pod = await registry.transition("test-pod-abc123", "starting")
        assert pod.state == "starting"

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, registry, sample_pod):
        """Test the happy path: creating → starting → running → stopping → stopped → destroying → destroyed."""
        await registry.transition("test-pod-abc123", "starting")
        await registry.transition("test-pod-abc123", "running")
        await registry.transition("test-pod-abc123", "stopping")
        await registry.transition("test-pod-abc123", "stopped")
        await registry.transition("test-pod-abc123", "destroying")
        pod = await registry.transition("test-pod-abc123", "destroyed")
        assert pod.state == "destroyed"

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, registry, sample_pod):
        with pytest.raises(InvalidTransitionError):
            await registry.transition("test-pod-abc123", "running")  # can't go creating -> running

    @pytest.mark.asyncio
    async def test_destroyed_is_terminal(self, registry, sample_pod):
        await registry.transition("test-pod-abc123", "starting")
        await registry.transition("test-pod-abc123", "stopping")
        await registry.transition("test-pod-abc123", "stopped")
        await registry.transition("test-pod-abc123", "destroying")
        await registry.transition("test-pod-abc123", "destroyed")

        with pytest.raises(InvalidTransitionError):
            await registry.transition("test-pod-abc123", "starting")

    @pytest.mark.asyncio
    async def test_error_recovery(self, registry, sample_pod):
        """Can recover from error state to starting or destroying."""
        await registry.transition("test-pod-abc123", "error")
        await registry.transition("test-pod-abc123", "starting")
        assert (await registry.get_pod("test-pod-abc123")).state == "starting"

    @pytest.mark.asyncio
    async def test_error_to_destroying(self, registry, sample_pod):
        await registry.transition("test-pod-abc123", "error")
        await registry.transition("test-pod-abc123", "destroying")
        assert (await registry.get_pod("test-pod-abc123")).state == "destroying"

    @pytest.mark.asyncio
    async def test_transition_nonexistent_pod_raises(self, registry):
        with pytest.raises(PodNotFoundError):
            await registry.transition("nonexistent", "starting")

    @pytest.mark.asyncio
    async def test_running_sets_started_at(self, registry, sample_pod):
        await registry.transition("test-pod-abc123", "starting")
        pod = await registry.transition("test-pod-abc123", "running")
        assert pod.started_at is not None

    @pytest.mark.asyncio
    async def test_stopped_sets_stopped_at(self, registry, sample_pod):
        await registry.transition("test-pod-abc123", "starting")
        await registry.transition("test-pod-abc123", "running")
        await registry.transition("test-pod-abc123", "stopping")
        pod = await registry.transition("test-pod-abc123", "stopped")
        assert pod.stopped_at is not None

    @pytest.mark.asyncio
    async def test_all_transitions_in_map(self):
        """Every state mentioned as a target must have its own entry."""
        all_targets = set()
        for targets in VALID_TRANSITIONS.values():
            all_targets.update(targets)
        for state in all_targets:
            assert state in VALID_TRANSITIONS, f"State '{state}' is a target but not in VALID_TRANSITIONS"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    @pytest.mark.asyncio
    async def test_update_health(self, registry, sample_pod):
        await registry.update_health("test-pod-abc123", "healthy", "ok", 0)
        pod = await registry.get_pod("test-pod-abc123")
        assert pod.health_status == "healthy"
        assert pod.health_reason == "ok"
        assert pod.last_health_check is not None
        assert pod.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_increment_restart_count(self, registry, sample_pod):
        count = await registry.increment_restart_count("test-pod-abc123")
        assert count == 1
        count = await registry.increment_restart_count("test-pod-abc123")
        assert count == 2

    @pytest.mark.asyncio
    async def test_update_container_id(self, registry, sample_pod):
        await registry.update_container_id("test-pod-abc123", "abc123def456")
        pod = await registry.get_pod("test-pod-abc123")
        assert pod.container_id == "abc123def456"


# ---------------------------------------------------------------------------
# Port Allocation
# ---------------------------------------------------------------------------

class TestPortAllocation:
    @pytest.mark.asyncio
    async def test_allocate_first_port(self, registry):
        port = await registry.allocate_port()
        assert port == 9001

    @pytest.mark.asyncio
    async def test_allocate_sequential(self, registry):
        await registry.create_pod("p1", "P1", 9001, "/d/p1")
        port = await registry.allocate_port()
        assert port == 9002

    @pytest.mark.asyncio
    async def test_allocate_gap_filling(self, registry):
        """If port 9001 is freed (destroyed), next allocation should reuse it."""
        await registry.create_pod("p1", "P1", 9001, "/d/p1")
        await registry.create_pod("p2", "P2", 9002, "/d/p2")

        # Destroy p1, freeing port 9001
        await registry.transition("p1", "starting")
        await registry.transition("p1", "stopping")
        await registry.transition("p1", "stopped")
        await registry.transition("p1", "destroying")
        await registry.transition("p1", "destroyed")

        port = await registry.allocate_port()
        assert port == 9001  # gap-filled

    @pytest.mark.asyncio
    async def test_allocate_skips_non_destroyed(self, registry):
        """Ports from error/stopped pods are still reserved."""
        await registry.create_pod("p1", "P1", 9001, "/d/p1")
        await registry.transition("p1", "error")  # creating → error is valid

        port = await registry.allocate_port()
        assert port == 9002  # 9001 still reserved


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class TestEvents:
    @pytest.mark.asyncio
    async def test_create_logs_event(self, registry, sample_pod):
        events = await registry.get_events("test-pod-abc123")
        assert len(events) >= 1
        assert events[-1]["event"] == "created"

    @pytest.mark.asyncio
    async def test_transition_logs_event(self, registry, sample_pod):
        await registry.transition("test-pod-abc123", "starting")
        events = await registry.get_events("test-pod-abc123")
        event_types = [e["event"] for e in events]
        assert "state_starting" in event_types

    @pytest.mark.asyncio
    async def test_events_ordered_desc(self, registry, sample_pod):
        await registry.transition("test-pod-abc123", "starting")
        await registry.transition("test-pod-abc123", "running")
        events = await registry.get_events("test-pod-abc123")
        # Most recent first
        assert events[0]["event"] == "state_running"

    @pytest.mark.asyncio
    async def test_events_limit(self, registry, sample_pod):
        for _ in range(5):
            await registry.transition("test-pod-abc123", "starting")
            await registry.transition("test-pod-abc123", "error")

        events = await registry.get_events("test-pod-abc123", limit=3)
        assert len(events) == 3
