"""Command-line interface for agent-pod."""

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from agent_pod.config import (
    get_all_agent_names,
    get_effective_agent_config,
    get_user_config,
)
from agent_pod.container import run_agent
from agent_pod.log import configure_logging
from agent_pod.types import (
    DEFAULT_PROFILE,
    STATE_DIR,
    AgentConfig,
    FileMount,
    ProfileConfig,
    UserConfig,
)
from agent_pod.utils.names import get_instance_name, humanized_id, valid_session_name

logger = logging.getLogger(__name__)


def _split_double_dash(argv: list[str]) -> tuple[list[str], list[str] | None]:
    """Split at the first bare `--`; returns (before, after) or None if absent."""
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1 :]
    return argv, None


class _CliParser(argparse.ArgumentParser):
    """Treat a bare `--` as a hard separator for extra agent args.

    argparse otherwise feeds the tokens after `--` into the optional `profile`
    positional when none was given (`ap run --agent pi -- --flag` → profile
    "--flag"). Split before parsing and re-attach the tail as `extra_args`.
    """

    def parse_args(self, args=None, namespace=None):
        argv, tail = _split_double_dash(list(sys.argv[1:]) if args is None else args)
        ns = super().parse_args(argv, namespace)
        if tail is not None and hasattr(ns, "extra_args"):
            ns.extra_args = tail
        return ns


# Shared ``-v/--verbose`` flag, inherited by the top-level parser and every
# subparser so it works in any position (``ap -v run`` or ``ap run -v``).
_VERBOSE = _CliParser(add_help=False)
_VERBOSE.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    help="Verbose output: DEBUG logs (subprocess commands, error tracebacks) to stderr.",
)


def _state_dir() -> Path:
    return Path.home() / STATE_DIR


def _valid_context_name(name: str) -> bool:
    """Whether `name` is safe as a context-file name: no separators/dot-segments/
    whitespace (they could escape the contexts dir or break the podman mount / @-reference).
    """
    if not name or name in {".", ".."}:
        return False
    return "/" not in name and "\\" not in name and not any(c.isspace() for c in name)


def _parse_context_files(context_file_args: list[str]) -> list[FileMount]:
    """Parse --context-file arguments into context FileMount entries.

    Each argument is HOST_PATH or HOST_PATH:NAME and becomes a `context: true`
    FileMount — the generic form of a context file (see types.FileMount.context).

    Raises:
        SystemExit: If a supplied name contains path separators, dot segments, or whitespace.
    """
    context_files = []
    for cf in context_file_args:
        if ":" in cf:
            host_path_str, name = cf.rsplit(":", 1)
        else:
            host_path_str = cf
            name = Path(cf).name
        if not _valid_context_name(name):
            print(
                f"Error: invalid --context-file name {name!r}: must be a plain file "
                "name without path separators, dot segments, or whitespace.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        context_files.append(
            FileMount(
                source=str(Path(host_path_str).expanduser().resolve()),
                name=name,
                permissions="ro",
                context=True,
            )
        )
    return context_files


def _default_settings_path() -> str:
    return str(Path.home() / ".pi" / "settings.json")


