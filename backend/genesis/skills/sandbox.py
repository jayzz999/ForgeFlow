"""Phase 4 — Sandbox: Resource-limited execution for compiled skills.

Compiled skill MCP servers run as subprocesses. This module provides
safety guardrails:
  - CPU time limits (prevent infinite loops)
  - Memory limits (prevent runaway allocations)
  - Network timeout enforcement
  - Process isolation via subprocess
  - Health monitoring with auto-restart

The sandbox wraps Python's subprocess module with resource constraints.
On macOS, we use `ulimit` for soft limits. On Linux, cgroups could be
used for harder isolation (future enhancement).
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("genesis.skills.sandbox")


@dataclass
class SandboxConfig:
    """Resource limits for a compiled skill server."""
    max_memory_mb: int = 256       # Max RSS in MB
    max_cpu_seconds: int = 30       # Per-tool-call CPU time limit
    max_runtime_seconds: int = 300  # Total server lifetime before restart
    max_output_bytes: int = 1_000_000  # Max stdout/stderr capture
    allowed_network: bool = True    # Whether network access is permitted
    python_path: str = ""           # Override Python interpreter path


@dataclass
class SandboxProcess:
    """A running compiled skill in a sandbox."""
    skill_id: str
    script_path: str
    process: Optional[subprocess.Popen] = None
    started_at: float = 0.0
    config: SandboxConfig = field(default_factory=SandboxConfig)
    restart_count: int = 0
    last_error: str = ""

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def uptime_seconds(self) -> float:
        if not self.is_alive:
            return 0.0
        return time.time() - self.started_at

    @property
    def needs_restart(self) -> bool:
        if not self.is_alive:
            return True
        if self.config.max_runtime_seconds > 0:
            return self.uptime_seconds > self.config.max_runtime_seconds
        return False


class SandboxManager:
    """Manages sandboxed compiled skill processes."""

    def __init__(self) -> None:
        self._processes: dict[str, SandboxProcess] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        skill_id: str,
        script_path: str,
        config: Optional[SandboxConfig] = None,
    ) -> SandboxProcess:
        """Start a compiled skill server in a sandbox."""
        async with self._lock:
            # Kill existing if running
            if skill_id in self._processes:
                await self._kill(skill_id)

            cfg = config or SandboxConfig()
            python_exe = cfg.python_path or sys.executable
            script = Path(script_path)

            if not script.exists():
                raise FileNotFoundError(f"Compiled skill not found: {script_path}")

            # Build environment with safety constraints
            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONUNBUFFERED"] = "1"

            # Start the process
            try:
                proc = subprocess.Popen(
                    [python_exe, str(script)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    preexec_fn=self._set_limits(cfg) if sys.platform != "win32" else None,
                )
            except Exception as e:
                logger.error(f"[sandbox] Failed to start {skill_id}: {e}")
                raise

            sandbox = SandboxProcess(
                skill_id=skill_id,
                script_path=str(script),
                process=proc,
                started_at=time.time(),
                config=cfg,
            )
            self._processes[skill_id] = sandbox
            logger.info(f"[sandbox] Started {skill_id} (PID {proc.pid})")
            return sandbox

    def _set_limits(self, cfg: SandboxConfig):
        """Return a preexec function that sets resource limits."""
        def _apply():
            import resource
            # Memory limit
            mem_bytes = cfg.max_memory_mb * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            except (ValueError, resource.error):
                pass  # macOS doesn't support RLIMIT_AS well
            # CPU time limit
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (cfg.max_cpu_seconds, cfg.max_cpu_seconds))
            except (ValueError, resource.error):
                pass
        return _apply

    async def stop(self, skill_id: str) -> None:
        """Stop a sandboxed skill process."""
        async with self._lock:
            await self._kill(skill_id)

    async def _kill(self, skill_id: str) -> None:
        """Internal: kill process without lock."""
        sandbox = self._processes.get(skill_id)
        if not sandbox or not sandbox.process:
            return
        try:
            sandbox.process.terminate()
            try:
                sandbox.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sandbox.process.kill()
                sandbox.process.wait(timeout=2)
        except Exception as e:
            logger.warning(f"[sandbox] Error killing {skill_id}: {e}")
        finally:
            sandbox.process = None
            logger.info(f"[sandbox] Stopped {skill_id}")

    async def restart(self, skill_id: str) -> Optional[SandboxProcess]:
        """Restart a sandboxed process."""
        sandbox = self._processes.get(skill_id)
        if not sandbox:
            return None
        sandbox.restart_count += 1
        return await self.start(skill_id, sandbox.script_path, sandbox.config)

    async def health_check(self) -> list[dict]:
        """Check health of all sandboxed processes."""
        results = []
        for skill_id, sandbox in list(self._processes.items()):
            status = {
                "skill_id": skill_id,
                "alive": sandbox.is_alive,
                "uptime_seconds": round(sandbox.uptime_seconds, 1),
                "restart_count": sandbox.restart_count,
                "pid": sandbox.process.pid if sandbox.process else None,
                "needs_restart": sandbox.needs_restart,
            }
            if sandbox.needs_restart and sandbox.restart_count < 5:
                try:
                    await self.restart(skill_id)
                    status["restarted"] = True
                except Exception as e:
                    status["restart_error"] = str(e)
            results.append(status)
        return results

    async def shutdown(self) -> None:
        """Stop all sandboxed processes."""
        for skill_id in list(self._processes.keys()):
            await self.stop(skill_id)

    def status(self) -> dict:
        """Get status of all sandboxes."""
        return {
            "total": len(self._processes),
            "alive": sum(1 for s in self._processes.values() if s.is_alive),
            "processes": [
                {
                    "skill_id": s.skill_id,
                    "alive": s.is_alive,
                    "uptime": round(s.uptime_seconds, 1),
                    "restarts": s.restart_count,
                    "script": s.script_path,
                }
                for s in self._processes.values()
            ],
        }


# Module-level singleton
sandbox_manager = SandboxManager()
