"""`ap plan` — preview what files and env vars an agent will be granted.

Builds the same mount list the runner uses (truthful preview); secrets are
flagged `[secret]`, never shown.
"""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_pod.container.runner import (
    SANDBOX_CAPABILITIES,
    SANDBOX_HOST_NETWORK,
    SANDBOX_NETWORK,
    SECRET_ENV_RE,
    Mount,
    _ephemeral_env,
    resolve_run,
)
from agent_pod.types import FileMount, ProfileConfig

_RED = "\033[31m"
_RESET = "\033[0m"

_ACCESS_WORDS = {"rw": "read/write", "ro": "read-only"}


@dataclass(frozen=True)
class EnvVar:
    name: str
    forwarded: bool
    internal: bool = False
    description: str | None = None


@dataclass(frozen=True)
class Plan:
    agent: str
    session: str
    mounts: list[Mount]
    envs: list[EnvVar]


def _display(path: Path | None) -> str:
    if path is None:
        return ""
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def build_envs(config, env: Mapping[str, str]) -> list[EnvVar]:
    return [
        EnvVar(name=entry.name, forwarded=entry.name in env, description=entry.description)
        for entry in config.passthrough_envs
    ]


def build_plan(
    *,
    agent: str,
    session: str = "default",
    context_files: list[FileMount] | None = None,
    files: list[FileMount] | None = None,
    user_cfg: ProfileConfig | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    ephemeral: bool = False,
    profile: str = "default",
) -> Plan:
    """Preview an agent run under a profile's effective config.

    `user_cfg` is the resolved config (top-level defaults + active profile
    overrides); when given it drives the agent config (passthrough envs, tmpfs,
    flake, file mounts...) and `ephemeral`. `files` remains for extra
    runtime-only mounts (CLI --context-file entries).
    """
    env = os.environ if env is None else env
    cwd = Path.cwd() if cwd is None else cwd
    resolved = resolve_run(
        agent_name=agent,
        session=session,
        profile=profile,
        cwd=cwd,
        user_cfg=user_cfg,
        context_files=context_files,
        files=files,
        ephemeral=ephemeral,
        env=env,
    )
    envs = build_envs(resolved.config, env)
    if resolved.ephemeral_repo is not None:
        envs = [
            EnvVar(name=key, forwarded=False, internal=True)
            for key in _ephemeral_env(resolved.ephemeral_repo)
        ] + envs
    return Plan(
        agent=agent,
        session=session,
        mounts=resolved.mounts,
        envs=envs,
    )


def color_enabled() -> bool:
    return os.environ.get("NO_COLOR") is None and sys.stdout.isatty()


def _dangerous(mount: Mount, home: Path) -> bool:
    """Flag write always; read-only only when it exposes home or a home child."""
    if mount.mode == "rw":
        return True
    host = mount.host_path
    if mount.mode == "ro" and host is not None and host.is_dir():
        return host == home or host.parent == home
    return False


def _secret_tag(color: bool) -> str:
    tag = "  [secret]"
    return (_RED + tag + _RESET) if color else tag


def render_plan(plan: Plan, *, color: bool = True) -> str:
    home = Path.home()
    width = 60

    def _word(mount: Mount) -> str:
        return _ACCESS_WORDS.get(mount.mode, "")

    # Read/write mounts first, then read-only; tmpfs has no rank (sorted last).
    rank = {"rw": 0, "ro": 1}
    lines = [
        f"{plan.agent}  ·  session: {plan.session}",
        "─" * width,
        "",
        "FILESYSTEM ACCESS",
        "─" * width,
    ]

    for mount in sorted((m for m in plan.mounts if not m.tmpfs), key=lambda m: rank.get(m.mode, 9)):
        word = _word(mount)
        if color and _dangerous(mount, home):
            word = _RED + word + _RESET
        secret = _secret_tag(color) if mount.secret else ""
        lines.append(f"  {word:<10} {_display(mount.source or mount.host_path)}{secret}")
        arrow = f"→ {mount.container_path}"
        if mount.description:
            arrow += f"  · {mount.description}"
        lines.append(f"             {arrow}")

    tmpfs = [mount.container_path for mount in plan.mounts if mount.tmpfs]
    if tmpfs:
        lines.append(f"  tmpfs (no host access): {', '.join(tmpfs)}")

    lines.extend(["", "ENVIRONMENT VARIABLES", "─" * width])
    for env in plan.envs:
        if env.internal:
            status = "set by agent-pod"
        elif env.forwarded:
            status = "forwarded (set in this shell)"
        else:
            status = "not set — not forwarded"
        secret = _secret_tag(color) if SECRET_ENV_RE.search(env.name) else ""
        line = f"  {env.name:<28} {status}{secret}"
        if env.description:
            line += f"  · {env.description}"
        lines.append(line)

    lines.extend(_render_security(width))
    return "\n".join(lines)


def _render_security(width: int) -> list[str]:
    """Truthful network + capability posture (no hardening flags are passed)."""
    network = (
        "Full outbound (default bridge) — no restriction"
        if SANDBOX_NETWORK == "full"
        else "None — no outbound traffic"
    )
    caps = (
        "podman defaults (root) — no hardening"
        if SANDBOX_CAPABILITIES == "default"
        else "DROP ALL (no root escalation)"
    )
    return [
        "",
        "NETWORK & CAPABILITIES",
        "─" * width,
        f"  {'Network Access':<16}: {network}",
        f"  {'Host Network':<16}: {'Enabled' if SANDBOX_HOST_NETWORK else 'Disabled'}",
        f"  {'Capabilities':<16}: {caps}",
    ]
