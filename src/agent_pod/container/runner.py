"""Container runner logic."""

import logging
import os
import re
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_pod.config import get_effective_agent_config
from agent_pod.container.builder import build_image
from agent_pod.container.cleanup import cleanup_stale_container, container_running
from agent_pod.prompts import load_base_prompt
from agent_pod.types import STATE_DIR, AgentConfig, FileMount
from agent_pod.utils.names import get_instance_name, valid_session_name

logger = logging.getLogger(__name__)

# Reserved `source` values for content agent-pod generates at runtime rather than
# mounting from the host. Used by `files` entries in the agent configs.
BUILTIN_INSTRUCTIONS = "builtin:instructions"
BUILTIN_GIT_WORKFLOW = "builtin:git-workflow"

BASE_STATE_DIR = Path.home() / STATE_DIR

# Container paths shared by every agent (not per-agent configurable).
GITCONFIG_CONTAINER = "/root/.gitconfig"
CONTEXTS_CONTAINER_DIR = "/root/.config/agent/contexts"
# In ephemeral git runs the host repo's .git is mounted here so the container
# can create its own per-session worktree on it (AP_REPO_GIT for the entrypoint).
EPHEMERAL_GITDIR_CONTAINER = "/repo/.git"

# opencode writes a $schema-only skeleton (possibly with trailing comma) as its
# default; treat as empty so seeding replaces it with the host config.
_SCHEMA_ONLY_RE = re.compile(r'^\{\s*"\$schema"\s*:\s*"[^"]*"\s*,?\s*\}$')


@dataclass(frozen=True)
class Mount:
    """A host path mounted into the container, or a container-private tmpfs.

    `host_path` is what podman actually mounts; `source` is the host path shown
    to users when it differs (e.g. a credential file copied into the session
    state dir, whose original lives elsewhere on the host).
    """

    host_path: Path | None
    container_path: str
    mode: str  # "rw", "ro", or "" for tmpfs
    kind: str  # repo|file|context|instructions|state|credential|gitconfig|tmpfs
    source: Path | None = None
    secret: bool = False
    tmpfs: bool = False
    description: str | None = None


@dataclass(frozen=True)
class EphemeralRepo:
    """How an ephemeral git run exposes the repo to the container.

    The host's `.git` is mounted read-write and the container creates its own
    per-session worktree in a subfolder of /sandbox, so only committed files
    ever reach the host. None means the working tree is mounted directly at
    /sandbox instead.
    """

    gitdir: Path  # host .git, mounted at gitdir_container (AP_REPO_GIT)
    branch: str  # agent/<profile>/<session> (AP_BRANCH)
    base: str  # host HEAD commit the worktree forks from (AP_BASE)
    worktree: str  # container path the worktree is checked out at (AP_WORKTREE)
    gitdir_container: str = EPHEMERAL_GITDIR_CONTAINER


@dataclass(frozen=True)
class SecurityProfile:
    """Network + kernel-capability posture granted to the sandbox container.

    The runner passes no `--network` or `--cap-*` flags, so this reflects
    podman's defaults. Single source of truth for `ap plan`; if hardening flags
    are added to `_podman_command`, update this so the preview stays truthful.
    """

    network: str = "full"  # "full" (default bridge) | "none"
    host_network: bool = False
    capabilities: str = "default"  # "default" (no drop) | "drop_all"


def _is_placeholder(content: str) -> bool:
    stripped = content.strip()
    return stripped == "" or stripped == "{}" or _SCHEMA_ONLY_RE.match(stripped) is not None


def _seed_source(entry: FileMount, settings_file: Path | None) -> Path | None:
    """The host path a writable state file is seeded from on first run."""
    # A caller-supplied settings file overrides the host seed for new sessions.
    if entry.name == "settings.json" and settings_file is not None and settings_file.exists():
        return settings_file
    if entry.source is None or not entry.seed:
        return None
    return Path(entry.source).expanduser()


def _ensure_state_file(file_path: Path, seed_src: Path | None) -> None:
    is_placeholder = file_path.exists() and _is_placeholder(file_path.read_text())
    if file_path.exists() and not is_placeholder:
        return
    if seed_src is not None and seed_src.exists():
        shutil.copy2(seed_src, file_path)
        return
    if file_path.exists() and is_placeholder:
        return
    if file_path.suffix == ".json":
        file_path.write_text("{}\n")
    else:
        file_path.touch()


