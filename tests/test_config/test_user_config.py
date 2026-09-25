"""Tests for user-level config loading and merging."""

from pathlib import Path

import pytest
import yaml

from agent_pod.config import get_effective_agent_config, get_user_config
from agent_pod.config.loader import GLOBAL_CONFIG_NAME, PROJECT_CONFIG_NAME


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Point global + project config discovery at tmp_path."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    return tmp_path


def _write(tmp_path, rel: str, text: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


class TestGetUserConfig:
    def test_no_config_files_returns_empty(self, isolated_paths):
        cfg = get_user_config()
        assert cfg.agent is None
        assert cfg.session is None
        assert cfg.extra_packages is None

    def test_global_config_loads_run_options(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump(
                {
                    "agent": "opencode",
                    "session": "dev",
                    "context_files": ["docs/notes.md"],
                    "extra_packages": "uv",
                }
            ),
        )
        cfg = get_user_config()
        assert cfg.agent == "opencode"
        assert cfg.session == "dev"
        assert cfg.context_files == ["docs/notes.md"]
        # A bare string is coerced to a one-item list.
        assert cfg.extra_packages == ["uv"]

    def test_extra_packages_accepts_list_and_string(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"extra_packages": ["uv", "jq"]}),
        )
        assert get_user_config().extra_packages == ["uv", "jq"]

    def test_project_config_wins_over_global(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"agent": "opencode", "session": "dev"}),
        )
        _write(isolated_paths, PROJECT_CONFIG_NAME, yaml.safe_dump({"session": "stage"}))
        cfg = get_user_config()
        # Project overrides session but leaves unset global options intact.
        assert cfg.session == "stage"
        assert cfg.agent == "opencode"

    def test_overrides_merge_across_layers(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"extra_packages": ["uv"], "image_tag": "a:1"}),
        )
        _write(isolated_paths, PROJECT_CONFIG_NAME, yaml.safe_dump({"image_tag": "b:2"}))
        cfg = get_user_config()
        assert cfg.extra_packages == ["uv"]
        assert cfg.image_tag == "b:2"

    def test_list_entries_replace_not_append(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"passthrough_envs": ["A"]}),
        )
        _write(
            isolated_paths,
            PROJECT_CONFIG_NAME,
            yaml.safe_dump({"passthrough_envs": ["B"]}),
        )
        assert get_user_config().passthrough_envs == ["B"]

    def test_unknown_default_agent_warns(self, isolated_paths, capsys):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"agent": "nope"}),
        )
        get_user_config()
        assert "default agent 'nope' is unknown" in capsys.readouterr().err

    def test_invalid_config_raises_value_error(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"session": 123}),
        )
        with pytest.raises(ValueError, match="Invalid user config"):
            get_user_config()


class TestGetEffectiveAgentConfig:
    def test_unchanged_without_overrides(self, isolated_paths):
        config = get_effective_agent_config("opencode")
        assert config.image_tag == "localhost/opencode-sandbox:latest"
        # extra_packages moved out of the bundled agent config entirely.
        assert config.flake.extra_packages == []

    def test_extra_packages_map_to_flake(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"extra_packages": ["uv", "jq"]}),
        )
        config = get_effective_agent_config("opencode")
        assert config.flake.extra_packages == ["uv", "jq"]
        # Untouched bundled fields are preserved.
        assert config.flake.dir == "config/agents/opencode"

    def test_flat_overrides_and_bundled_fields_kept(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump(
                {"image_tag": "localhost/custom:latest", "container_name": "my-instance"}
            ),
        )
        config = get_effective_agent_config("opencode")
        assert config.image_tag == "localhost/custom:latest"
        assert config.container_name == "my-instance"
        assert config.flake.dir == "config/agents/opencode"

    def test_overrides_apply_to_any_agent(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"agent": "opencode", "extra_packages": ["uv"]}),
        )
        # The config targets opencode, but overrides still apply to pi.
        config = get_effective_agent_config("pi")
        assert config.flake.extra_packages == ["uv"]

    def test_extra_packages_wins_over_nested_flake(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"extra_packages": ["uv"], "flake": {"dir": "config/agents/pi"}}),
        )
        config = get_effective_agent_config("opencode")
        assert config.flake.dir == "config/agents/pi"
        assert config.flake.extra_packages == ["uv"]

    def test_unfree_shorthands_map_to_flake(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"allow_unfree": True, "permitted_insecure": ["openssl-1.1.1w"]}),
        )
        config = get_effective_agent_config("opencode")
        assert config.flake.allow_unfree is True
        assert config.flake.permitted_insecure == ["openssl-1.1.1w"]

    def test_unfree_shorthands_wins_over_nested_flake(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump(
                {
                    "allow_unfree": True,
                    "flake": {"allow_unfree": False, "permitted_insecure": ["a:1"]},
                }
            ),
        )
        config = get_effective_agent_config("opencode")
        # Top-level shorthand takes precedence over the nested flake field.
        assert config.flake.allow_unfree is True
        assert config.flake.permitted_insecure == ["a:1"]

    def test_unfree_defaults_when_unset(self, isolated_paths):
        config = get_effective_agent_config("opencode")
        assert config.flake.allow_unfree is False
        assert config.flake.permitted_insecure == []

    def test_lists_replace_bundled_values(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"passthrough_envs": ["SCALAWAY_TOKEN"]}),
        )
        config = get_effective_agent_config("opencode")
        # Replace semantics: bundled passthrough list is fully replaced.
        assert config.passthrough_envs == ["SCALAWAY_TOKEN"]

    def test_user_files_append_to_bundled(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump(
                {
                    "files": [
                        {
                            "source": "~/extra/notes.md",
                            "name": "notes.md",
                            "permissions": "ro",
                            "description": "extra notes",
                        }
                    ]
                }
            ),
        )
        config = get_effective_agent_config("opencode")
        # The agent's own entries come first (builtins keep their position) and
        # the user's entries are appended.
        assert any(f.source == "builtin:instructions" for f in config.files)
        assert any(f.source == "builtin:git-workflow" for f in config.files)
        assert config.files[-1].name == "notes.md"
        assert config.files[-1].source == "~/extra/notes.md"
        assert config.files[-1].permissions == "ro"
        assert config.files[-1].description == "extra notes"

    def test_user_files_append_applies_to_any_agent(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump(
                {"files": [{"name": "tools", "permissions": "rw", "description": "tools dir"}]}
            ),
        )
        config = get_effective_agent_config("pi")
        assert config.files[-1].name == "tools"
        # pi's own writable state (auth.json, sessions) is still present.
        assert any(
            f.name == "auth.json" and not f.seed and f.permissions == "rw"
            for f in config.files
        )

    def test_bad_type_fails_validation(self, isolated_paths):
        _write(
            isolated_paths,
            f".config/container-agents/{GLOBAL_CONFIG_NAME}",
            yaml.safe_dump({"extra_packages": [1]}),
        )
        # Bad types fail Pydantic validation (the same strategy as agent files),
        # surfacing as a ValueError from the user config load.
        with pytest.raises(ValueError, match="Input should be a valid string"):
            get_effective_agent_config("opencode")
