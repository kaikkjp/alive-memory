"""supervisor.docker_manager — Container lifecycle via async subprocess."""

import asyncio
import json
import os
import pathlib
import secrets
import shutil
from dataclasses import dataclass
from typing import Optional

from supervisor.registry import Pod


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).parent.parent
DEFAULT_IDENTITY_TEMPLATE = REPO_ROOT / "config" / "default_digital_lifeform.yaml"
ENGINE_CONFIG_TEMPLATE = REPO_ROOT / "engine" / "alive_config.yaml"
AGENTS_ROOT = pathlib.Path(os.getenv("AGENTS_ROOT", "/data/alive-agents"))
DOCKER_IMAGE = os.getenv("SUPERVISOR_DOCKER_IMAGE", "alive-engine:latest")
CONTAINER_PREFIX = "alive-agent-"
APPUSER_UID = 1000  # matches Dockerfile.agent non-root user


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DockerError(Exception):
    def __init__(self, message: str, returncode: int = -1, stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class DockerTimeoutError(DockerError):
    pass


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str


async def run_cmd(
    *args: str,
    check: bool = True,
    timeout: int = 30,
) -> CmdResult:
    """Run a command asynchronously. Raises DockerError on failure if check=True."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise DockerTimeoutError(
            f"Command timed out after {timeout}s: {' '.join(args)}"
        )

    result = CmdResult(
        returncode=proc.returncode,
        stdout=stdout_bytes.decode() if stdout_bytes else "",
        stderr=stderr_bytes.decode() if stderr_bytes else "",
    )

    if check and result.returncode != 0:
        raise DockerError(
            f"Command failed (rc={result.returncode}): {' '.join(args)}\n{result.stderr}",
            returncode=result.returncode,
            stderr=result.stderr,
        )
    return result


# ---------------------------------------------------------------------------
# Container operations
# ---------------------------------------------------------------------------

def _container_name(pod_id: str) -> str:
    return f"{CONTAINER_PREFIX}{pod_id}"


async def create_pod(pod: Pod, openrouter_key: str) -> str:
    """Provision directories, copy configs, launch container. Returns container ID."""
    data_dir = pathlib.Path(pod.data_dir)

    # 1. Create directory structure
    (data_dir / "db").mkdir(parents=True, exist_ok=True)
    (data_dir / "memory").mkdir(parents=True, exist_ok=True)

    # 2. Copy default identity if not present
    identity_path = data_dir / "identity.yaml"
    if not identity_path.exists():
        shutil.copy2(str(DEFAULT_IDENTITY_TEMPLATE), str(identity_path))

    # 3. Copy alive_config.yaml if not present
    config_path = data_dir / "alive_config.yaml"
    if not config_path.exists():
        shutil.copy2(str(ENGINE_CONFIG_TEMPLATE), str(config_path))

    # 4. Set ownership to appuser (UID 1000)
    await run_cmd(
        "chown", "-R", f"{APPUSER_UID}:{APPUSER_UID}",
        str(data_dir / "db"), str(data_dir / "memory"),
        check=False,  # may fail in dev without root — non-fatal
    )

    # 5. Generate server token
    server_token = secrets.token_hex(32)

    # 6. docker run
    container_name = _container_name(pod.id)
    result = await run_cmd(
        "docker", "run", "-d",
        "--name", container_name,
        "-p", f"127.0.0.1:{pod.port}:8080",
        "-v", f"{data_dir}/:/agent-config/",
        "-e", f"AGENT_ID={pod.id}",
        "-e", f"OPENROUTER_API_KEY={openrouter_key}",
        "-e", "AGENT_CONFIG_DIR=/agent-config/",
        "-e", f"SHOPKEEPER_SERVER_TOKEN={server_token}",
        "--restart", "unless-stopped",
        "--memory", f"{pod.memory_limit_mb}m",
        "--cpus", str(pod.cpu_limit),
        DOCKER_IMAGE,
        timeout=120,
    )

    container_id = result.stdout.strip()[:12]
    print(f"[DockerMgr] Created container {container_name} ({container_id}) on port {pod.port}")
    return container_id


async def start_pod(pod_id: str) -> None:
    """Start a stopped container."""
    await run_cmd("docker", "start", _container_name(pod_id), timeout=15)
    print(f"[DockerMgr] Started {_container_name(pod_id)}")


async def stop_pod(pod_id: str) -> None:
    """Stop a running container."""
    await run_cmd("docker", "stop", _container_name(pod_id), timeout=15)
    print(f"[DockerMgr] Stopped {_container_name(pod_id)}")


async def restart_pod(pod_id: str) -> None:
    """Restart a container (preserves container identity)."""
    await run_cmd("docker", "restart", _container_name(pod_id), timeout=30)
    print(f"[DockerMgr] Restarted {_container_name(pod_id)}")


async def destroy_pod(pod_id: str, purge: bool = False) -> None:
    """Stop and remove container. Optionally purge agent data."""
    container = _container_name(pod_id)
    await run_cmd("docker", "stop", container, check=False, timeout=15)
    await run_cmd("docker", "rm", container, check=False, timeout=15)
    print(f"[DockerMgr] Destroyed {container}")

    if purge:
        data_dir = AGENTS_ROOT / pod_id
        if data_dir.exists():
            shutil.rmtree(str(data_dir), ignore_errors=True)
            print(f"[DockerMgr] Purged data at {data_dir}")


async def get_logs(pod_id: str, tail: int = 200) -> str:
    """Retrieve container logs."""
    result = await run_cmd(
        "docker", "logs", "--tail", str(tail), _container_name(pod_id),
        check=False, timeout=10,
    )
    return result.stdout + result.stderr


async def inspect_container(pod_id: str) -> Optional[dict]:
    """Get container state from Docker. Returns None if container doesn't exist."""
    result = await run_cmd(
        "docker", "inspect", _container_name(pod_id),
        check=False, timeout=10,
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        return data[0] if data else None
    except (json.JSONDecodeError, IndexError):
        return None


@dataclass
class ContainerInfo:
    name: str
    agent_id: str
    state: str
    port: Optional[int]


async def list_containers() -> list[ContainerInfo]:
    """List all alive-agent-* containers with name, state, port."""
    result = await run_cmd(
        "docker", "ps", "-a",
        "--filter", f"name={CONTAINER_PREFIX}",
        "--format", "{{.Names}}\t{{.State}}\t{{.Ports}}",
        check=False, timeout=10,
    )
    if not result.stdout.strip():
        return []

    containers = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[0]
        state = parts[1]
        port_str = parts[2] if len(parts) > 2 else ""

        agent_id = name.removeprefix(CONTAINER_PREFIX)
        port = _parse_host_port(port_str)

        containers.append(ContainerInfo(
            name=name,
            agent_id=agent_id,
            state=state,
            port=port,
        ))
    return containers


def _parse_host_port(port_str: str) -> Optional[int]:
    """Extract host port from Docker port mapping string like '127.0.0.1:9001->8080/tcp'."""
    if not port_str:
        return None
    try:
        # Format: "127.0.0.1:9001->8080/tcp" or "0.0.0.0:9001->8080/tcp"
        for mapping in port_str.split(","):
            mapping = mapping.strip()
            if "->8080" in mapping:
                host_part = mapping.split("->")[0]
                port = int(host_part.split(":")[-1])
                return port
    except (ValueError, IndexError):
        pass
    return None
