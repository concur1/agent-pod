"""Pydantic models for agent configuration validation."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Base directory under the user's home holding agent-pod state and config.
# Relative so each consumer resolves it against the current home at call time
# (tests patch Path.home); the runner additionally exports it as BASE_STATE_DIR.
STATE_DIR = Path(".config") / "container-agents"

# Profile selected when `ap run`/`ap plan` get no profile and the config sets none.
DEFAULT_PROFILE = "default"


class FlakeConfig(BaseModel):
    """Flake-based build config: content comes from a nix flake, runtime from agent-pod."""

    dir: str = Field(
        ...,
        description="Directory containing flake.nix + flake.lock (relative to the repo root)",
    )
    extra_packages: list[str] = Field(
        default_factory=list,
        description=(
            "Additional nix package attr names (e.g. 'uv') to install into the image from "
            "the flake's locked nixpkgs input and expose on PATH. Prefer these over apt "
            "for deployable tooling; the agent itself and git are always in the closure."
        ),
    )
    allow_unfree: bool = Field(
        default=False,
        description=(
            "Allow nixpkgs packages with unfree licenses in `extra_packages` "
            "(e.g. 'unrar'). False by default; nix refuses to evaluate unfree "
            "packages otherwise."
        ),
    )
    permitted_insecure: list[str] = Field(
        default_factory=list,
        description=(
            "Exact nixpkgs package versions allowed despite being marked "
            "insecure, e.g. ['openssl-1.1.1w']. Default-deny: insecure software "
            "in an agent sandbox is a deliberate, per-version opt-in."
        ),
    )


class FileMount(BaseModel):
    """A file or directory supplied to the sandbox."""

    source: str | None = Field(
        default=None,
        description=(
            "Host file or folder to mount, or a `builtin:` generator id "
            "(`builtin:instructions`, `builtin:git-workflow`) for content agent-pod "
            "generates at runtime. Omit for a writable state file/dir with no host "
            "seed (it is created empty in the session state dir)."
        ),
    )
    name: str = Field(
        ...,
        description=(
            "Mount name; the container path defaults to `<container_home>/<name>`. "
            "Slash-separated names nest (e.g. `skills/git-workflow/SKILL.md`)."
        ),
    )
    permissions: Literal["ro", "rw"] = Field(
        ...,
        description="Mount permissions: read-only (`ro`) or read/write (`rw`).",
    )
    description: str | None = Field(
        default=None,
        description="Human-readable description shown by `ap plan`.",
    )
    target: str | None = Field(
        default=None,
        description=(
            "Absolute container path override; defaults to `<container_home>/<name>` "
            "(e.g. opencode's auth.json lives outside its home)."
        ),
    )
    optional: bool = Field(
        default=False,
        description=(
            "Skip silently if the host `source` is missing (default False prints a "
            "warning and skips). Writable state entries are always created."
        ),
    )
    context: bool = Field(
        default=False,
        description=(
            "Treat the file as a context file: mounted read-only into the shared "
            "contexts dir, listed in the generated instructions, and passed to pi "
            "as an `@<path>` arg. `--context-file` / the `context_files` config key "
            "are sugar for a `context: true` files entry; adding `context: true` "
            "here is the generic form."
        ),
    )
    seed: bool = Field(
        default=False,
        description=(
            "For read/write files: copy the host `source` into the session state "
            "dir on first run, then mount the copy writable so the host file is "
            "never modified."
        ),
    )
    secret: bool = Field(
        default=False,
        description="Flag the mount as `[secret]` in `ap plan`; values never shown.",
    )
    type: Literal["file", "dir"] | None = Field(
        default=None,
        description=(
            "Explicit file/dir kind for writable state entries; inferred when "
            "omitted (`file` when `seed` is set, otherwise from the source's type "
            "or the name's extension)."
        ),
    )

    @property
    def effective_type(self) -> Literal["file", "dir"]:
        """The file/dir kind used for writable state entries."""
        if self.type is not None:
            return self.type
        if self.seed:
            return "file"
        if self.source:
            host = Path(self.source).expanduser()
            if host.exists():
                return "file" if host.is_file() else "dir"
            return "file" if Path(self.name).suffix else "dir"
        return "file" if Path(self.name).suffix else "dir"


class AgentConfig(BaseModel):
    """Runtime configuration for an agent container."""

    flake: FlakeConfig = Field(
        ...,
        description="Flake-based build config: the environment comes from the flake's image output",
    )
    image_tag: str = Field(
        ...,
        description="Full image tag for the built container (e.g., 'localhost/pi-sandbox:latest')",
    )
    container_name: str = Field(
        ...,
        description="Base name for the container instance",
    )
    container_home: str = Field(
        ...,
        description="Home directory path inside the container for agent state",
    )
    files: list[FileMount] = Field(
        default_factory=list,
        description=(
            "Files and directories supplied to the sandbox: host passthrough "
            "(read-only mirrors), generated instruction/skill files, and writable "
            "state seeded from the host. Mount order follows list order."
        ),
    )
    tmpfs_mounts: dict[str, str] = Field(
        default_factory=dict,
        description="RAM-backed tmpfs mounts (container_path -> mount_options)",
    )
    passthrough_envs: list[str] = Field(
        default_factory=list,
        description="Environment variables to pass through from host to container",
    )

    @property
    def writable_state(self) -> list[FileMount]:
        """Read/write entries whose state lives in the session state dir.

        These are the entries `ensure_host_paths` creates and `ap sessions --rm`
        cleans up: writable entries with a `seed` (host copy on first run) or no
        `source` (empty state file/dir). A plain writable host-path mount is
        excluded — it points at the host directly.
        """
        return [f for f in self.files if f.permissions == "rw" and (f.seed or f.source is None)]

    def file_container_path(self, entry: FileMount) -> str:
        """The container path a file entry mounts at."""
        return entry.target or f"{self.container_home}/{entry.name}"


class FlakeOverrides(BaseModel):
    """All-optional mirror of FlakeConfig so user configs can override any subset."""

    dir: str | None = Field(default=None, description="See FlakeConfig.dir")
    extra_packages: list[str] | None = Field(
        default=None,
        description="See FlakeConfig.extra_packages",
    )
    allow_unfree: bool | None = Field(default=None, description="See FlakeConfig.allow_unfree")
    permitted_insecure: list[str] | None = Field(
        default=None,
        description="See FlakeConfig.permitted_insecure",
    )


class ProfileConfig(BaseModel):
    """Run-level overrides for a named profile (see UserConfig.profiles).

    A profile names a branch namespace (`agent/<profile>/<id>`) and can pin the
    agent-run options. Each set field overlays the merged top-level user config
    for that key; unset fields inherit the top level.
    """

    agent: str | None = Field(
        default=None,
        description=(
            "Harness agent when this profile is active (else the config's default `agent`)."
        ),
    )
    context_files: list[str] | None = Field(
        default=None, description="Default `--context-file` entries (HOST_PATH[:NAME])."
    )
    files: list[FileMount] | None = Field(
        default=None,
        description=(
            "Extra file/dir mounts added when this profile is active, appended "
            "after the top-level `files`. A later mount at the same container "
            "path replaces an earlier one — e.g. flip the bundled read-only "
            "skills mount to read/write (`source: ~/.agent/skills, name: skills, "
            "permissions: rw, seed: true`)."
        ),
    )
    extra_args: list[str] | None = Field(
        default=None, description="Default extra args forwarded to the agent."
    )
    settings_file: str | None = Field(default=None, description="Default `--settings-file` path.")


class UserConfig(BaseModel):
    """User-level sandbox configuration (flat, single-agent oriented).

    Loaded from the user's global config file and the working directory's
    `.agent-pod.yaml` (project layer wins per key), then overridden by CLI flags.
    All fields are optional. `agent` is the default agent for `ap run`; run-flag
    fields mirror the CLI options; the remaining fields override the bundled
    agent config of whichever agent is run (lists replace, dicts merge key-by-key).
    """

    agent: str | None = Field(
        default=None,
        description="Default agent for `ap run`/`build`/`sessions` when none is given on the CLI.",
    )
    profile: str | None = Field(
        default=None, description="Default profile name for `ap run`/`plan`."
    )
    profiles: dict[str, ProfileConfig] = Field(
        default_factory=dict,
        description=(
            "Named profiles: run-level overrides plus the `agent/<profile>/<id>` "
            "branch namespace for auto-generated sessions."
        ),
    )
    session: str | None = Field(default=None, description="Default --session value.")
    ephemeral: bool | None = Field(
        default=None,
        description=(
            "Ephemeral git sessions: in a git repo, mount the .git read-write so the "
            "container creates its own per-session worktree on it — only committed "
            "files reach the host. Default false: the working tree is mounted directly "
            "at /sandbox."
        ),
    )
    context_files: list[str] | None = Field(
        default=None, description="Default --context-file entries (HOST_PATH[:NAME])."
    )
    settings_file: str | None = Field(default=None, description="Default --settings-file path.")
    extra_args: list[str] | None = Field(
        default=None, description="Default extra args forwarded to the agent."
    )
    flake: FlakeOverrides | None = Field(
        default=None, description="Override of the agent's `flake` config (see AgentConfig.flake)."
    )
    extra_packages: list[str] | None = Field(
        default=None,
        description=(
            "Nix packages to add to the agent's flake image (shorthand for "
            "`flake.extra_packages`, so it applies to whichever agent is run). "
            "A single string is accepted as a one-item list."
        ),
    )
    allow_unfree: bool | None = Field(
        default=None,
        description=(
            "Shorthand for `flake.allow_unfree`: allow unfree nixpkgs packages in the agent image."
        ),
    )
    permitted_insecure: list[str] | None = Field(
        default=None,
        description=(
            "Shorthand for `flake.permitted_insecure`: exact nixpkgs package "
            "versions allowed despite being marked insecure."
        ),
    )
    image_tag: str | None = Field(default=None, description="See AgentConfig.image_tag")
    container_name: str | None = Field(default=None, description="See AgentConfig.container_name")
    container_home: str | None = Field(default=None, description="See AgentConfig.container_home")
    files: list[FileMount] | None = Field(
        default=None,
        description=(
            "Files/dirs to append to the agent's `files` (see AgentConfig.files). "
            "Unlike other lists, user `files` are APPENDED to the bundled agent's, "
            "so per-agent built-ins keep their position and your entries come after."
        ),
    )
    tmpfs_mounts: dict[str, str] | None = Field(
        default=None, description="See AgentConfig.tmpfs_mounts"
    )
    passthrough_envs: list[str] | None = Field(
        default=None, description="See AgentConfig.passthrough_envs"
    )

    @field_validator("extra_packages", mode="before")
    @classmethod
    def _coerce_extra_packages(cls, value: object) -> object:
        """Accept a bare string (`extra_packages: uv`) as a one-item list."""
        if isinstance(value, str):
            return [value]
        return value
