"""Container image building utilities."""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_pod.types import AgentConfig, FlakeConfig
from agent_pod.utils.paths import agent_pod_root

logger = logging.getLogger(__name__)

# Nix runs inside this builder image; the host needs no Nix (macOS/container userbase).
NIXOS_IMAGE = "docker.io/nixos/nix:2.24.9"

# Persistent named volume shared by all agents: native-runtime I/O stays fast
# (not a host-sharing bind mount), rebuilds fetch only the delta, and the
# nixos/nix image's own /nix is copied in on first use so `nix` stays runnable.
NIX_STORE_VOLUME = "agent-pod-nix"

# Where the content hash of the last successful build is recorded per image tag.
# A matching hash + an existing image lets `run`/`build` skip the rebuild.
CACHE_DIR = Path.home() / ".cache" / "container-agents" / "build-hashes"

# Bundled build templates (bash / nix / dockerfile) live in templates/ as real
# files so they can be reviewed, shellchecked, and linted on their own.
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _tpl(name: str) -> str:
    return (_TEMPLATES_DIR / name).read_text()


def _flake_dir_path(flake_dir: str) -> Path:
    """Resolve a flake dir to an absolute path.

    Absolute paths (e.g. a user's own flake) are used as-is; relative paths are
    anchored at the agent_pod package root (where the bundled configs live).
    """
    p = Path(flake_dir)
    return p if p.is_absolute() else agent_pod_root() / p


def _build_input_hash(dockerfile: str, settings_json: str | None, flake_dir: Path | None) -> str:
    """Hash everything that changes the built image: Dockerfile, settings, flake inputs."""
    h = hashlib.sha256()
    h.update(dockerfile.encode())
    if settings_json is not None:
        h.update(b"\x00settings\x00")
        h.update(settings_json.encode())
    if flake_dir:
        for name in ("flake.nix", "flake.lock", "extra-packages.nix", "flake-config.nix"):
            p = Path(flake_dir) / name
            if p.exists():
                h.update(b"\x00")
                h.update(p.read_bytes())
    return h.hexdigest()


