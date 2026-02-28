"""supervisor.nginx_manager — Route generation, idempotent config writes, reload."""

import os
import pathlib
import re
from typing import Optional

from supervisor.docker_manager import run_cmd, DockerError
from supervisor.registry import Registry


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NGINX_CONF_PATH = os.getenv(
    "NGINX_CONF_PATH", "/etc/nginx/sites-available/alive-lounge"
)
MARKER_BEGIN = "# --- BEGIN AGENT ROUTES ---"
MARKER_END = "# --- END AGENT ROUTES ---"


# ---------------------------------------------------------------------------
# Nginx Manager
# ---------------------------------------------------------------------------

class NginxManager:
    def __init__(self, conf_path: str = NGINX_CONF_PATH):
        self._conf_path = pathlib.Path(conf_path)

    async def regenerate_routes(self, registry: Registry) -> bool:
        """Rebuild nginx location blocks from registry. Returns True if config changed."""
        if not self._conf_path.exists():
            print(f"[NginxMgr] Config not found at {self._conf_path} — skipping (dev mode)")
            return False

        pods = await registry.list_pods(state="running")
        new_block = self._build_routes(pods)

        current_block = self._read_between_markers()
        if current_block is not None and current_block.strip() == new_block.strip():
            return False  # No change needed

        # Write new routes
        self._write_between_markers(new_block)

        # Test config
        try:
            await run_cmd("nginx", "-t", timeout=10)
        except DockerError as e:
            # Revert on failure
            print(f"[NginxMgr] nginx -t failed, reverting: {e}")
            if current_block is not None:
                self._write_between_markers(current_block)
            raise

        # Reload
        await run_cmd("systemctl", "reload", "nginx", timeout=10)
        print(f"[NginxMgr] Regenerated routes for {len(pods)} pod(s)")
        return True

    def _build_routes(self, pods: list) -> str:
        """Build nginx location blocks for running pods."""
        blocks = []
        for pod in pods:
            if pod.port is None:
                continue
            blocks.append(
                f"    location /{pod.id}/ {{\n"
                f"        proxy_pass http://127.0.0.1:{pod.port}/;\n"
                f"        proxy_http_version 1.1;\n"
                f"        proxy_set_header Upgrade $http_upgrade;\n"
                f'        proxy_set_header Connection "upgrade";\n'
                f"        proxy_set_header Host $host;\n"
                f"        proxy_set_header X-Real-IP $remote_addr;\n"
                f"        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                f"        proxy_read_timeout 60s;\n"
                f"    }}"
            )
        return "\n".join(blocks)

    def _read_between_markers(self) -> Optional[str]:
        """Read content between BEGIN/END markers. Returns None if markers not found."""
        try:
            content = self._conf_path.read_text()
        except OSError:
            return None

        begin_idx = content.find(MARKER_BEGIN)
        end_idx = content.find(MARKER_END)
        if begin_idx == -1 or end_idx == -1 or begin_idx >= end_idx:
            return None

        start = begin_idx + len(MARKER_BEGIN) + 1  # skip newline after marker
        return content[start:end_idx].rstrip()

    def _write_between_markers(self, new_routes: str) -> None:
        """Replace content between BEGIN/END markers with new routes."""
        content = self._conf_path.read_text()

        begin_idx = content.find(MARKER_BEGIN)
        end_idx = content.find(MARKER_END)
        if begin_idx == -1 or end_idx == -1:
            print("[NginxMgr] Markers not found in config — cannot update routes")
            return

        before = content[:begin_idx + len(MARKER_BEGIN)]
        after = content[end_idx:]

        if new_routes.strip():
            new_content = before + "\n" + new_routes + "\n" + after
        else:
            new_content = before + "\n" + after

        self._conf_path.write_text(new_content)
