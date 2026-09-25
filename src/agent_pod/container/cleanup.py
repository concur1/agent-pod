"""Container cleanup utilities."""

import logging
import subprocess

logger = logging.getLogger(__name__)


def container_running(container_name: str) -> bool:
    """Whether a container with this exact name is currently running.

    Filters by name and checks exact membership (podman's name filter matches
    substrings). Any podman failure is treated as "not running" so a missing
    podman or a blip never blocks a launch.
    """
    try:
        out = subprocess.run(
            ["podman", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return isinstance(out, str) and container_name in {line.strip() for line in out.splitlines()}


def cleanup_stale_container(container_name: str) -> None:
    """Remove any lingering container of the same name before launch."""
    result = subprocess.run(
        ["podman", "rm", "-f", container_name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and "no such container" not in result.stderr.lower():
        logger.warning(
            "Failed to clean up existing container '%s': %s", container_name, result.stderr.strip()
        )
