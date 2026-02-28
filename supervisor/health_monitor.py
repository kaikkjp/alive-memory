"""supervisor.health_monitor — Background health polling with auto-restart."""

import asyncio
import os
import time
from typing import Optional

import aiohttp

from supervisor import docker_manager
from supervisor.registry import Registry


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POLL_INTERVAL_S = int(os.getenv("HEALTH_POLL_INTERVAL", "15"))
HEALTH_TIMEOUT_S = int(os.getenv("HEALTH_TIMEOUT", "5"))
MAX_CONSECUTIVE_FAILURES = int(os.getenv("HEALTH_MAX_FAILURES", "3"))
MAX_RESTARTS_PER_HOUR = int(os.getenv("HEALTH_MAX_RESTARTS", "5"))
RESTART_BACKOFF = [0, 10, 30, 60, 120]  # seconds


# ---------------------------------------------------------------------------
# Health Monitor
# ---------------------------------------------------------------------------

class HealthMonitor:
    def __init__(self, registry: Registry):
        self._registry = registry
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._restart_timestamps: dict[str, list[float]] = {}  # pod_id -> [timestamps]

    async def start(self) -> None:
        """Start the background polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        print(f"[HealthMon] Started (interval={POLL_INTERVAL_S}s)")

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        print("[HealthMon] Stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop — checks health of all running pods."""
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[HealthMon] Poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL_S)

    async def _poll_once(self) -> None:
        """Single health check round for all running and starting pods."""
        running = await self._registry.list_pods(state="running")
        starting = await self._registry.list_pods(state="starting")
        pods = running + starting
        if not pods:
            return

        async with aiohttp.ClientSession() as session:
            tasks = [self._check_pod(session, pod) for pod in pods]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_pod(self, session: aiohttp.ClientSession, pod) -> None:
        """Check a single pod's health endpoint."""
        url = f"http://127.0.0.1:{pod.port}/api/health"
        old_status = pod.health_status

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=HEALTH_TIMEOUT_S)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    agent_status = data.get("status", "unknown")
                    reason = data.get("reason", "ok")

                    if agent_status == "alive":
                        await self._registry.update_health(
                            pod.id, "healthy", reason, consecutive_failures=0
                        )
                        # Promote starting pods to running on first healthy check
                        if pod.state == "starting":
                            await self._registry.transition(pod.id, "running")
                            print(f"[HealthMon] {pod.id}: starting -> running (healthy)")
                        elif old_status != "healthy":
                            print(f"[HealthMon] {pod.id}: {old_status} -> healthy")
                    elif agent_status == "degraded":
                        new_failures = pod.consecutive_failures + 1
                        await self._registry.update_health(
                            pod.id, "degraded", reason,
                            consecutive_failures=new_failures,
                        )
                        if old_status != "degraded":
                            print(f"[HealthMon] {pod.id}: {old_status} -> degraded ({reason})")
                    else:
                        await self._handle_failure(pod, f"unexpected status: {agent_status}")
                else:
                    await self._handle_failure(pod, f"HTTP {resp.status}")

        except asyncio.TimeoutError:
            await self._handle_failure(pod, "timeout")
        except aiohttp.ClientError as e:
            await self._handle_failure(pod, f"connection error: {type(e).__name__}")

    async def _handle_failure(self, pod, reason: str) -> None:
        """Handle a health check failure — track consecutive failures, auto-restart if needed."""
        new_failures = pod.consecutive_failures + 1
        print(f"[HealthMon] {pod.id}: failure #{new_failures} ({reason})")

        if new_failures >= MAX_CONSECUTIVE_FAILURES:
            await self._registry.update_health(
                pod.id, "dead", reason, consecutive_failures=new_failures
            )
            # Starting pods that never became healthy → error state, not restart
            if pod.state == "starting":
                print(f"[HealthMon] {pod.id}: failed to start, entering error state")
                await self._registry.transition(pod.id, "error", f"failed to start: {reason}")
            else:
                await self._try_restart(pod)
        else:
            await self._registry.update_health(
                pod.id, "degraded" if new_failures > 1 else pod.health_status,
                reason, consecutive_failures=new_failures,
            )

    async def _try_restart(self, pod) -> None:
        """Attempt to auto-restart a dead pod with backoff and rate limiting."""
        # Rate limit: max restarts per hour
        now = time.monotonic()
        timestamps = self._restart_timestamps.get(pod.id, [])
        timestamps = [t for t in timestamps if now - t < 3600]  # last hour
        self._restart_timestamps[pod.id] = timestamps

        if len(timestamps) >= MAX_RESTARTS_PER_HOUR:
            print(f"[HealthMon] {pod.id}: max restarts ({MAX_RESTARTS_PER_HOUR}/hr) exceeded, entering error state")
            await self._registry.transition(pod.id, "error", "max restarts exceeded")
            return

        # Backoff
        restart_index = min(len(timestamps), len(RESTART_BACKOFF) - 1)
        backoff = RESTART_BACKOFF[restart_index]
        if backoff > 0:
            print(f"[HealthMon] {pod.id}: waiting {backoff}s before restart")
            await asyncio.sleep(backoff)

        # Restart
        try:
            await docker_manager.restart_pod(pod.id)
            restart_count = await self._registry.increment_restart_count(pod.id)
            self._restart_timestamps[pod.id].append(time.monotonic())
            print(f"[HealthMon] {pod.id}: restarted (count={restart_count})")

            # Wait for health to recover
            healthy = await self._wait_for_health(pod.id, pod.port, timeout=30)
            if healthy:
                await self._registry.update_health(
                    pod.id, "healthy", "recovered after restart",
                    consecutive_failures=0,
                )
                print(f"[HealthMon] {pod.id}: healthy after restart")
            else:
                print(f"[HealthMon] {pod.id}: still unhealthy after restart")

        except docker_manager.DockerError as e:
            print(f"[HealthMon] {pod.id}: restart failed: {e}")
            await self._registry.transition(pod.id, "error", f"restart failed: {e}")

    async def _wait_for_health(self, pod_id: str, port: int, timeout: int = 30) -> bool:
        """Wait up to timeout seconds for a pod to respond healthy."""
        url = f"http://127.0.0.1:{port}/api/health"
        deadline = asyncio.get_event_loop().time() + timeout

        async with aiohttp.ClientSession() as session:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=HEALTH_TIMEOUT_S)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("status") == "alive":
                                return True
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
                await asyncio.sleep(2)
        return False

    async def check_pod_health(self, pod_id: str, port: int) -> bool:
        """One-shot health check for a specific pod. Used by API during create flow."""
        return await self._wait_for_health(pod_id, port, timeout=60)
