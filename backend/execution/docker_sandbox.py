"""Docker-based sandbox for secure code execution.

Runs generated workflow code inside an isolated Docker container with:
- Network access (needed for API testing)
- Memory limit (256MB)
- CPU limit (0.5 cores)
- Auto-removal after execution
- Timeout enforcement

Falls back to subprocess sandbox if Docker is not available.
"""

import asyncio
import logging
import tempfile
import os

logger = logging.getLogger("forgeflow.docker_sandbox")

SANDBOX_IMAGE = "python:3.12-slim"
CONTAINER_PREFIX = "forgeflow-sandbox-"

_STDLIB = {
    "asyncio", "os", "sys", "json", "re", "time", "datetime", "collections",
    "functools", "itertools", "pathlib", "logging", "typing", "uuid", "hashlib",
    "base64", "urllib", "tempfile", "math", "random", "string", "io", "struct",
    "csv", "enum", "email", "smtplib", "imaplib", "http", "socket", "ssl",
    "traceback", "inspect", "copy", "textwrap", "contextlib", "dataclasses", "abc",
}
_PIP_MAP = {
    "httpx": "httpx>=0.26.0",
    "websockets": "websockets>=12.0",
    "requests": "requests>=2.31.0",
    "aiohttp": "aiohttp>=3.9.0",
    "slack_sdk": "slack-sdk>=3.27.0",
    "google": "google-api-python-client>=2.0.0",
    "dotenv": "python-dotenv>=1.0.0",
    "pydantic": "pydantic>=2.0.0",
    "yaml": "pyyaml>=6.0",
}


def _extract_requirements_for_sandbox(code: str) -> str:
    """Extract pip-installable packages from import statements."""
    imports: set[str] = set()
    for line in code.split("\n"):
        line = line.strip()
        if line.startswith("import "):
            imports.add(line.split()[1].split(".")[0])
        elif line.startswith("from "):
            imports.add(line.split()[1].split(".")[0])

    deps = []
    for mod in sorted(imports):
        if mod in _STDLIB or mod.startswith("_"):
            continue
        deps.append(_PIP_MAP.get(mod, mod))

    # Always include httpx and websockets as baseline
    for baseline in ("httpx>=0.26.0", "websockets>=12.0"):
        if baseline not in deps:
            deps.append(baseline)

    return "\n".join(deps) + "\n"


async def is_docker_available() -> bool:
    """Check if Docker is installed and running."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "info",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
        return proc.returncode == 0
    except (FileNotFoundError, asyncio.TimeoutError, Exception):
        return False


async def ensure_sandbox_image() -> bool:
    """Pull the sandbox Docker image if not already available."""
    try:
        # Check if image exists
        proc = await asyncio.create_subprocess_exec(
            "docker", "image", "inspect", SANDBOX_IMAGE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode == 0:
            return True

        # Pull the image
        logger.info(f"Pulling Docker sandbox image: {SANDBOX_IMAGE}")
        proc = await asyncio.create_subprocess_exec(
            "docker", "pull", SANDBOX_IMAGE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)
        return proc.returncode == 0
    except Exception as e:
        logger.error(f"Failed to ensure sandbox image: {e}")
        return False


async def execute_code_docker(
    code: str,
    timeout: int = 30,
    network: bool = True,
    extra_files: dict[str, str] | None = None,
) -> dict:
    """Execute Python code inside a Docker container.

    Args:
        code: Python source code to execute
        timeout: Execution timeout in seconds
        network: Whether to allow network access (needed for API calls)
        extra_files: Optional dict of {path: content} for multi-file projects

    Returns:
        dict with keys: success, stdout, stderr, error, execution_time
    """
    import time
    import uuid

    start = time.time()
    container_name = f"{CONTAINER_PREFIX}{uuid.uuid4().hex[:8]}"

    # Write code to a temp directory
    with tempfile.TemporaryDirectory(prefix="forgeflow_") as tmpdir:
        code_file = os.path.join(tmpdir, "workflow.py")
        with open(code_file, "w") as f:
            f.write(code)

        # Write extra files (multi-file projects: clients/, config.py, etc.)
        if extra_files:
            for fpath, fcontent in extra_files.items():
                full = os.path.join(tmpdir, fpath)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w") as ef:
                    ef.write(fcontent)

        # Generate requirements.txt from code imports (sandbox runs before deploy)
        req_content = _extract_requirements_for_sandbox(code)
        req_file = os.path.join(tmpdir, "requirements.txt")
        with open(req_file, "w") as rf:
            rf.write(req_content)

        # Write a setup script that installs dependencies then runs the workflow
        setup_script = os.path.join(tmpdir, "run.sh")
        with open(setup_script, "w") as sf:
            sf.write(
                "#!/bin/sh\n"
                "pip install -q -r requirements.txt 2>/dev/null\n"
                "python workflow.py\n"
            )
        os.chmod(setup_script, 0o755)

        # Collect relevant env vars to pass into the container
        env_prefixes = (
            "SLACK_", "GMAIL_", "GOOGLE_", "DERIV_",
            "SHEETS_", "WEBHOOK_", "API_", "AUTH_", "TOKEN_",
        )
        env_args = []
        for key, val in os.environ.items():
            if any(key.startswith(p) for p in env_prefixes):
                env_args.extend(["-e", f"{key}={val}"])

        # Build docker run command
        cmd = [
            "docker", "run",
            "--rm",                          # Auto-remove after exit
            "--name", container_name,
            "--memory", "256m",              # Memory limit
            "--cpus", "0.5",                 # CPU limit
            "--tmpfs", "/tmp:size=64m",      # Writable /tmp
            "-v", f"{tmpdir}:/app",          # Mount code (writable for pip)
            "-w", "/app",
        ]

        # Pass env vars
        cmd.extend(env_args)

        if not network:
            cmd.extend(["--network", "none"])

        cmd.extend([
            SANDBOX_IMAGE,
            "sh", "run.sh",
        ])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout + 5  # 5s grace for Docker overhead
                )
            except asyncio.TimeoutError:
                # Kill the container
                kill_proc = await asyncio.create_subprocess_exec(
                    "docker", "kill", container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await kill_proc.communicate()

                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "",
                    "error": f"Execution timed out after {timeout}s (Docker sandbox)",
                    "execution_time": time.time() - start,
                    "sandbox": "docker",
                }

            elapsed = time.time() - start
            stdout_str = stdout.decode("utf-8", errors="replace")[:5000]
            stderr_str = stderr.decode("utf-8", errors="replace")[:5000]

            if proc.returncode == 0:
                return {
                    "success": True,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "error": None,
                    "execution_time": elapsed,
                    "sandbox": "docker",
                }
            else:
                return {
                    "success": False,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "error": stderr_str or f"Process exited with code {proc.returncode}",
                    "execution_time": elapsed,
                    "sandbox": "docker",
                }

        except FileNotFoundError:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": "Docker not found",
                "execution_time": time.time() - start,
                "sandbox": "none",
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": f"Docker execution error: {str(e)}",
                "execution_time": time.time() - start,
                "sandbox": "docker",
            }