def _resolve_agent(cli_agent: str | None, cfg: ProfileConfig, subcommand: str) -> str:
    """Return the agent for a subcommand: CLI arg wins, else the config default."""
    agent = cli_agent or cfg.agent
    if agent is None:
        print(
            f"Error: no agent given for '{subcommand}'. "
            "Pass one or set 'agent' in your user config.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if agent not in get_all_agent_names():
        print(
            f"Error: unknown agent '{agent}' for '{subcommand}'. "
            f"Available: {', '.join(get_all_agent_names())}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return agent


def _effective_user_config(
    user_cfg: UserConfig, cli_profile: str | None
) -> tuple[str, ProfileConfig]:
    """Resolve the active profile to its complete config.

    Returns (profile_name, effective_config). The profile is the positional
    `cli_profile`, else the config `profile`, else "default". The effective
    config is the top-level defaults applied to all configs, overlaid with the
    selected profile's per-key overrides (`files` appends after the top level) —
    see UserConfig.effective. It resolves into the concrete AgentConfig used by
    the runner, so any config option settable at the top level is settable per
    profile.
    """
    profile = cli_profile or user_cfg.profile or DEFAULT_PROFILE
    if profile != "default" and profile not in user_cfg.profiles:
        defined = ", ".join(sorted(user_cfg.profiles)) or "(none)"
        print(f"Error: unknown profile {profile!r}. Defined: {defined}", file=sys.stderr)
        raise SystemExit(2)
    if not valid_session_name(profile):
        print(
            f"Error: invalid profile name {profile!r}: must be a plain name without "
            "path separators, dot segments, or whitespace.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return profile, user_cfg.effective(profile)


def _used_session_ids(agent_dir: Path) -> set[str]:
    """Session names already taken (state dirs), so fresh auto sessions don't collide."""
    if not agent_dir.is_dir():
        return set()
    return {d.name for d in agent_dir.iterdir() if d.is_dir()}


def _run(args: argparse.Namespace, use_bash: bool, label: str) -> None:
    # First-time setup: if no user config exists on any level, walk the user
    # through generating one before launching the sandbox.
    from agent_pod.config.init import ensure_user_config

    ensure_user_config(agent_hint=args.agent)
    user_cfg = get_user_config()
    profile, eff = _effective_user_config(user_cfg, args.profile)
    agent = _resolve_agent(args.agent, eff, label)
    # CLI flags win over the config; unset flags fall back to the effective
    # (profile-resolved) config values, then to CLI defaults. Config extra_args
    # don't apply when dropping to a bash shell (the runner ignores them anyway).
    extra_args = [a for a in args.extra_args if a != "--"]
    if not extra_args and not use_bash:
        extra_args = eff.extra_args or []
    context_file_args = (
        args.context_file if args.context_file is not None else (eff.context_files or [])
    )
    context_files = _parse_context_files(context_file_args)
    # The settings-file bake is pi-specific; other agents never read it, so only
    # resolve it (and warn about a missing file) for the pi agent.
    settings_file = (
        args.settings_file or eff.settings_file or _default_settings_path()
        if agent == "pi"
        else None
    )

    # Explicit --session/config session: persistent session name + isolated state.
    # Auto sessions get a fresh humanized id so each run gets its own branch/
    # worktree instead of reusing the profile's; dedupe against session state dirs.
    explicit_session = args.session or eff.session
    session = explicit_session or humanized_id(_used_session_ids(_state_dir() / agent))

    run_agent(
        agent,
        extra_args,
        use_bash=use_bash,
        session=session,
        profile=profile,
        context_files=context_files,
        settings_file=Path(settings_file).expanduser().resolve() if settings_file else None,
        user_cfg=eff,
    )


def cmd_run(args: argparse.Namespace) -> None:
    _run(args, use_bash=False, label="run")


def cmd_shell(args: argparse.Namespace) -> None:
    """`ap shell` — like `run`, but with an interactive bash entrypoint."""
    _run(args, use_bash=True, label="shell")


def cmd_init(args: argparse.Namespace) -> None:
    """Execute the 'init' subcommand: interactively generate a user config."""
    from agent_pod.config.init import run_init

    path = run_init(target=args.target, force=args.force)
    if path is None:
        return
    print(f"Created config at {path}")
    print("Run `ap run` to launch an agent with this config.")


def cmd_build(args: argparse.Namespace) -> None:
    from agent_pod.container import build_image

    user_cfg = get_user_config()
    agent = _resolve_agent(args.agent, user_cfg, "build")
    config = get_effective_agent_config(agent)
    settings_file = (
        args.settings_file or user_cfg.settings_file or _default_settings_path()
        if agent == "pi"
        else None
    )
    build_image(
        agent,
        config,
        Path(settings_file).expanduser().resolve() if settings_file else None,
    )


def cmd_list(args: argparse.Namespace) -> None:
    """List configured profiles by default; `--agents` lists agents instead."""
    if args.agents:
        _list_agents()
    else:
        _list_profiles()


def _list_agents() -> None:
    print("Configured Agents:")
    for name in get_all_agent_names():
        config = get_effective_agent_config(name)
        print(f"  - {name:<10} Image: {config.image_tag}")


def _list_profiles() -> None:
    """List configured profiles: the `default` profile plus any named ones.

    The `default` profile always exists (its settings are the config's baseline
    run options); named profiles are run-level overrides on top of it. The
    active profile — the config's `profile:` key, else `default` — is marked.
    `ap list --agents` lists the supported agents instead.
    """
    user_cfg = get_user_config()
    active = user_cfg.profile or DEFAULT_PROFILE
    print("Configured Profiles:")
    marker = " (active)" if active == DEFAULT_PROFILE else ""
    print(f"  - {DEFAULT_PROFILE}{marker}{_default_profile_summary(user_cfg)}")
    for name in sorted(p for p in user_cfg.profiles if p != DEFAULT_PROFILE):
        marker = " (active)" if name == active else ""
        print(f"  - {name}{marker}{_profile_summary(user_cfg.profiles[name])}")


def _default_profile_summary(user_cfg: UserConfig) -> str:
    """Compact summary of the `default` profile's effective run settings.

    The config's top-level run keys are the baseline applied to all configs; a
    `profiles: {default: …}` block (if any) overlays them per key — exactly what
    `_effective_user_config` resolves for the active profile.
    """
    return _profile_summary(user_cfg.effective("default"))


def _profile_summary(profile: ProfileConfig) -> str:
    """Compact human summary of a profile's run-level overrides."""
    parts = []
    if profile.agent:
        parts.append(f"agent={profile.agent}")
    if profile.context_files:
        parts.append(f"{len(profile.context_files)} context file(s)")
    if profile.files:
        parts.append(f"{len(profile.files)} file mount(s)")
    if profile.extra_args:
        parts.append(f"flags: {' '.join(profile.extra_args)}")
    if profile.settings_file:
        parts.append(f"settings_file={profile.settings_file}")
    return f"  [{', '.join(parts)}]" if parts else ""


def _default_session_detected(agent_dir: Path, config: AgentConfig) -> bool:
    return (
        any((agent_dir / entry.name).exists() for entry in config.writable_state)
        or (agent_dir / ".gitconfig").exists()
    )


def _named_sessions(agent_dir: Path) -> list[str]:
    return [d.name for d in agent_dir.iterdir() if d.is_dir()]


def _detect_sessions(agent_dir: Path, config: AgentConfig) -> list[str]:
    sessions = set(_named_sessions(agent_dir))
    if _default_session_detected(agent_dir, config):
        sessions.add("default")
    return sorted(sessions)


def _session_status(instance_name: str, ps_output: str) -> str:
    for line in ps_output.splitlines():
        parts = line.split("\t", 1)
        if parts[0] == instance_name:
            return parts[1] if len(parts) > 1 else "stopped"
    return "stopped"


def _remove_session(agent: str, session: str, config: AgentConfig) -> None:
    if not valid_session_name(session):
        print(
            f"Error: invalid session name {session!r}: must be a plain name without "
            "path separators, dot segments, or whitespace.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    subprocess.run(["podman", "rm", "-f", get_instance_name(config, session)], capture_output=True)
    # The session's own git history is in the host repo's .git (the container's
    # worktree metadata is pruned when the container exits); nothing repo-side
    # to clean here beyond state.
    state_dir = _state_dir() / agent
    if session == "default":
        if state_dir.exists():
            for entry in config.writable_state:
                path = state_dir / entry.name
                if path.exists():
                    if entry.effective_type == "dir":
                        shutil.rmtree(path)
                    else:
                        path.unlink()
            gitconfig = state_dir / ".gitconfig"
            if gitconfig.exists():
                gitconfig.unlink()
    else:
        session_dir = state_dir / session
        if session_dir.exists():
            shutil.rmtree(session_dir)
    print(f"Removed session '{session}' for agent '{agent}'.")


def cmd_plan(args: argparse.Namespace) -> None:
    from agent_pod.plan import build_plan, color_enabled, render_plan

    user_cfg = get_user_config()
    profile, eff = _effective_user_config(user_cfg, args.profile)
    agent = _resolve_agent(args.agent, eff, "plan")
    context_file_args = (
        args.context_file if args.context_file is not None else (eff.context_files or [])
    )
    context_files = _parse_context_files(context_file_args)
    plan = build_plan(
        agent=agent,
        session=args.session or eff.session or profile,
        context_files=context_files,
        user_cfg=eff,
        profile=profile,
    )
    print(render_plan(plan, color=color_enabled()))


def cmd_context(args: argparse.Namespace) -> None:
    """Print the generated agent instructions (AGENTS.md) a profile gives the agent.

    Reuses the plan build so it resolves the profile exactly as `ap plan` does,
    then prints the instructions file `build_mounts` wrote — the same text the
    container mounts at /root/.pi/agent/AGENTS.md, with live forwarded/not-set
    env status from the current shell.
    """
    from agent_pod.container.runner import BASE_STATE_DIR
    from agent_pod.plan import build_plan

    user_cfg = get_user_config()
    profile, eff = _effective_user_config(user_cfg, args.profile)
    agent = _resolve_agent(args.agent, eff, "context")
    context_file_args = (
        args.context_file if args.context_file is not None else (eff.context_files or [])
    )
    context_files = _parse_context_files(context_file_args)
    build_plan(
        agent=agent,
        session=args.session or eff.session or profile,
        context_files=context_files,
        user_cfg=eff,
        profile=profile,
    )
    path = BASE_STATE_DIR / "prompts" / f"{agent}-instructions.md"
    sys.stdout.write(path.read_text())


def cmd_sessions(args: argparse.Namespace) -> None:
    user_cfg = get_user_config()
    agent = _resolve_agent(args.agent, user_cfg, "sessions")
    config = get_effective_agent_config(agent)
    if args.rm:
        _remove_session(agent, args.rm, config)
        return

    agent_dir = _state_dir() / agent
    if not agent_dir.exists():
        print(f"No sessions found for agent '{agent}'.")
        sys.exit(0)

    sessions = _detect_sessions(agent_dir, config)
    if not sessions:
        print(f"No sessions found for agent '{agent}'.")
        sys.exit(0)

    print(f"Sessions for '{agent}':")
    for session in sessions:
        instance_name = get_instance_name(config, session)
        result = subprocess.run(
            ["podman", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
        )
        status = _session_status(instance_name, result.stdout)
        print(f"  - {session:<20} {status}")


def _fatal_message(error: Exception) -> str:
    """A single-line, size-capped rendering of an uncaught error for the CLI."""
    message = " ".join(str(error).split())
    return message[:400] or type(error).__name__


def main() -> None:
    parser = _CliParser(
        prog="ap",
        parents=[_VERBOSE],
        description="Fast, isolated container sandboxes for AI coding agents using Podman CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Options shared by `run` and `shell` (the two ways to launch a sandbox): the
    # profile is always the positional, the harness comes from the profile's `agent`,
    # else the config default, with `--agent` to override explicitly.
    _RUN_OPTIONS = _CliParser(add_help=False)
    _RUN_OPTIONS.add_argument(
        "--agent",
        choices=get_all_agent_names(),
        default=None,
        help=(
            "Harness agent to launch (defaults to the profile's `agent`, "
            "else the config's `agent`)."
        ),
    )
    _RUN_OPTIONS.add_argument(
        "--session",
        default=None,
        help=(
            "Session name for isolated state and parallel runs. Explicit sessions "
            "map to a stable `agent/<profile>/<session>` branch (resume re-checks "
            "it out); otherwise each run gets a fresh humanized session name "
            "(e.g. crisp-lamp) and its own branch."
        ),
    )
    _RUN_OPTIONS.add_argument(
        "--context-file",
        action="append",
        dest="context_file",
        default=None,
        help=(
            "Mount a context file into the agent (format: HOST_PATH[:NAME]). "
            "Can be specified multiple times."
        ),
    )
    _RUN_OPTIONS.add_argument(
        "--settings-file",
        metavar="HOST_PATH",
        default=None,
        help=(
            "Path to the pi settings.json to bake into the image (defaults to "
            "~/.pi/settings.json); its 'packages' are installed at build time. At "
            "runtime the host's ~/.pi/settings.json is mounted read-only when "
            "present, so the baked copy only applies when it's absent."
        ),
    )

    run_parser = subparsers.add_parser(
        "run", parents=[_VERBOSE, _RUN_OPTIONS], help="Run a sandboxed AI agent under a profile"
    )
    run_parser.add_argument(
        "profile",
        nargs="?",
        default=None,
        help=(
            "Named profile to run (branch namespace agent/<profile>/<name> + run "
            "overrides). The harness agent comes from the profile's `agent`, else "
            "the config's `agent`; --agent overrides it."
        ),
    )
    run_parser.add_argument(
        "extra_args",
        nargs="*",
        default=[],
        help="Additional arguments to pass to the agent.",
    )

    shell_parser = subparsers.add_parser(
        "shell",
        parents=[_VERBOSE, _RUN_OPTIONS],
        help="Drop into an interactive bash shell inside the sandbox",
    )
    shell_parser.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="Named profile to shell into (same selection rules as `run`).",
    )
    shell_parser.add_argument(
        "extra_args",
        nargs="*",
        default=[],
        help="Additional arguments to pass to the agent (ignored in bash mode).",
    )

    build_parser = subparsers.add_parser(
        "build", parents=[_VERBOSE], help="Build container image for a specific agent"
    )
    build_parser.add_argument(
        "agent",
        nargs="?",
        choices=get_all_agent_names(),
        default=None,
        help="The agent image to build (defaults to the 'agent' in your user config).",
    )
    build_parser.add_argument(
        "--settings-file",
        metavar="HOST_PATH",
        default=None,
        help=(
            "Path to a pi settings.json to bake into the image at build time, so pi "
            "loads its extensions/packages offline instead of at runtime (defaults to "
            "the pi global settings at ~/.pi/settings.json). Each package in the file's "
            "'packages' list is installed via `pi install` during the build."
        ),
    )

    list_parser = subparsers.add_parser(
        "list",
        parents=[_VERBOSE],
        help="List configured profiles (or supported agents with --agents)",
    )
    list_parser.add_argument(
        "--agents",
        action="store_true",
        help="List the supported agents and their target image tags instead.",
    )

    init_parser = subparsers.add_parser(
        "init",
        parents=[_VERBOSE],
        help="Interactively generate an agent-pod user config file",
    )
    init_parser.add_argument(
        "--target",
        choices=["project", "global"],
        default=None,
        help=(
            "Write to the project (.agent-pod.yaml) or global "
            "(~/.config/container-agents/.agent-pod.yaml) config without asking "
            "(default: ask)."
        ),
    )
    init_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite an existing config file instead of refusing.",
    )

    sessions_parser = subparsers.add_parser(
        "sessions", parents=[_VERBOSE], help="List or manage agent sessions"
    )
    sessions_parser.add_argument(
        "agent",
        nargs="?",
        choices=get_all_agent_names(),
        default=None,
        help="The agent whose sessions to manage (defaults to the 'agent' in your user config).",
    )
    sessions_parser.add_argument(
        "--rm",
        metavar="SESSION",
        help="Remove a specific session: its container and session state dir.",
    )

    plan_parser = subparsers.add_parser(
        "plan",
        parents=[_VERBOSE],
        help="Show what files, secrets, and env vars the agent will be granted",
    )
    plan_parser.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="Named profile to preview (branch namespace + run overrides).",
    )
    plan_parser.add_argument(
        "--agent",
        choices=get_all_agent_names(),
        default=None,
        help=(
            "Harness agent to preview (defaults to the profile's `agent`, "
            "else the config's `agent`)."
        ),
    )
    plan_parser.add_argument(
        "--session",
        default=None,
        help="Session name to preview (defaults to the profile name, or 'default' without one)",
    )
    plan_parser.add_argument(
        "--context-file",
        action="append",
        dest="context_file",
        default=None,
        help=(
            "Mount a context file into the agent (format: HOST_PATH[:NAME]). "
            "Can be specified multiple times."
        ),
    )

    context_parser = subparsers.add_parser(
        "context",
        parents=[_VERBOSE],
        help="Print the generated agent instructions (AGENTS.md) a profile gives the agent",
    )
    context_parser.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="Named profile to render (branch namespace + run overrides).",
    )
    context_parser.add_argument(
        "--agent",
        choices=get_all_agent_names(),
        default=None,
        help=(
            "Harness agent to render (defaults to the profile's `agent`, "
            "else the config's `agent`)."
        ),
    )
    context_parser.add_argument(
        "--session",
        default=None,
        help="Session name to render (defaults to the profile name, or 'default' without one)",
    )
    context_parser.add_argument(
        "--context-file",
        action="append",
        dest="context_file",
        default=None,
        help=(
            "Mount a context file into the agent (format: HOST_PATH[:NAME]). "
            "Can be specified multiple times."
        ),
    )

    args = parser.parse_args()
    configure_logging(args.verbose)

    def _dispatch() -> None:
        if args.subcommand == "run":
            cmd_run(args)
        elif args.subcommand == "shell":
            cmd_shell(args)
        elif args.subcommand == "build":
            cmd_build(args)
        elif args.subcommand == "list":
            cmd_list(args)
        elif args.subcommand == "init":
            cmd_init(args)
        elif args.subcommand == "plan":
            cmd_plan(args)
        elif args.subcommand == "context":
            cmd_context(args)
        elif args.subcommand == "sessions":
            cmd_sessions(args)
        else:
            parser.print_help()

    try:
        _dispatch()
    except SystemExit:
        raise  # usage errors, session exits, and the agent's own exit code pass through
    except KeyboardInterrupt:
        raise
    except Exception as error:
        # One clean line, not a raw traceback; the full traceback is logged under -v.
        logger.debug("Unhandled error", exc_info=True)
        print(f"Error: {_fatal_message(error)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
