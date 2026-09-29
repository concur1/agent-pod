"""Pydantic models for agent configuration validation."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge `override` onto `base`: dicts merge key-by-key, else replace.

    Lists and scalars in `override` fully replace the base value; nested dicts
    (e.g. `flake`, `tmpfs_mounts`) merge field-by-field. This gives predictable
    precedence across config layers without surprising append behavior.
    """
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


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
        examples=["~/dotfiles/aliases.sh"],
        description=(
            "Host file or folder to mount, or a `builtin:` generator id "
            "(`builtin:instructions`, `builtin:ephemeral-git-workflow`) for content agent-pod "
            "generates at runtime. Omit for a writable state file/dir with no host "
            "seed (it is created empty in the session state dir)."
        ),
    )
    name: str = Field(
        ...,
        examples=[".bashrc.d/aliases.sh"],
        description=(
            "Mount name; the container path defaults to `<container_home>/<name>`. "
            "Slash-separated names nest (e.g. `skills/ephemeral-git-workflow/SKILL.md`)."
        ),
    )
    permissions: Literal["ro", "rw"] = Field(
        ...,
        examples=["ro", "rw"],
        description="Mount permissions: read-only (`ro`) or read/write (`rw`).",
    )
    description: str | None = Field(
        default=None,
        examples=["shared aliases"],
        description="Human-readable description shown by `ap plan`.",
    )
    target: str | None = Field(
        default=None,
        examples=["/etc/skills/SKILL.md"],
        description=(
            "Absolute container path override; defaults to `<container_home>/<name>` "
            "(e.g. opencode's auth.json lives outside its home)."
        ),
    )
    optional: bool = Field(
        default=False,
        examples=[True],
        description=(
            "Skip silently if the host `source` is missing (default False prints a "
            "warning and skips). Writable state entries are always created."
        ),
    )
    context: bool = Field(
        default=False,
        examples=[True],
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
        examples=[True],
        description=(
            "For read/write files: copy the host `source` into the session state "
            "dir on first run, then mount the copy writable so the host file is "
            "never modified."
        ),
    )
    secret: bool = Field(
        default=False,
        examples=[True],
        description="Flag the mount as `[secret]` in `ap plan`; values never shown.",
    )
    type: Literal["file", "dir"] | None = Field(
        default=None,
        examples=["file", "dir"],
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


class PassthroughEnv(BaseModel):
    """An environment variable forwarded from the host into the sandbox."""

    name: str = Field(
        ...,
        examples=["HF_TOKEN"],
        description="Environment variable name to forward from the host into the container.",
    )
    description: str = Field(
        ...,
        examples=["Hugging Face token for model downloads"],
        description=(
            "Human-readable description of what the variable is for; required, so "
            "the generated agent instructions and `ap plan` can tell the agent what "
            "each forwarded credential grants and whether it is a secret."
        ),
    )


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
    passthrough_envs: list[PassthroughEnv] = Field(
        default_factory=list,
        description=(
            "Environment variables to pass through from host to container, each with "
            "a required description so the agent understands what the value grants."
        ),
    )
    prompt: str | None = Field(
        default=None,
        examples=["You work on the payments service. Run `make check` before every commit."],
        description=(
            "Optional custom prompt injected at the top of the generated agent "
            "instructions (AGENTS.md), so the agent reads its role/task before the "
            "sandbox grants. Only rendered when set."
        ),
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

    dir: str | None = Field(
        default=None,
        examples=["config/agents/pi"],
        description="See FlakeConfig.dir",
    )
    extra_packages: list[str] | None = Field(
        default=None,
        examples=[["uv", "jq"]],
        description="See FlakeConfig.extra_packages",
    )
    allow_unfree: bool | None = Field(
        default=None,
        examples=[True],
        description="See FlakeConfig.allow_unfree",
    )
    permitted_insecure: list[str] | None = Field(
        default=None,
        examples=[["openssl-1.1.1w"]],
        description="See FlakeConfig.permitted_insecure",
    )


class ProfileConfig(BaseModel):
    """The main config model: a complete user configuration for an agent run.

    Every field is optional, so one instance serves both as the config file's
    top-level defaults (applied to ALL profiles unless explicitly overridden)
    and as a single named profile's overrides on top of those defaults. An
    effective profile — `top_level.merged_with(profiles[name])` — resolves into
    a concrete `AgentConfig` via `get_effective_agent_config`. Every config
    option lives here, so any of them can be supplied per-profile.
    """

    agent: str | None = Field(
        default=None,
        examples=["pi"],
        description="Default agent for `ap run`/`build`/`sessions` when none is given on the CLI.",
    )
    context_files: list[str] | None = Field(
        default=None,
        examples=[["docs/notes.md", "docs/api.md:api.md"]],
        description="Default `--context-file` entries (HOST_PATH[:NAME]).",
    )
    files: list[FileMount] | None = Field(
        default=None,
        examples=[[{"name": "spec.md", "permissions": "ro"}]],
        description=(
            "File/dir mounts appended to the agent's `files` (see AgentConfig.files); a "
            "later mount at the same container path replaces an earlier one."
        ),
    )
    extra_args: list[str] | None = Field(
        default=None,
        examples=[["--model", "sonnet"]],
        description="Default extra args forwarded to the agent.",
    )
    settings_file: str | None = Field(
        default=None,
        examples=["~/.pi/settings.json"],
        description="Default `--settings-file` path.",
    )
    session: str | None = Field(
        default=None,
        examples=["dev"],
        description="Default --session value.",
    )
    ephemeral: bool | None = Field(
        default=None,
        examples=[True],
        description=(
            "Ephemeral git sessions: in a git repo, mount the .git read-write so the "
            "container creates its own per-session worktree on it — only committed "
            "files reach the host. Default false: the working tree is mounted directly "
            "at /sandbox."
        ),
    )
    flake: FlakeOverrides | None = Field(
        default=None,
        examples=[{"extra_packages": ["uv", "jq"], "allow_unfree": True}],
        description="Override of the agent's `flake` config (see AgentConfig.flake).",
    )
    extra_packages: list[str] | None = Field(
        default=None,
        examples=[["uv", "jq"]],
        description=(
            "Nix packages to add to the agent's flake image (shorthand for "
            "`flake.extra_packages`, so it applies to whichever agent is run). "
            "A single string is accepted as a one-item list."
        ),
    )
    allow_unfree: bool | None = Field(
        default=None,
        examples=[True],
        description=(
            "Shorthand for `flake.allow_unfree`: allow unfree nixpkgs packages in the agent image."
        ),
    )
    permitted_insecure: list[str] | None = Field(
        default=None,
        examples=[["openssl-1.1.1w"]],
        description=(
            "Shorthand for `flake.permitted_insecure`: exact nixpkgs package "
            "versions allowed despite being marked insecure."
        ),
    )
    image_tag: str | None = Field(
        default=None,
        examples=["localhost/pi-sandbox:latest"],
        description="See AgentConfig.image_tag",
    )
    container_name: str | None = Field(
        default=None,
        examples=["pi-sandbox-instance"],
        description="See AgentConfig.container_name",
    )
    container_home: str | None = Field(
        default=None,
        examples=["/sandbox"],
        description="See AgentConfig.container_home",
    )
    tmpfs_mounts: dict[str, str] | None = Field(
        default=None,
        examples=[{"/tmp": "rw,exec,size=512m"}],
        description="See AgentConfig.tmpfs_mounts",
    )
    passthrough_envs: list[PassthroughEnv] | None = Field(
        default=None,
        examples=[[{"name": "MY_API_KEY", "description": "API key for the my.example service"}]],
        description="See AgentConfig.passthrough_envs",
    )
    prompt: str | None = Field(
        default=None,
        examples=["You are a release engineer; verify builds before merging."],
        description=(
            "See AgentConfig.prompt — optional custom prompt injected into the "
            "generated agent instructions."
        ),
    )

    @field_validator("extra_packages", mode="before")
    @classmethod
    def _coerce_extra_packages(cls, value: object) -> object:
        """Accept a bare string (`extra_packages: uv`) as a one-item list."""
        if isinstance(value, str):
            return [value]
        return value

    def merged_with(self, overlay: "ProfileConfig") -> "ProfileConfig":
        """Deep-merge `overlay` onto self (self is the baseline); a new config.

        `overlay` wins per key. `files` is the one list that appends instead of
        replacing — self's files stay first, overlay's come after — so a profile
        adds mounts without dropping the baseline's (and a later mount at the
        same container path replaces an earlier one).
        """
        merged = deep_merge(
            self.model_dump(exclude_none=True), overlay.model_dump(exclude_none=True)
        )
        if overlay.files:
            merged["files"] = [f.model_dump(exclude_none=True) for f in (self.files or [])] + [
                f.model_dump(exclude_none=True) for f in overlay.files
            ]
        return ProfileConfig.model_validate(merged)


class UserConfig(ProfileConfig):
    """User-level sandbox configuration file: shared defaults + named profiles.

    The top-level fields (inherited from ProfileConfig) are the baseline applied
    to EVERY profile; a named profile's fields override that baseline per key.
    Loaded from the user's global config file and the working directory's
    `.agent-pod.yaml` (project layer wins per key), then overridden by CLI flags.
    All fields are optional.
    """

    profile: str | None = Field(
        default=None,
        examples=["fixes"],
        description="Default profile name for `ap run`/`plan`.",
    )
    profiles: dict[str, ProfileConfig] = Field(
        default_factory=dict,
        examples=[{"fixes": {"agent": "pi", "extra_args": ["--no-approval"]}}],
        description=(
            "Named profiles: overrides on top of the top-level defaults, plus the "
            "`agent/<profile>/<id>` branch namespace for auto-generated sessions."
        ),
    )

    def effective(self, name: str) -> ProfileConfig:
        """Resolve `name` to its complete config: defaults overlaid with the profile.

        The top-level fields are applied to all configs; `profiles[name]` (if it
        exists, incl. a `default` profile) overrides per key. Result is a full
        `ProfileConfig` that resolves into a concrete `AgentConfig`.
        """
        baseline = self.model_dump(exclude_none=True, exclude={"profile", "profiles"})
        return ProfileConfig.model_validate(baseline).merged_with(
            self.profiles.get(name, ProfileConfig())
        )
