"""Tests for config loader module."""

import pytest

from agent_pod.config import get_agent_config, get_all_agent_names, load_agent_configs


class TestGetAllAgentNames:
    def test_includes_expected_agents(self):
        names = get_all_agent_names()
        assert "pi" in names
        assert "claude" in names
        assert "opencode" in names


class TestGetAgentConfig:
    def test_returns_valid_config_for_pi(self):
        config = get_agent_config("pi")
        assert config.image_tag == "localhost/pi-sandbox:latest"
        assert config.container_name == "pi-sandbox-instance"
        # pi was migrated to the flake path (packaged on nixos-unstable).
        assert config.flake is not None
        assert config.flake.extra_packages == []

    def test_opencode_is_flake_first(self):
        config = get_agent_config("opencode")
        # opencode is on the flake path; its runtime fields are unchanged.
        assert config.flake is not None
        assert config.flake.dir == "config/agents/opencode"
        assert config.image_tag == "localhost/opencode-sandbox:latest"

    def test_no_default_env_passthrough(self):
        # Env passthrough is opt-in: bundled agent configs forward nothing by
        # default, so `ap plan` doesn't list a wall of unused vars. Users opt in
        # per agent via `passthrough_envs` in their own config.
        for name in get_all_agent_names():
            assert get_agent_config(name).passthrough_envs == []

    def test_returns_valid_config_for_claude(self):
        config = get_agent_config("claude")
        assert config.image_tag == "localhost/claude-sandbox:latest"
        assert config.container_name == "claude-sandbox-instance"
        # claude is on the flake path (claude-code packaged on nixos-unstable);
        # its runtime fields are unchanged.
        assert config.flake is not None
        assert config.flake.dir == "config/agents/claude"

    def test_raises_for_unknown_agent(self):
        with pytest.raises(KeyError, match="Unknown agent"):
            get_agent_config("nonexistent")

    def test_config_has_required_fields(self):
        for name in get_all_agent_names():
            config = get_agent_config(name)
            # Every agent is provisioned by a flake (the source of truth for the image).
            assert config.flake is not None
            assert config.image_tag
            assert config.container_name
            assert config.container_home


class TestLoadAgentConfigs:
    def test_all_configs_are_valid(self):
        configs = load_agent_configs()
        for _name, config in configs.items():
            # Pydantic validation ensures all required fields are present; every
            # agent is provisioned by a `flake`.
            assert config.flake is not None