def _warn_missing(entry: FileMount, host: Path) -> None:
    if not entry.optional:
        logger.warning("%s: source not found, skipping: %s", entry.name, host)


_GITCONFIG_SAFE = "[safe]\n\tdirectory = *\n"
_GITCONFIG_DEFAULT_USER = "[user]\n\tname = AI Agent\n\temail = agent@localhost\n"


def _git_global_get(key: str, env: Mapping[str, str]) -> str | None:
    """Resolved global git value for `key` on the host; None if unset."""
    try:
        out = subprocess.run(
            ["git", "config", "--global", "--get", key],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out or None


def _git_user_block(env: Mapping[str, str] | None = None) -> str:
    """Host's global git identity as a `[user]` block; default when unset.

    Read through `git config` (not the raw file) so `[include]`d identity is
    picked up too. The seeded `.gitconfig` is bind-mounted into the container,
    where `git config --global` cannot rewrite it (rename onto a mounted file
    is EBUSY), so the identity must already be present for ephemeral commits.
    """
    env = {**os.environ, **(env or {})}
    email = _git_global_get("user.email", env)
    if email is None:
        return _GITCONFIG_DEFAULT_USER
    name = _git_global_get("user.name", env)
    block = ["[user]"]
    if name:
        block.append(f"\tname = {name}")
    block.append(f"\temail = {email}")
    return "\n".join(block) + "\n"


def _gitconfig_seed() -> str:
    return _GITCONFIG_SAFE + "\n" + _git_user_block()


def _mainline_branch(cwd: Path) -> str | None:
    """The local mainline branch ('main', else 'master'); None if neither exists.

    None means "don't prune": without a mainline to compare against we never
    delete a session branch.
    """
    for name in ("main", "master"):
        try:
            result = subprocess.run(
                ["git", "-C", str(cwd), "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        if result.returncode == 0:
            return name
    return None


def _delete_noop_branch(cwd: Path, branch: str, mainline: str) -> bool:
    """Delete `branch` when its tip is an ancestor of `mainline`; True if deleted."""
    try:
        contained = subprocess.run(
            ["git", "-C", str(cwd), "merge-base", "--is-ancestor", branch, mainline],
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    if contained.returncode != 0:
        return False
    deleted = subprocess.run(
        ["git", "-C", str(cwd), "branch", "-D", branch], capture_output=True, text=True
    )
    return deleted.returncode == 0


def prune_matching_branch(cwd: Path, branch: str) -> bool:
    """Delete `branch` when it adds no commits to the mainline.

    A branch whose tip is an ancestor of the mainline carries no work beyond it
    (never committed, or its commits were folded back), so it's a no-op session
    branch safe to drop; branches with unique commits stay for review.
    """
    mainline = _mainline_branch(cwd)
    if mainline is None:
        return False
    return _delete_noop_branch(cwd, branch, mainline)


def tidy_noop_branches(cwd: Path) -> int:
    """Prune leftover `agent/*` branches that add nothing to the mainline.

    Sweeps what a crashed or legacy session never pruned on close. Live sessions
    are untouched: their branch is checked out in a worktree, so `branch -D`
    refuses it. Returns the number of branches deleted.
    """
    mainline = _mainline_branch(cwd)
    if mainline is None:
        return 0
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(cwd),
                "for-each-ref",
                "--format=%(refname:short)",
                "refs/heads/agent/",
            ],
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0
    return sum(_delete_noop_branch(cwd, branch, mainline) for branch in out.stdout.splitlines())


def _git_head_commit(cwd: Path) -> str | None:
    """The repo's current HEAD commit id; None outside a repo or on an unborn HEAD."""
    try:
        out = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out or None


def repo_workspace(
    *, ephemeral: bool, cwd: Path, branch: str, worktree: str
) -> EphemeralRepo | None:
    """The ephemeral git exposure for this run, if any.

    Ephemeral mode mounts `.git` so the container creates its own per-session
    worktree on `branch` at `worktree` (a subfolder of /sandbox), forked from
    the current host HEAD. Falls back to the direct /sandbox mount when
    `ephemeral` is off, cwd isn't a git repo, or the repo has no commits yet.
    """
    if not ephemeral or not (cwd / ".git").is_dir():
        return None
    base = _git_head_commit(cwd)
    if base is None:
        return None
    return EphemeralRepo(gitdir=cwd / ".git", branch=branch, base=base, worktree=worktree)


def _ephemeral_env(repo: EphemeralRepo) -> dict[str, str]:
    """The AP_* env vars the image entrypoint reads to set up the worktree."""
    return {
        "AP_BRANCH": repo.branch,
        "AP_BASE": repo.base,
        "AP_REPO_GIT": repo.gitdir_container,
        "AP_WORKTREE": repo.worktree,
    }


def ensure_host_paths(
    agent_name: str,
    config: AgentConfig,
    session: str = "default",
    settings_file: Path | None = None,
) -> Path:
    agent_host_dir = BASE_STATE_DIR / (
        agent_name if session == "default" else f"{agent_name}/{session}"
    )
    agent_host_dir.mkdir(parents=True, exist_ok=True)

    gitconfig = agent_host_dir / ".gitconfig"
    if not gitconfig.exists():
        gitconfig.write_text(_gitconfig_seed())

    for entry in config.writable_state:
        if entry.effective_type == "dir":
            (agent_host_dir / entry.name).mkdir(parents=True, exist_ok=True)
        else:
            _ensure_state_file(agent_host_dir / entry.name, _seed_source(entry, settings_file))

    return agent_host_dir


def _instructions_content(
    skill_container_path: str | None, context_entries: list[FileMount]
) -> str:
    lines = [
        "# Agent instructions",
        "",
        "## Version control",
        "",
        "Follow the `git-workflow` skill for all code change operations — never use `jj`.",
    ]
    if skill_container_path:
        lines.append(
            f"Load it with `read {skill_container_path}` before any code changes; it covers the"
            " commit flow and working conventions."
        )
    else:
        lines.append(
            "Load the `git-workflow` skill before any code changes; it covers the"
            " commit flow and working conventions."
        )
    lines.extend(["", "## Context files", ""])
    for entry in context_entries:
        lines.append(f"@{CONTEXTS_CONTAINER_DIR}/{entry.name}")
    lines.append("")
    return "\n".join(lines)


def _builtin_container_path(config: AgentConfig, builtin: str) -> str | None:
    """The container path of a `builtin:` file entry, if any."""
    for entry in config.files:
        if entry.source == builtin:
            return config.file_container_path(entry)
    return None


def build_mounts(
    *,
    agent_name: str,
    config: AgentConfig,
    cwd: Path,
    agent_host_dir: Path,
    prompts_dir: Path,
    ephemeral_repo: EphemeralRepo | None = None,
) -> list[Mount]:
    """Assemble every host mount and tmpfs the agent will get.

    Shared by the runner (which turns these into podman -v/--tmpfs args) and the
    `ap plan` preview, so the plan always reflects what will actually run. The
    sandbox's `files` are mounted in list order, so a directory entry placed
    before a file entry nested inside it wins for the exact path (e.g. the host
    skills dir before the runner-authoritative git-workflow SKILL.md). Context
    (`context: true`) files are read-only entries also referenced in the
    generated instructions and passed to pi as `@<path>` args.
    """
    mounts: list[Mount] = []
    context_entries = [
        e for e in config.files if e.context and e.source and Path(e.source).expanduser().exists()
    ]

    if ephemeral_repo is not None:
        # The container owns the worktree: mount just .git so it can create its
        # own per-session worktree on it; uncommitted work never leaves the pod.
        mounts.append(
            Mount(
                host_path=ephemeral_repo.gitdir,
                container_path=ephemeral_repo.gitdir_container,
                mode="rw",
                kind="repo",
                description="Your repository (.git)",
            )
        )
    else:
        mounts.append(
            Mount(
                host_path=cwd,
                container_path="/sandbox",
                mode="rw",
                kind="repo",
                description="Your repository",
            )
        )

    for entry in config.files:
        container_path = config.file_container_path(entry)
        if entry.context:
            host = Path(entry.source).expanduser() if entry.source else None
            if host is None or not host.exists():
                if host is not None:
                    _warn_missing(entry, host)
                continue
            mounts.append(
                Mount(
                    host_path=host,
                    container_path=f"{CONTEXTS_CONTAINER_DIR}/{entry.name}",
                    mode="ro",
                    kind="context",
                    description=entry.description,
                )
            )
            continue
        if entry.source == BUILTIN_INSTRUCTIONS:
            prompts_dir.mkdir(parents=True, exist_ok=True)
            host = prompts_dir / f"{agent_name}-instructions.md"
            host.write_text(
                _instructions_content(
                    _builtin_container_path(config, BUILTIN_GIT_WORKFLOW), context_entries
                )
            )
            mounts.append(
                Mount(
                    host_path=host,
                    container_path=container_path,
                    mode="ro",
                    kind="instructions",
                    description=entry.description,
                )
            )
            continue
        if entry.source == BUILTIN_GIT_WORKFLOW:
            prompts_dir.mkdir(parents=True, exist_ok=True)
            host = prompts_dir / "git-workflow.md"
            host.write_text(load_base_prompt())
            mounts.append(
                Mount(
                    host_path=host,
                    container_path=container_path,
                    mode="ro",
                    kind="skill",
                    description=entry.description,
                )
            )
            continue

        host = Path(entry.source).expanduser() if entry.source else None

        if entry.permissions == "ro":
            if host is None or not host.exists():
                if host is not None:
                    _warn_missing(entry, host)
                continue
            mounts.append(
                Mount(
                    host_path=host,
                    container_path=container_path,
                    mode="ro",
                    kind="config",
                    description=entry.description,
                )
            )
            continue

        # Read/write.
        if entry.source is not None and not entry.seed:
            # A writable host path mounted directly (writes flow back to the host).
            rw_host = Path(entry.source).expanduser()
            if not rw_host.exists():
                _warn_missing(entry, rw_host)
                continue
            mounts.append(
                Mount(
                    host_path=rw_host,
                    container_path=container_path,
                    mode="rw",
                    kind="config",
                    description=entry.description,
                    secret=entry.secret,
                )
            )
            continue

        # Writable state: seeded from the host (or empty), mounted from the state dir.
        state_path = agent_host_dir / entry.name
        seed_host = Path(entry.source).expanduser() if entry.seed and entry.source else None
        mounts.append(
            Mount(
                host_path=state_path,
                container_path=container_path,
                mode="rw",
                kind="credential" if entry.secret else "state",
                source=seed_host,
                secret=entry.secret,
                description=entry.description,
            )
        )

    mounts.append(
        Mount(
            host_path=agent_host_dir / ".gitconfig",
            container_path=GITCONFIG_CONTAINER,
            mode="rw",
            kind="gitconfig",
        )
    )

    for container_path, mount_options in config.tmpfs_mounts.items():
        mounts.append(
            Mount(
                host_path=None,
                container_path=f"{container_path}:{mount_options}",
                mode="",
                kind="tmpfs",
                tmpfs=True,
            )
        )

    return _finalize_mounts(mounts)


def _finalize_mounts(mounts: list[Mount]) -> list[Mount]:
    """Resolve same-path and nested-path conflicts before handing to podman.

    - Last mount for a container path wins, kept at its first-appearance
      position, so podman never gets two -v flags for one destination and
      `ap plan` shows the mount that actually takes effect.
    - A nested mount under a directory we own (writable session state) is
      folded into that directory instead of bind-mounting file-under-dir:
      crun cannot create a mount point *inside* a bind-mounted directory whose
      source lacks the nested path (e.g. `…/skills/git-workflow.md` after the
      skills profile replaces `…/skills` with a rw state dir). Folding the
      nested content into the on-disk state dir keeps the agent seeing it — the
      nested (builtin) version wins for the exact path, as before — without the
      conflicting bind.
    """
    unique: dict[str, Mount] = {}
    for mount in mounts:
        unique[mount.container_path] = mount
    ordered = list(unique.values())
    owned_dirs = [m for m in ordered if m.host_path and m.kind in ("state", "credential")]
    result = []
    for mount in ordered:
        parent = _nested_under_owned_dir(mount, owned_dirs)
        if parent is not None and mount.host_path and Path(mount.host_path).exists():
            _fold_mount_into_dir(mount, parent)
            continue
        result.append(mount)
    return result


def _nested_under_owned_dir(mount: Mount, owned_dirs: list[Mount]) -> Mount | None:
    """Return the owned directory mount this mount nests under, if any."""
    if not mount.container_path:
        return None
    for owned in owned_dirs:
        if owned is mount:
            continue
        base = owned.container_path.rstrip("/")
        if base and mount.container_path.startswith(base + "/"):
            return owned
    return None


def _fold_mount_into_dir(mount: Mount, parent: Mount) -> None:
    assert parent.host_path is not None
    assert mount.host_path is not None
    rel = mount.container_path[len(parent.container_path.rstrip("/")) :].lstrip("/")
    dest = Path(parent.host_path) / rel
    src = Path(mount.host_path)
    try:
        if src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    except OSError:
        pass  # plan preview must not crash; a runtime error would surface anyway


def _podman_command(
    *,
    agent_name: str,
    config: AgentConfig,
    instance_name: str,
    session: str,
    use_bash: bool,
    extra_args: list[str],
    env: Mapping[str, str],
    mounts: list[Mount],
    internal_env: Mapping[str, str] | None = None,
) -> list[str]:
    cmd = [
        "podman",
        "run",
        "--rm",
        "-it",
        "--stop-timeout",
        "0",
        "--pull=never",
        "--name",
        instance_name,
        "-w",
        # Podman rejects a workdir that doesn't exist in the container yet, and
        # the ephemeral worktree path is created by the entrypoint only after
        # startup; the entrypoint `cd`s into it itself. /sandbox always exists.
        "/sandbox",
    ]

    if use_bash:
        cmd += ["--entrypoint", "bash"]

    for mount in mounts:
        if mount.tmpfs:
            cmd += ["--tmpfs", mount.container_path]
        else:
            cmd += ["-v", f"{mount.host_path}:{mount.container_path}:{mount.mode},z"]

    for env_key in config.passthrough_envs:
        if env_key in env:
            cmd += ["-e", env_key]

    for env_key, env_value in (internal_env or {}).items():
        cmd += ["-e", f"{env_key}={env_value}"]

    cmd.append(config.image_tag)

    # pi loads `@<file>` args into the message: one per context file mount.
    if agent_name == "pi" and not use_bash:
        at_args = [f"@{m.container_path}" for m in mounts if m.kind == "context"]
        if at_args:
            extra_args = at_args + extra_args

    if not use_bash:
        cmd += extra_args

    return cmd


def run_agent(
    agent_name: str,
    extra_args: list[str],
    use_bash: bool = False,
    session: str = "default",
    profile: str = "default",
    context_files: list[FileMount] | None = None,
    files: list[FileMount] | None = None,
    settings_file: Path | None = None,
    ephemeral: bool = False,
) -> None:
    config = get_effective_agent_config(agent_name)
    # Profile `files` and context files are just additional `files` entries;
    # append them so mounts, instructions, and pi args all derive from one list.
    extra_files = [*(files or []), *(context_files or [])]
    if extra_files:
        config = config.model_copy(update={"files": [*config.files, *extra_files]})

    if not valid_session_name(session):
        print(
            f"Error: invalid session name {session!r}: must be a plain name without "
            "path separators, dot segments, or whitespace.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    instance_name = get_instance_name(config, session)

    if container_running(instance_name):
        print(
            f"Error: a session is already running as container '{instance_name}'. Stop it"
            f" first (e.g. `ap sessions {agent_name} --rm {session}`) before relaunching.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if settings_file is not None and not settings_file.exists():
        logger.warning("settings file not found, falling back to default seed: %s", settings_file)
        settings_file = None

    agent_host_dir = ensure_host_paths(agent_name, config, session, settings_file)

    prompts_dir = BASE_STATE_DIR / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    cleanup_stale_container(instance_name)

    # Leftover agent branches from crashed or legacy sessions accumulate; sweep
    # no-op ones before launching. Live sessions' branches are checked out and
    # can't be deleted, so this never disturbs an active session.
    tidy_noop_branches(Path.cwd())

    build_image(agent_name, config, settings_file)

    # Ephemeral git mode: mount the repo's .git and let the container create its
    # own per-session worktree on agent/<profile>/<session>, forked from the
    # current host HEAD. Commits are the only thing that ever reaches the host.
    # Falls back to the direct /sandbox mount unless enabled in a git repo.
    ephemeral_repo = repo_workspace(
        ephemeral=ephemeral,
        cwd=Path.cwd(),
        branch=f"agent/{profile}/{session}",
        worktree=f"/sandbox/{instance_name}",
    )
    internal_env = _ephemeral_env(ephemeral_repo) if ephemeral_repo is not None else {}

    mounts = build_mounts(
        agent_name=agent_name,
        config=config,
        cwd=Path.cwd(),
        agent_host_dir=agent_host_dir,
        prompts_dir=prompts_dir,
        ephemeral_repo=ephemeral_repo,
    )

    # Launch screen: the same truthful preview `ap plan` renders, built from the
    # exact mounts + envs just handed to podman, so the operator sees what the
    # sandbox can touch before the agent takes over the terminal. Imported here
    # (not at module scope) because plan.py imports from this module.
    from agent_pod.plan import EnvVar, Plan, build_envs, color_enabled, render_plan

    envs = build_envs(config, os.environ)
    if ephemeral_repo is not None:
        envs = [EnvVar(name=key, forwarded=False, internal=True) for key in internal_env] + envs

    plan = Plan(
        agent=agent_name,
        session=session,
        mounts=mounts,
        envs=envs,
        security=SecurityProfile(),
    )
    print(render_plan(plan, color=color_enabled()))

    command = _podman_command(
        agent_name=agent_name,
        config=config,
        instance_name=instance_name,
        session=session,
        use_bash=use_bash,
        extra_args=extra_args,
        env=os.environ,
        mounts=mounts,
        internal_env=internal_env or None,
    )

    try:
        _run_podman(command, instance_name)
    except FileNotFoundError:
        print("Error: 'podman' executable was not found on your PATH.", file=sys.stderr)
        sys.exit(1)
    except Exception as execution_error:
        print(f"Error: Failed to execute podman command: {execution_error}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Drop this session's worktree registration from the repo's .git. Its
        # gitdir points at the container-only /sandbox/<instance> path, so
        # targeted `remove --force` on that one path leaves any other live
        # session's worktree alone. A branch that adds nothing to main is then
        # pruned; unique work stays for review.
        if ephemeral_repo is not None:
            repo = Path.cwd()
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "worktree",
                    "remove",
                    "--force",
                    ephemeral_repo.worktree,
                ],
                capture_output=True,
                text=True,
            )
            prune_matching_branch(repo, ephemeral_repo.branch)


def _run_podman(command: list[str], instance_name: str) -> None:
    """Run podman, force-removing the container if the terminal is torn down.

    `podman run --rm -it` removes the container only when it exits on its own.
    When the terminal goes away — e.g. a zellij pane running the agent is closed
    — a TUI agent such as opencode can leave a background server process behind,
    which keeps the container alive and consuming memory; `--rm` never fires.
    Trapping SIGHUP here lets agent-pod force-stop and remove the container in
    that case instead of relying on podman to notice the terminal is gone.
    """
    logger.debug("podman: %s", " ".join(command))
    proc = subprocess.Popen(command)

    def _force_remove(signum: int, frame) -> None:
        subprocess.run(
            ["podman", "stop", "-t", "0", "--ignore", instance_name],
            capture_output=True,
            text=True,
            timeout=15,
        )
        subprocess.run(
            ["podman", "rm", "-f", "--ignore", instance_name],
            capture_output=True,
            text=True,
            timeout=15,
        )
        sys.exit(128 + signum)

    signal.signal(signal.SIGHUP, _force_remove)
    try:
        proc.wait()
    finally:
        signal.signal(signal.SIGHUP, signal.SIG_DFL)
    raise SystemExit(proc.returncode or 0)
