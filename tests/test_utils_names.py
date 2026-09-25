"""Tests for container naming utilities."""

from agent_pod.types import AgentConfig, FlakeConfig
from agent_pod.utils.names import get_instance_name, humanized_id, valid_session_name


def _cfg(container_name: str) -> AgentConfig:
    return AgentConfig(
        flake=FlakeConfig(dir="agent"),
        image_tag="t",
        container_name=container_name,
        container_home="/root",
    )


class TestValidSessionName:
    def test_rejects_unsafe_names(self):
        for bad in ["../pi2", "/tmp/evil", "a/b", "a\\b", "..", ".", "a b", "a\tb", ""]:
            assert not valid_session_name(bad)

    def test_accepts_plain_names(self):
        for good in ["default", "dev", "fixes-1", "feature_ship"]:
            assert valid_session_name(good)


class TestGetInstanceName:
    def test_default_session_uses_plain_container_name(self):
        assert get_instance_name(_cfg("pi"), "default") == "pi"

    def test_named_session_suffixed(self):
        assert get_instance_name(_cfg("pi"), "dev") == "pi-dev"


class TestHumanizedId:
    def test_shape_and_safety(self, monkeypatch):
        monkeypatch.setattr("agent_pod.utils.names.random.choice", lambda seq: seq[0])
        assert humanized_id() == "amber-acorn"
        # always a valid session/ref name
        assert valid_session_name(humanized_id())

    def test_regenerates_on_collision(self, monkeypatch):
        # Each name mints two picks: adjective then noun.
        picks = iter(["amber", "acorn", "crisp", "lamp"])
        monkeypatch.setattr("agent_pod.utils.names.random.choice", lambda seq: next(picks))
        assert humanized_id({"amber-acorn"}) == "crisp-lamp"
