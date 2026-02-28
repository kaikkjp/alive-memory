"""supervisor.api — HTTP JSON API for pod lifecycle management."""

import hashlib
import json
import os
import re
from typing import Optional

from aiohttp import web

from supervisor import docker_manager
from supervisor.docker_manager import DockerError, DockerTimeoutError, AGENTS_ROOT
from supervisor.health_monitor import HealthMonitor
from supervisor.nginx_manager import NginxManager
from supervisor.registry import (
    Registry, Pod, InvalidTransitionError, PodNotFoundError, PortExhaustedError,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SUPERVISOR_HOST = os.getenv("SUPERVISOR_HOST", "127.0.0.1")
SUPERVISOR_PORT = int(os.getenv("SUPERVISOR_PORT", "9100"))
SUPERVISOR_TOKEN = os.getenv("SUPERVISOR_TOKEN", "")  # empty = no auth (dev mode)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_response(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def _error_response(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _pod_dict(pod: Pod) -> dict:
    d = pod.to_dict()
    # Strip sensitive fields from API responses
    d.pop("openrouter_key_hash", None)
    return d


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

@web.middleware
async def auth_middleware(request: web.Request, handler):
    if not SUPERVISOR_TOKEN:
        return await handler(request)

    # Health endpoint is always open
    if request.path == "/api/v1/health":
        return await handler(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return _error_response("Missing Authorization header", 401)

    token = auth_header.removeprefix("Bearer ").strip()
    if token != SUPERVISOR_TOKEN:
        return _error_response("Invalid token", 403)

    return await handler(request)


# ---------------------------------------------------------------------------
# API Server
# ---------------------------------------------------------------------------

class ApiServer:
    def __init__(
        self,
        registry: Registry,
        health_monitor: HealthMonitor,
        nginx_manager: NginxManager,
    ):
        self._registry = registry
        self._health_monitor = health_monitor
        self._nginx_manager = nginx_manager
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None

    def create_app(self) -> web.Application:
        app = web.Application(middlewares=[auth_middleware])
        app.router.add_routes([
            # Pod lifecycle
            web.post("/api/v1/pods", self.create_pod),
            web.get("/api/v1/pods", self.list_pods),
            web.get("/api/v1/pods/{id}", self.get_pod),
            web.post("/api/v1/pods/{id}/start", self.start_pod),
            web.post("/api/v1/pods/{id}/stop", self.stop_pod),
            web.post("/api/v1/pods/{id}/restart", self.restart_pod),
            web.delete("/api/v1/pods/{id}", self.destroy_pod),
            web.get("/api/v1/pods/{id}/logs", self.get_logs),
            web.get("/api/v1/pods/{id}/health", self.get_health),
            web.get("/api/v1/pods/{id}/events", self.get_events),
            # System
            web.get("/api/v1/health", self.supervisor_health),
            web.post("/api/v1/reconcile", self.reconcile),
        ])
        self._app = app
        return app

    async def start(self) -> None:
        if self._app is None:
            self.create_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, SUPERVISOR_HOST, SUPERVISOR_PORT)
        await site.start()
        print(f"[API] Listening on {SUPERVISOR_HOST}:{SUPERVISOR_PORT}")

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        print("[API] Stopped")

    # -- Pod lifecycle endpoints --------------------------------------------

    async def create_pod(self, request: web.Request) -> web.Response:
        """POST /api/v1/pods — Create and start a new pod."""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _error_response("Invalid JSON body")

        pod_id = body.get("id")
        name = body.get("name")
        openrouter_key = body.get("openrouter_key")

        if not pod_id or not name:
            return _error_response("'id' and 'name' are required")
        if not openrouter_key:
            return _error_response("'openrouter_key' is required")

        # Validate pod_id format (prevent path traversal)
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$', pod_id):
            return _error_response("Invalid pod ID: must be alphanumeric with hyphens/underscores, max 63 chars")

        # Check if pod already exists
        existing = await self._registry.get_pod(pod_id)
        if existing and existing.state != "destroyed":
            return _error_response(f"Pod '{pod_id}' already exists (state={existing.state})", 409)

        # Hard-delete destroyed pod row so PK/UNIQUE constraints don't block re-creation
        if existing and existing.state == "destroyed":
            await self._registry.delete_pod(pod_id)

        memory_limit = body.get("memory_limit_mb", 512)
        cpu_limit = body.get("cpu_limit", 0.5)
        manager_id = body.get("manager_id")

        try:
            port = await self._registry.allocate_port()
        except PortExhaustedError as e:
            return _error_response(str(e), 503)

        data_dir = str(AGENTS_ROOT / pod_id)
        key_hash = hashlib.sha256(openrouter_key.encode()).hexdigest()

        # Create registry entry
        pod = await self._registry.create_pod(
            pod_id=pod_id,
            name=name,
            port=port,
            data_dir=data_dir,
            manager_id=manager_id,
            openrouter_key_hash=key_hash,
            memory_limit_mb=memory_limit,
            cpu_limit=cpu_limit,
        )

        # Create container
        try:
            container_id = await docker_manager.create_pod(pod, openrouter_key)
            await self._registry.update_container_id(pod_id, container_id)
            pod = await self._registry.transition(pod_id, "starting")
        except (DockerError, DockerTimeoutError) as e:
            await docker_manager.destroy_pod(pod_id, purge=False)
            await self._registry.transition(pod_id, "error", f"create failed: {e}")
            return _error_response(f"Container creation failed: {e}", 500)

        # Wait for health in background — don't block the response
        # The health monitor will pick it up, but let's do an initial wait
        healthy = await self._health_monitor.check_pod_health(pod_id, port)
        if healthy:
            pod = await self._registry.transition(pod_id, "running")
            await self._registry.update_health(pod_id, "healthy", "initial check passed", 0)
            await self._nginx_manager.regenerate_routes(self._registry)
        else:
            # Still starting — health monitor will handle it
            print(f"[API] Pod {pod_id} created but not yet healthy — health monitor will track")

        pod = await self._registry.get_pod(pod_id)
        return _json_response({"pod": _pod_dict(pod)}, 201)

    async def list_pods(self, request: web.Request) -> web.Response:
        """GET /api/v1/pods — List all pods."""
        state = request.query.get("state")
        manager_id = request.query.get("manager_id")
        pods = await self._registry.list_pods(state=state, manager_id=manager_id)
        return _json_response({"pods": [_pod_dict(p) for p in pods]})

    async def get_pod(self, request: web.Request) -> web.Response:
        """GET /api/v1/pods/{id} — Get pod detail."""
        pod_id = request.match_info["id"]
        pod = await self._registry.get_pod(pod_id)
        if not pod:
            return _error_response(f"Pod '{pod_id}' not found", 404)
        return _json_response({"pod": _pod_dict(pod)})

    async def start_pod(self, request: web.Request) -> web.Response:
        """POST /api/v1/pods/{id}/start — Start a stopped pod."""
        pod_id = request.match_info["id"]
        pod = await self._registry.get_pod(pod_id)
        if not pod:
            return _error_response(f"Pod '{pod_id}' not found", 404)

        try:
            await self._registry.transition(pod_id, "starting")
            await docker_manager.start_pod(pod_id)
            healthy = await self._health_monitor.check_pod_health(pod_id, pod.port)
            if healthy:
                pod = await self._registry.transition(pod_id, "running")
                await self._registry.update_health(pod_id, "healthy", "started", 0)
                await self._nginx_manager.regenerate_routes(self._registry)
            else:
                pod = await self._registry.get_pod(pod_id)
        except InvalidTransitionError as e:
            return _error_response(str(e), 409)
        except DockerError as e:
            await self._registry.transition(pod_id, "error", str(e))
            return _error_response(f"Start failed: {e}", 500)

        return _json_response({"pod": _pod_dict(pod)})

    async def stop_pod(self, request: web.Request) -> web.Response:
        """POST /api/v1/pods/{id}/stop — Stop a running pod."""
        pod_id = request.match_info["id"]
        pod = await self._registry.get_pod(pod_id)
        if not pod:
            return _error_response(f"Pod '{pod_id}' not found", 404)

        try:
            await self._registry.transition(pod_id, "stopping")
            await docker_manager.stop_pod(pod_id)
            pod = await self._registry.transition(pod_id, "stopped")
            await self._registry.update_health(pod_id, "unknown", "stopped", 0)
            await self._nginx_manager.regenerate_routes(self._registry)
        except InvalidTransitionError as e:
            return _error_response(str(e), 409)
        except DockerError as e:
            await self._registry.transition(pod_id, "error", str(e))
            return _error_response(f"Stop failed: {e}", 500)

        return _json_response({"pod": _pod_dict(pod)})

    async def restart_pod(self, request: web.Request) -> web.Response:
        """POST /api/v1/pods/{id}/restart — Restart a pod."""
        pod_id = request.match_info["id"]
        pod = await self._registry.get_pod(pod_id)
        if not pod:
            return _error_response(f"Pod '{pod_id}' not found", 404)

        if pod.state not in ("running", "starting", "error"):
            return _error_response(
                f"Cannot restart pod in '{pod.state}' state", 409
            )

        try:
            await docker_manager.restart_pod(pod_id)
            restart_count = await self._registry.increment_restart_count(pod_id)

            # Force pod to starting state, then check health
            if pod.state != "starting":
                await self._registry.adopt_pod(pod_id, "starting")

            healthy = await self._health_monitor.check_pod_health(pod_id, pod.port)
            if healthy:
                await self._registry.transition(pod_id, "running")
                await self._registry.update_health(pod_id, "healthy", "restarted", 0)
                await self._nginx_manager.regenerate_routes(self._registry)
            else:
                print(f"[API] Pod {pod_id} restarted but not yet healthy — health monitor will track")
        except DockerError as e:
            # Use adopt to avoid InvalidTransitionError if already in error state
            await self._registry.adopt_pod(pod_id, "error")
            return _error_response(f"Restart failed: {e}", 500)

        pod = await self._registry.get_pod(pod_id)
        return _json_response({"pod": _pod_dict(pod)})

    async def destroy_pod(self, request: web.Request) -> web.Response:
        """DELETE /api/v1/pods/{id} — Destroy a pod."""
        pod_id = request.match_info["id"]
        pod = await self._registry.get_pod(pod_id)
        if not pod:
            return _error_response(f"Pod '{pod_id}' not found", 404)

        purge = request.query.get("purge", "false").lower() == "true"

        try:
            # Stop first if running
            if pod.state in ("running", "starting"):
                await self._registry.transition(pod_id, "stopping")
                await docker_manager.stop_pod(pod_id)
                await self._registry.transition(pod_id, "stopped")

            await self._registry.transition(pod_id, "destroying")
            await docker_manager.destroy_pod(pod_id, purge=purge)
            pod = await self._registry.transition(pod_id, "destroyed")
            await self._nginx_manager.regenerate_routes(self._registry)
        except InvalidTransitionError as e:
            return _error_response(str(e), 409)
        except DockerError as e:
            await self._registry.transition(pod_id, "error", str(e))
            return _error_response(f"Destroy failed: {e}", 500)

        return _json_response({"pod": _pod_dict(pod)})

    async def get_logs(self, request: web.Request) -> web.Response:
        """GET /api/v1/pods/{id}/logs — Get container logs."""
        pod_id = request.match_info["id"]
        pod = await self._registry.get_pod(pod_id)
        if not pod:
            return _error_response(f"Pod '{pod_id}' not found", 404)

        try:
            tail = int(request.query.get("tail", "200"))
        except ValueError:
            return _error_response("'tail' must be an integer")
        try:
            logs = await docker_manager.get_logs(pod_id, tail=tail)
        except DockerError as e:
            return _error_response(f"Failed to get logs: {e}", 500)

        return _json_response({"pod_id": pod_id, "logs": logs})

    async def get_health(self, request: web.Request) -> web.Response:
        """GET /api/v1/pods/{id}/health — Get pod health status."""
        pod_id = request.match_info["id"]
        pod = await self._registry.get_pod(pod_id)
        if not pod:
            return _error_response(f"Pod '{pod_id}' not found", 404)

        return _json_response({
            "pod_id": pod_id,
            "health_status": pod.health_status,
            "health_reason": pod.health_reason,
            "last_health_check": pod.last_health_check,
            "consecutive_failures": pod.consecutive_failures,
            "restart_count": pod.restart_count,
        })

    async def get_events(self, request: web.Request) -> web.Response:
        """GET /api/v1/pods/{id}/events — Get pod event history."""
        pod_id = request.match_info["id"]
        pod = await self._registry.get_pod(pod_id)
        if not pod:
            return _error_response(f"Pod '{pod_id}' not found", 404)

        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            return _error_response("'limit' must be an integer")
        events = await self._registry.get_events(pod_id, limit=limit)
        return _json_response({"pod_id": pod_id, "events": events})

    # -- System endpoints ---------------------------------------------------

    async def supervisor_health(self, request: web.Request) -> web.Response:
        """GET /api/v1/health — Supervisor self-health."""
        pods = await self._registry.list_pods()
        running = sum(1 for p in pods if p.state == "running")
        errored = sum(1 for p in pods if p.state == "error")
        return _json_response({
            "status": "ok",
            "total_pods": len(pods),
            "running": running,
            "errored": errored,
        })

    async def reconcile(self, request: web.Request) -> web.Response:
        """POST /api/v1/reconcile — Force Docker↔registry sync."""
        # Import here to avoid circular — supervisor.py owns reconciliation logic
        # Instead, we do it inline
        changes = await self._do_reconcile()
        return _json_response({"reconciled": True, "changes": changes})

    async def _do_reconcile(self) -> list[str]:
        """Sync Docker state with registry."""
        changes = []
        containers = await docker_manager.list_containers()
        container_map = {c.agent_id: c for c in containers}

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
                changes.append(f"adopted {c.agent_id} as {state}")

        # Reconcile state mismatches
        # Use adopt_pod() to bypass state machine — reconciliation is a force-sync
        registry_pods = await self._registry.list_pods()
        for pod in registry_pods:
            c = container_map.get(pod.id)
            if c is None and pod.state in ("running", "starting"):
                await self._registry.adopt_pod(pod.id, "stopped")
                changes.append(f"{pod.id}: {pod.state} -> stopped (container missing)")
            elif c is not None:
                docker_running = c.state == "running"
                if pod.state == "running" and not docker_running:
                    await self._registry.adopt_pod(pod.id, "stopped")
                    changes.append(f"{pod.id}: running -> stopped")
                elif pod.state == "stopped" and docker_running:
                    await self._registry.adopt_pod(pod.id, "running")
                    changes.append(f"{pod.id}: stopped -> running")

        if changes:
            await self._nginx_manager.regenerate_routes(self._registry)

        return changes
