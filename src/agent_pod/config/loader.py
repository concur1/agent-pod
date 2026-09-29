"""Load and validate agent configurations from YAML files."""

import functools
import logging
from pathlib import Path

import yaml

from agent_pod.types import (
    STATE_DIR,
    AgentConfig,
    ProfileConfig,
    UserConfig,
)
from agent_pod.types import (
    deep_merge as _deep_merge,
)

logger = logging.getLogger(__name__)

# User-level config files share one name everywhere: a per-user one under the
# global state dir plus an optional per-project one in the working directory.
# They are deep-merged (project wins) and then override the bundled agent
# configs and CLI defaults.
CONFIG_NAME = ".agent-pod.yaml"


def _config_dir() -> Path:
    """Return the bundled agent config directory (package data)."""
    return Path(__file__).resolve().parent / "agents"


def _global_config_dir() -> Path:
    """Return the directory holding the user's global agent-pod config."""
    return Path.home() / STATE_DIR


def _project_config_path() -> Path:
    """Return the working-directory user config path."""
    return Path.cwd() / CONFIG_NAME


def get_global_config_path() -> Path:
    """Return the user's global agent-pod config path."""
    return _global_config_dir() / CONFIG_NAME


def get_project_config_path() -> Path:
    """Return the working-directory agent-pod config path."""
    return _project_config_path()


def user_config_paths() -> list[Path]:
    """User config files that exist, global before project."""
    return [p for p in (get_global_config_path(), get_project_config_path()) if p.exists()]


def _load_user_config_file(path: Path) -> UserConfig | None:
    """Load and validate a single user config file, or None if absent.

    Raises:
        yaml.YAMLError: If the file is malformed.
        ValueError: If the file fails validation.
    """
    if not path.exists():
        return None
    try:
        with open(path) as f:
            raw_config = yaml.safe_load(f)
        if raw_config is None:
            return UserConfig()
        return UserConfig.model_validate(raw_config)
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Failed to parse {path}: {e}") from e
    except Exception as e:
        raise ValueError(f"Invalid user config in {path}: {e}") from e


def get_user_config() -> UserConfig:
    """Merge the global and project user configs (project wins per key).

    Only files that exist are read; if none exist an empty UserConfig is returned.
    An unknown default `agent` is warned about (it fails at run time).

    Raises:
        yaml.YAMLError: If a user config file is malformed.
        ValueError: If a user config file fails validation.
    """
    merged = UserConfig()
    for path in (_global_config_dir() / CONFIG_NAME, _project_config_path()):
        config = _load_user_config_file(path)
        if config is None:
            continue
        merged = UserConfig.model_validate(
            _deep_merge(merged.model_dump(exclude_none=True), config.model_dump(exclude_none=True))
        )

    if merged.agent is not None and merged.agent not in load_agent_configs():
        logger.warning("user config default agent '%s' is unknown.", merged.agent)
    return merged


def _user_agent_overrides(user_cfg: ProfileConfig) -> dict:
    """Extract AgentConfig-shaped overrides from a resolved user config.

    The top-level `extra_packages` field is shorthand for `flake.extra_packages`
    and takes precedence over a directly-nested `flake.extra_packages`. Accepts
    a `ProfileConfig` (top-level defaults or an effective profile), which
    `UserConfig` also is.
    """
    result: dict = {}
    if user_cfg.flake is not None:
        result["flake"] = user_cfg.flake.model_dump(exclude_none=True)
    for field in (
        "image_tag",
        "container_name",
        "container_home",
        "tmpfs_mounts",
        "passthrough_envs",
        "prompt",
    ):
        value = getattr(user_cfg, field)
        if value is not None:
            result[field] = value
    if user_cfg.files is not None:
        result["files"] = [f.model_dump(exclude_none=True) for f in user_cfg.files]
    if user_cfg.extra_packages is not None:
        result.setdefault("flake", {})["extra_packages"] = user_cfg.extra_packages
    if user_cfg.allow_unfree is not None:
        result.setdefault("flake", {})["allow_unfree"] = user_cfg.allow_unfree
    if user_cfg.permitted_insecure is not None:
        result.setdefault("flake", {})["permitted_insecure"] = user_cfg.permitted_insecure
    return result


def get_effective_agent_config(
    agent_name: str, user_cfg: ProfileConfig | None = None
) -> AgentConfig:
    """Return the validated agent config with user overrides applied.

    `user_cfg` is the resolved config (top-level defaults merged with the
    active profile, see ``UserConfig.effective``); when None the raw user config
    is used, so bundled-agent builds (`ap build`) get the shared defaults. The
    config is merged with the flat overrides (extra_packages, image_tag, flake,
    ...), then re-validated with the same Pydantic strategy as the agent files.
    Overrides apply to whatever agent is requested.

    `files` is the one list that APPENDS instead of replacing: the user's entries
    come after the bundled agent's (preserving mount order and the position of
    agent-owned built-ins before user files).

    Raises:
        KeyError: If the agent name is not found.
    """
    base = get_agent_config(agent_name)
    resolved = user_cfg if user_cfg is not None else get_user_config()
    overrides = _user_agent_overrides(resolved)
    if not overrides:
        return base
    if "files" in overrides:
        overrides["files"] = [f.model_dump(exclude_none=True) for f in base.files] + overrides[
            "files"
        ]
    merged = _deep_merge(base.model_dump(), overrides)
    return AgentConfig.model_validate(merged)


def load_agent_configs() -> dict[str, AgentConfig]:
    """Load all agent configurations from YAML files.

    Raises:
        FileNotFoundError: If the config directory doesn't exist.
        yaml.YAMLError: If a YAML file is malformed.
        ValueError: If a config fails validation.
    """
    config_dir = _config_dir()
    if not config_dir.exists():
        raise FileNotFoundError(f"Agent config directory not found: {config_dir}")

    configs: dict[str, AgentConfig] = {}
    for yaml_file in config_dir.glob("*.yaml"):
        agent_name = yaml_file.stem
        try:
            with open(yaml_file) as f:
                raw_config = yaml.safe_load(f)
            configs[agent_name] = AgentConfig.model_validate(raw_config)
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Failed to parse {yaml_file}: {e}") from e
        except Exception as e:
            raise ValueError(f"Invalid config for agent '{agent_name}' in {yaml_file}: {e}") from e

    return configs


@functools.cache
def get_all_agent_names() -> list[str]:
    """Return the available agent names, sorted."""
    return sorted(load_agent_configs())


@functools.cache
def get_agent_config(agent_name: str) -> AgentConfig:
    """Return the validated config for an agent.

    Raises:
        KeyError: If the agent name is not found.
    """
    configs = load_agent_configs()
    if agent_name not in configs:
        available = ", ".join(sorted(configs))
        raise KeyError(f"Unknown agent '{agent_name}'. Available: {available}")

    return configs[agent_name]
