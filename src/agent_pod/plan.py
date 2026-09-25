"""`ap plan` — preview what files and env vars an agent will be granted.

Builds the same mount list the runner uses (truthful preview); secrets are
flagged `[secret]`, never shown.
"""

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from agent_pod.config import get_effective_agent_config
from agent_pod.container.runner import (
    BASE_STATE_DIR,
    Mount,
    SecurityProfile,
    _ephemeral_env,
    build_mounts,
    repo_workspace,
)
from agent_pod.types import FileMount
from agent_pod.utils.names import get_instance_name

_RED = "\033[31m"
_RESET = "\033[0m"

# Env vars whose name looks like a credential are treated as secrets.
_SECRET_ENV_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)

_ACCESS_WORDS = {"rw": "read/write", "ro": "read-only"}


@dataclass(frozen=True)
class EnvVar:
    name: str
    forwarded: bool
    internal: bool = False


@dataclass(frozen=True)
class Plan:
    agent: str
    session: str
    mounts: list[Mount]
    envs: list[EnvVar]
    security: SecurityProfile = field(default_factory=SecurityProfile)


def _display(path: Path | None) -> str:
    if path is None:
        return ""
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def build_envs(config, env: Mapping[str, str]) -> list[EnvVar]:
    return [EnvVar(name=key, forwarded=key in env) for key in config.passthrough_envs]


def build_plan(
    *,
    agent: str,
    session: str = "default",
    context_files: list[FileMount] | None = None,
    files: list[FileMount] | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    ephemeral: bool = False,
    profile: str = "default",
) -> Plan:
    config = get_effective_agent_config(agent)
    extra_files = [*(files or []), *(context_files or [])]
    if extra_files:
        config = config.model_copy(update={"files": [*config.files, *extra_files]})
    env = os.environ if env is None else env
    cwd = Path.cwd() if cwd is None else cwd
    agent_host_dir = BASE_STATE_DIR / (agent if session == "default" else f"{agent}/{session}")
    prompts_dir = BASE_STATE_DIR / "prompts"
    ephemeral_repo = repo_workspace(
        ephemeral=ephemeral,
        cwd=cwd,
        branch=f"agent/{profile}/{session}",
        worktree=f"/sandbox/{get_instance_name(config, session)}",
    )
    mounts = build_mounts(
        agent_name=agent,
        config=config,
        cwd=cwd,
        agent_host_dir=agent_host_dir,
        prompts_dir=prompts_dir,
        ephemeral_repo=ephemeral_repo,
    )
    envs = build_envs(config, env)
    if ephemeral_repo is not None:
        envs = [
            EnvVar(name=key, forwarded=False, internal=True)
            for key in _ephemeral_env(ephemeral_repo)
        ] + envs
    return Plan(
        agent=agent,
        session=session,
        mounts=mounts,
        envs=envs,
        # No hardening flags are passed today, so this reflects podman's defaults
        # (see SecurityProfile in runner.py); keep in sync with _podman_command.
        security=SecurityProfile(),
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
        secret = _secret_tag(color) if _SECRET_ENV_RE.search(env.name) else ""
        lines.append(f"  {env.name:<28} {status}{secret}")

    lines.extend(_render_security(plan.security, width))
    return "\n".join(lines)


def _render_security(profile: SecurityProfile, width: int) -> list[str]:
    """Truthful network + capability posture."""
    network = (
        "Full outbound (default bridge) — no restriction"
        if profile.network == "full"
        else "None — no outbound traffic"
    )
    caps = (
        "podman defaults (root) — no hardening"
        if profile.capabilities == "default"
        else "DROP ALL (no root escalation)"
    )
    return [
        "",
        "NETWORK & CAPABILITIES",
        "─" * width,
        f"  {'Network Access':<16}: {network}",
        f"  {'Host Network':<16}: {'Enabled' if profile.host_network else 'Disabled'}",
        f"  {'Capabilities':<16}: {caps}",
    ]
