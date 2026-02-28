"""supervisor.supervisor — Main entry point, startup reconciliation, signal handling."""

import asyncio
import os
import signal
import sys
from typing import Optional

from supervisor.api import ApiServer
from supervisor.docker_manager import AGENTS_ROOT
from supervisor.health_monitor import HealthMonitor
from supervisor.nginx_manager import NginxManager
from supervisor.registry import Registry
from supervisor import docker_manager


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

class Supervisor:
    def __init__(self, db_path: Optional[str] = None):
        self._registry = Registry(db_path=db_path) if db_path else Registry()
        self._health_monitor = HealthMonitor(self._registry)
        self._nginx_manager = NginxManager()
        self._api = ApiServer(self._registry, self._health_monitor, self._nginx_manager)
        self._shutdown_event = asyncio.Event()

    @property
    def registry(self) -> Registry:
        return self._registry

    @property
    def api(self) -> ApiServer:
        return self._api

    async def start(self) -> None:
        """Initialize DB, reconcile Docker state, start health monitor and API."""
        print("[Supervisor] Starting...")

        # 1. Initialize platform DB
        await self._registry.init_db()

        # 2. Reconcile with Docker reality
        await self._reconcile()

        # 3. Start health monitor
        await self._health_monitor.start()

        # 4. Start API server
        await self._api.start()

        print("[Supervisor] Ready")

    async def stop(self) -> None:
        """Graceful shutdown."""
        print("[Supervisor] Shutting down...")
        await self._api.stop()
        await self._health_monitor.stop()
        await self._registry.close()
        print("[Supervisor] Shutdown complete")

    async def run(self) -> None:
        """Start and wait for shutdown signal."""
        await self.start()

        # Install signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._signal_handler)

        # Wait for shutdown
        await self._shutdown_event.wait()
        await self.stop()

    def _signal_handler(self) -> None:
        print("\n[Supervisor] Signal received, initiating shutdown...")
        self._shutdown_event.set()

    async def _reconcile(self) -> None:
        """Sync Docker container state with registry on startup."""
        print("[Supervisor] Reconciling Docker state...")
        try:
            containers = await docker_manager.list_containers()
        except docker_manager.DockerError as e:
            print(f"[Supervisor] Docker not available, skipping reconciliation: {e}")
            return

        container_map = {c.agent_id: c for c in containers}
        adopted = 0
        reconciled = 0

        # Adopt containers not in registry
        for c in containers:
            pod = await self._registry.get_pod(c.agent_id)
            if pod is None:
                data_dir = str(AGENTS_ROOT / c.agent_id)
                state = "running" if c.state == "running" else "stopped"
                port = c.port or await self._registry.allocate_port()
                await self._registry.create_pod(
                    pod_id=c.agent_id,
                    name=c.agent_id,
                    port=port,
                    data_dir=data_dir,
                )
                await self._registry.adopt_pod(c.agent_id, state)
                adopted += 1

        # Reconcile state mismatches for existing pods
        # Use adopt_pod() to bypass state machine — reconciliation is a force-sync
        registry_pods = await self._registry.list_pods()
        for pod in registry_pods:
            c = container_map.get(pod.id)
            if c is None and pod.state in ("running", "starting"):
                await self._registry.adopt_pod(pod.id, "stopped")
                reconciled += 1
            elif c is not None:
                docker_running = c.state == "running"
                if pod.state == "running" and not docker_running:
                    await self._registry.adopt_pod(pod.id, "stopped")
                    reconciled += 1
                elif pod.state == "stopped" and docker_running:
                    await self._registry.adopt_pod(pod.id, "running")
                    reconciled += 1

        # Regenerate nginx if anything changed
        if adopted > 0 or reconciled > 0:
            await self._nginx_manager.regenerate_routes(self._registry)

        print(f"[Supervisor] Reconciliation: {adopted} adopted, {reconciled} reconciled, "
              f"{len(containers)} container(s) found")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    supervisor = Supervisor()
    try:
        asyncio.run(supervisor.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
