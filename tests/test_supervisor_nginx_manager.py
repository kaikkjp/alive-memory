"""Tests for supervisor.nginx_manager — Route generation and config management."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from supervisor.nginx_manager import NginxManager, MARKER_BEGIN, MARKER_END
from supervisor.registry import Registry, Pod


@pytest_asyncio.fixture
async def registry(tmp_path):
    db_path = str(tmp_path / "test_supervisor.db")
    reg = Registry(db_path=db_path)
    await reg.init_db()
    yield reg
    await reg.close()


@pytest.fixture
def nginx_conf(tmp_path):
    """Create a mock nginx config file with markers."""
    conf = tmp_path / "alive-lounge"
    conf.write_text(
        f"server {{\n"
        f"    listen 80;\n"
        f"{MARKER_BEGIN}\n"
        f"{MARKER_END}\n"
        f"    location / {{ return 404; }}\n"
        f"}}\n"
    )
    return conf


@pytest.fixture
def manager(nginx_conf):
    return NginxManager(conf_path=str(nginx_conf))


# ---------------------------------------------------------------------------
# Route building
# ---------------------------------------------------------------------------

class TestRouteBuild:
    def test_build_routes_single_pod(self, manager):
        pods = [Pod(
            id="hina", name="Hina", state="running", port=9001,
            container_id="abc", memory_limit_mb=512, cpu_limit=0.5,
            data_dir="/d/hina", health_status="healthy", health_reason=None,
            last_health_check=None, consecutive_failures=0, restart_count=0,
            manager_id=None, created_at="", updated_at="",
            started_at=None, stopped_at=None,
        )]
        routes = manager._build_routes(pods)
        assert "location /hina/" in routes
        assert "proxy_pass http://127.0.0.1:9001/;" in routes
        assert "proxy_set_header Upgrade" in routes

    def test_build_routes_multiple_pods(self, manager):
        pods = [
            Pod(id="hina", name="Hina", state="running", port=9001,
                container_id="a", memory_limit_mb=512, cpu_limit=0.5,
                data_dir="/d/h", health_status="healthy", health_reason=None,
                last_health_check=None, consecutive_failures=0, restart_count=0,
                manager_id=None, created_at="", updated_at="",
                started_at=None, stopped_at=None),
            Pod(id="yuki", name="Yuki", state="running", port=9002,
                container_id="b", memory_limit_mb=512, cpu_limit=0.5,
                data_dir="/d/y", health_status="healthy", health_reason=None,
                last_health_check=None, consecutive_failures=0, restart_count=0,
                manager_id=None, created_at="", updated_at="",
                started_at=None, stopped_at=None),
        ]
        routes = manager._build_routes(pods)
        assert "location /hina/" in routes
        assert "location /yuki/" in routes
        assert "9001" in routes
        assert "9002" in routes

    def test_build_routes_empty(self, manager):
        routes = manager._build_routes([])
        assert routes == ""

    def test_build_routes_skips_none_port(self, manager):
        pods = [Pod(
            id="broken", name="Broken", state="running", port=None,
            container_id="x", memory_limit_mb=512, cpu_limit=0.5,
            data_dir="/d/b", health_status="unknown", health_reason=None,
            last_health_check=None, consecutive_failures=0, restart_count=0,
            manager_id=None, created_at="", updated_at="",
            started_at=None, stopped_at=None,
        )]
        routes = manager._build_routes(pods)
        assert routes == ""


# ---------------------------------------------------------------------------
# Config file operations
# ---------------------------------------------------------------------------

class TestConfigOps:
    def test_read_between_markers(self, manager, nginx_conf):
        content = manager._read_between_markers()
        assert content is not None
        assert content.strip() == ""  # empty between markers initially

    def test_write_between_markers(self, manager, nginx_conf):
        manager._write_between_markers("    location /test/ { }")
        content = nginx_conf.read_text()
        assert "location /test/" in content
        assert MARKER_BEGIN in content
        assert MARKER_END in content

    def test_write_preserves_surrounding(self, manager, nginx_conf):
        manager._write_between_markers("    location /test/ { }")
        content = nginx_conf.read_text()
        assert "listen 80" in content
        assert "return 404" in content

    def test_read_missing_markers(self, tmp_path):
        conf = tmp_path / "no-markers"
        conf.write_text("server { listen 80; }")
        mgr = NginxManager(conf_path=str(conf))
        assert mgr._read_between_markers() is None


# ---------------------------------------------------------------------------
# regenerate_routes
# ---------------------------------------------------------------------------

class TestRegenerateRoutes:
    @pytest.mark.asyncio
    async def test_regenerate_with_running_pods(self, registry, manager, nginx_conf):
        await registry.create_pod("hina", "Hina", 9001, "/d/hina")
        await registry.transition("hina", "starting")
        await registry.transition("hina", "running")

        with patch("supervisor.nginx_manager.run_cmd", new_callable=AsyncMock):
            changed = await manager.regenerate_routes(registry)

        assert changed is True
        content = nginx_conf.read_text()
        assert "location /hina/" in content

    @pytest.mark.asyncio
    async def test_regenerate_idempotent(self, registry, manager, nginx_conf):
        await registry.create_pod("hina", "Hina", 9001, "/d/hina")
        await registry.transition("hina", "starting")
        await registry.transition("hina", "running")

        with patch("supervisor.nginx_manager.run_cmd", new_callable=AsyncMock):
            await manager.regenerate_routes(registry)  # First time
            changed = await manager.regenerate_routes(registry)  # Second time

        assert changed is False  # No change needed

    @pytest.mark.asyncio
    async def test_regenerate_removes_stopped_pods(self, registry, manager, nginx_conf):
        await registry.create_pod("hina", "Hina", 9001, "/d/hina")
        await registry.transition("hina", "starting")
        await registry.transition("hina", "running")

        with patch("supervisor.nginx_manager.run_cmd", new_callable=AsyncMock):
            await manager.regenerate_routes(registry)

        # Stop the pod
        await registry.transition("hina", "stopping")
        await registry.transition("hina", "stopped")

        with patch("supervisor.nginx_manager.run_cmd", new_callable=AsyncMock):
            changed = await manager.regenerate_routes(registry)

        assert changed is True
        content = nginx_conf.read_text()
        assert "location /hina/" not in content

    @pytest.mark.asyncio
    async def test_dev_mode_no_config(self, registry, tmp_path):
        """When config file doesn't exist, should log warning and skip."""
        mgr = NginxManager(conf_path=str(tmp_path / "nonexistent"))
        changed = await mgr.regenerate_routes(registry)
        assert changed is False