def _image_exists(tag: str) -> bool:
    try:
        result = subprocess.run(["podman", "image", "exists", tag], capture_output=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _packages_from_settings(settings_json: str) -> list[str]:
    """Extract install sources from a pi settings.json 'packages' list.

    Each entry is either a string (e.g. "npm:@foo/bar") or a filter object with a
    'source' key.
    """
    data = json.loads(settings_json)
    sources = []
    for entry in data.get("packages", []) or []:
        if isinstance(entry, str):
            sources.append(entry)
        elif isinstance(entry, dict) and entry.get("source"):
            sources.append(entry["source"])
    return sources


def _runtime_tail(agent_cmd: str) -> str:
    """Runner-owned runtime Docker layer: git identity + the worktree entrypoint.

    `agent_cmd` is the container path of the agent CLI, exec'd by the entrypoint
    after it creates/checks out the per-session git worktree in ephemeral runs
    (`ap shell` overrides ENTRYPOINT with bash). git/bash/coreutils come from
    the flake's nix closure.
    """
    return _tpl("runtime-tail.dockerfile").replace("@AGENT_CMD@", agent_cmd).rstrip("\n")


def _flake_image_base(agent_name: str) -> str:
    """Local tag the flake image is retagged to after `podman load`."""
    return f"agent-pod/{agent_name}:spike"


def _write_extra_packages(flake_dir: Path, extra_packages: list[str]) -> Path:
    """Write the generated `extra-packages.nix` the flake imports into its image.

    The flake's `image.contents` is `[ pkgs.bash pkgs.git <agent> ] ++
    (import ./extra-packages.nix { inherit pkgs; })`, so the set of extra tools
    is declared in config but materialized in the flake — the flake, not a
    generated Dockerfile, is the source of truth for the environment.
    """
    path = flake_dir / "extra-packages.nix"
    entries = "\n".join(f"  pkgs.{p}" for p in extra_packages)
    path.write_text(_tpl("extra-packages.nix").replace("@PACKAGES@", entries))
    return path


def _write_flake_config(flake_dir: Path, allow_unfree: bool, permitted_insecure: list[str]) -> Path:
    """Write the generated `flake-config.nix` the flake applies as nixpkgs config.

    Only non-default keys are emitted. This keeps the generated config purely
    additive so a flake's own required settings (e.g. claude's `allowUnfree`
    for the unfree claude-code binary) are never overridden by defaults.
    """
    path = flake_dir / "flake-config.nix"
    lines = []
    if allow_unfree:
        lines.append("  allowUnfree = true;")
    if permitted_insecure:
        quoted = ", ".join(f'"{p}"' for p in permitted_insecure)
        lines.append(f"  permittedInsecurePackages = [ {quoted} ];")
    options = "".join(line + "\n" for line in lines)
    path.write_text(_tpl("flake-config.nix").replace("@OPTIONS@", options))
    return path


def _nix_string(s: str) -> str:
    """Quote a string as a nix double-quoted string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_extra_packages_check(flake_dir: Path, extra_packages: list[str]) -> Path:
    """Write the pre-flight `check-extra-packages.nix`: classifies each extra_packages
    name against the flake's locked nixpkgs (unknown / insecure / unfree / ok) so a
    bad attr fails fast with an actionable message, not a cryptic nix build error.
    """
    path = flake_dir / "check-extra-packages.nix"
    names = " ".join(_nix_string(n) for n in extra_packages)
    path.write_text(_tpl("check-extra-packages.nix").replace("@NAMES@", names))
    return path


def _extra_packages_check_script() -> str:
    """The shell pre-flight eval of check-extra-packages.nix; runs nix-in-docker."""
    return _tpl("check-extra-packages.sh")


_EXTRA_PACKAGE_ERRORS = {
    "unknown": (
        "is not in this flake's locked nixpkgs. `extra_packages` takes nixpkgs "
        "attribute names (e.g. `uv`, `nodejs_22`, `python311`); find the right "
        "name with `nix search nixpkgs <tool>` or https://search.nixos.org/packages."
    ),
    "unfree": (
        "has an unfree license. Opt in explicitly with `allow_unfree: true` in the flake config."
    ),
    "insecure": (
        "has a known vulnerability. Allow its exact version via `permitted_insecure` "
        "in the flake config (default-deny: insecure software in an agent sandbox "
        "is a deliberate opt-in)."
    ),
}


def _friendly_extra_package_error(name: str, status: str) -> str:
    hint = _EXTRA_PACKAGE_ERRORS.get(status, "failed the extra_packages pre-flight check")
    return f"Error: extra_packages entry `{name}` {hint}"


def _check_extra_packages(context_dir: Path, extra_packages: list[str]) -> None:
    """Pre-flight validate `extra_packages` attr names against the locked nixpkgs.

    Fails fast with an actionable message instead of a cryptic nix build error.
    No-op when empty.

    Raises:
        SystemExit: If podman is missing, the eval fails, or any entry is not ok.
    """
    if not extra_packages:
        return
    with tempfile.TemporaryDirectory(prefix="agent-pod-nix-check-") as out:
        outdir = Path(out)
        command = [
            "podman",
            "run",
            "--rm",
            "-v",
            f"{NIX_STORE_VOLUME}:/nix",
            "-v",
            f"{context_dir}:/src:ro",
            "-v",
            f"{outdir}:/out",
            NIXOS_IMAGE,
            "/bin/sh",
            "-c",
            _extra_packages_check_script(),
        ]
        _run_podman(command, "pre-flight check of extra_packages")
        try:
            entries = json.loads((outdir / "extra-packages-check.json").read_text())
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(
                f"Error: could not parse the extra_packages pre-flight result: {e}",
                file=sys.stderr,
            )
            sys.exit(1)
    bad = [entry for entry in entries if entry.get("status") != "ok"]
    if bad:
        for entry in bad:
            print(
                _friendly_extra_package_error(entry.get("name", "?"), entry.get("status", "?")),
                file=sys.stderr,
            )
        sys.exit(1)


def _stage_flake_context(
    flake_dir: Path,
    extra_packages: list[str],
    allow_unfree: bool = False,
    permitted_insecure: list[str] | None = None,
) -> Path:
    """Stage a writable temp copy of the flake + generated files next to flake.nix
    (bundled flakes may live in a read-only installed wheel). Caller cleans up.
    """
    ctx = Path(tempfile.mkdtemp(prefix="agent-pod-flake-"))
    shutil.copy2(flake_dir / "flake.nix", ctx / "flake.nix")
    lock = flake_dir / "flake.lock"
    if lock.exists():
        shutil.copy2(lock, ctx / "flake.lock")
    _write_extra_packages(ctx, extra_packages)
    _write_flake_config(ctx, allow_unfree, permitted_insecure or [])
    _write_extra_packages_check(ctx, extra_packages)
    return ctx


def _nix_build_script() -> str:
    """Shell script run in the nixos/nix container to build the flake's `image` output.

    The out-link lands in /nix/store (not visible on the host), so the tarball
    is copied to the /out bind mount, handling both dockerTools layouts (dir
    with image.tar.gz, or single-file tarball). /src is read-only, so flake.lock
    is never rewritten here.
    """
    return _tpl("nix-build.sh")


def _run_podman(command: list[str], label: str) -> None:
    """Run a podman subprocess, exiting with a clean error on failure."""
    logger.debug("podman: %s", " ".join(command))
    try:
        result = subprocess.run(command, capture_output=False)
    except FileNotFoundError:
        print(
            "Error: 'podman' was not found on PATH. Install Podman to build sandbox images.",
            file=sys.stderr,
        )
        sys.exit(1)
    if result.returncode != 0:
        print(f"Error: {label} failed.", file=sys.stderr)
        sys.exit(1)


def _build_flake_image(context_dir: Path, agent_name: str) -> None:
    """Build the flake's `image` output nix-in-docker and load it into podman.

    No host Nix: nix runs inside the `nixos/nix` builder container. The nix
    store lives in a persistent named volume (`NIX_STORE_VOLUME`) shared by all
    agents, so a rebuild after a flake change fetches only the delta and the
    store stays in the runtime's native filesystem (fast named-volume I/O, not a
    host-sharing bind mount). The loaded image is retagged to
    `agent-pod/<agent>:spike` so the runner's thin layer can build FROM it.
    """
    with tempfile.TemporaryDirectory(prefix="agent-pod-nix-out-") as out:
        outdir = Path(out)
        command = [
            "podman",
            "run",
            "--rm",
            "-v",
            f"{NIX_STORE_VOLUME}:/nix",
            "-v",
            f"{context_dir}:/src:ro",
            "-v",
            f"{outdir}:/out",
            NIXOS_IMAGE,
            "/bin/sh",
            "-c",
            _nix_build_script(),
        ]
        _run_podman(command, "nix build of the flake image")
        tarball = outdir / "image.tar.gz"
        result = subprocess.run(
            ["podman", "load", "-i", str(tarball)], capture_output=True, text=True
        )
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            print("Error: podman load of the flake image failed.", file=sys.stderr)
            sys.exit(1)
        # Normalize the loaded image to the reference the thin layer builds FROM,
        # whatever name the flake used for its dockerTools image. If the load
        # output couldn't be parsed, assume the flake already used the canonical
        # name (the bundled flakes do) rather than retagging an empty reference.
        base = _flake_image_base(agent_name)
        loaded = _loaded_image_ref(result.stdout)
        if loaded and loaded != base:
            _run_podman(["podman", "tag", loaded, base], "retagging the loaded flake image")


def _loaded_image_ref(load_output: str) -> str:
    """Extract the first loaded image reference from `podman load` output."""
    m = re.search(r"Loaded image(?:\(s\))?: (.+)", load_output)
    if not m:
        return ""
    return m.group(1).split(",")[0].strip()


def generate_runtime_dockerfile(agent_name: str, settings_json: str | None = None) -> str:
    """Generate the thin runner Dockerfile on the flake image: git identity + the
    per-session worktree entrypoint, and (pi) the baked settings.json + installs.
    The flake, not this file, is the source of truth for what is installed.

    Args:
        agent_name: Agent name; the agent CLI is expected at `/usr/local/bin/<agent>`.
        settings_json: Optional pi settings.json text to bake + install at build time.
    """
    agent_cmd = f"/usr/local/bin/{agent_name}"
    lines = [f"FROM {_flake_image_base(agent_name)}"]
    if settings_json is not None:
        lines += [
            "RUN mkdir -p /root/.pi/agent && \\",
            "    cat > /root/.pi/agent/settings.json <<'PI_JSON'",
            settings_json.rstrip("\n"),
            "PI_JSON",
        ]
        packages = _packages_from_settings(settings_json)
        if packages:
            installs = " && ".join(f"{agent_cmd} install {p} --approve" for p in packages)
            lines.append("RUN GIT_TERMINAL_PROMPT=0 PI_SKIP_VERSION_CHECK=1 \\\n    " + installs)
    lines.append(_runtime_tail(agent_cmd))
    return "\n".join(lines)


def _check_flake_dir(flake_cfg: FlakeConfig) -> Path:
    context_dir = _flake_dir_path(flake_cfg.dir)
    for required in ("flake.nix", "flake.lock"):
        if not (context_dir / required).exists():
            print(f"Error: no '{required}' in flake dir '{context_dir}'.", file=sys.stderr)
            sys.exit(1)
    return context_dir


def _load_settings(settings_file: Path | None) -> str | None:
    """Read + canonicalize a pi settings.json for baking into the image.

    Canonicalizing (sorted keys, 2-space indent) keeps semantically-equal settings
    byte-identical, keeping the buildah layer cache key stable across formatting
    churn. Returns None when no file is supplied/exists.
    """
    if settings_file is None or not settings_file.exists():
        return None
    raw = settings_file.read_text()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(
            f"Error: Invalid settings file '{settings_file}': {e}",
            file=sys.stderr,
        )
        sys.exit(1)
    return json.dumps(data, indent=2, sort_keys=True)


# Matches the baked pi settings.json heredoc: from the opening `cat > ... <<'PI_JSON'`
# line through the closing `PI_JSON` marker. The content is user settings that can
# hold API keys, so it is hidden when the generated Dockerfile is echoed for debugging.
_SETTINGS_HEREDOC_RE = re.compile(
    r"(cat > /root/\.pi/agent/settings\.json <<'PI_JSON'\n).*?(\nPI_JSON)",
    re.DOTALL,
)


def _redact_dockerfile(dockerfile: str) -> str:
    return _SETTINGS_HEREDOC_RE.sub(r"\1<redacted>\2", dockerfile)


def _podman_build(dockerfile: str, image_tag: str, context_dir: str) -> None:
    """Build a Dockerfile via podman build -f <tempfile> -t <tag> <context>."""
    fd, dockerfile_path = tempfile.mkstemp(prefix="agent-pod-", suffix=".Dockerfile")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(dockerfile)
        _run_podman(
            [
                "podman",
                "build",
                "-f",
                dockerfile_path,
                "-t",
                image_tag,
                "--pull=never",
                context_dir,
            ],
            f"building image '{image_tag}'",
        )
    finally:
        os.unlink(dockerfile_path)


def build_image(
    agent_name: str,
    config: AgentConfig,
    settings_file: Path | None = None,
) -> None:
    """Build the agent image: flake image loaded nix-in-docker, then a thin runtime layer.

    Args:
        agent_name: Name of the agent.
        config: Agent configuration.
        settings_file: Optional path to a pi settings.json to bake into the image
            (pi only).

    Raises:
        SystemExit: If the build fails, the settings file is invalid JSON, or the
            flake dir is missing.
    """
    # The settings.json/package bake is pi-specific: only the pi image runs
    # `pi install --approve` on its extension list at build time. Baking it into
    # other agent images would invoke `<agent> install` on a binary that doesn't
    # understand pi packages, failing the build. So only pi loads/bakes settings.
    settings_json = _load_settings(settings_file) if agent_name == "pi" else None
    flake_dir = _check_flake_dir(config.flake)
    # Stage a writable context: the flake imports ./extra-packages.nix, which
    # is generated from config, and bundled flakes may be in a read-only
    # installed wheel. The staged dir (flake.nix + flake.lock + generated
    # extra-packages.nix) is the source of truth for the nix build.
    context_dir = _stage_flake_context(
        flake_dir,
        config.flake.extra_packages or [],
        config.flake.allow_unfree,
        config.flake.permitted_insecure,
    )
    dockerfile = generate_runtime_dockerfile(agent_name, settings_json)

    try:
        print(f"Building image '{config.image_tag}' for {agent_name}...")
        # The generated Dockerfile stays reviewable for debugging, but only under
        # -v; stdout is the launch screen, not build internals.
        logger.debug("Generated Dockerfile:\n%s", _redact_dockerfile(dockerfile))

        digest = _build_input_hash(dockerfile, settings_json, context_dir)
        cache_file = CACHE_DIR / f"{config.image_tag.replace('/', '_')}.hash"
        if (
            cache_file.exists()
            and cache_file.read_text().strip() == digest
            and _image_exists(config.image_tag)
        ):
            print(f"Image '{config.image_tag}' is up to date; skipping build.")
            return

        _check_extra_packages(context_dir, config.flake.extra_packages or [])
        _build_flake_image(context_dir, agent_name)
        _podman_build(dockerfile, config.image_tag, str(context_dir))

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(digest)
    finally:
        shutil.rmtree(context_dir, ignore_errors=True)
