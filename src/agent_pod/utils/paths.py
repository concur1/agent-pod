"""Path utilities."""

from pathlib import Path


def agent_pod_root() -> Path:
    """Return the agent_pod package root (anchor for bundled data files)."""
    return Path(__file__).resolve().parent.parent
