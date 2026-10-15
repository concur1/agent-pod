"""Tests for skill loader module."""

from pathlib import Path

import pytest

from agent_pod.skills import load_skill
from agent_pod.types import STATE_DIR


class TestLoadSkill:
    def test_loads_from_bundled_skill(self):
        content = load_skill("agent-pod-config")
        assert "agent-pod-config" in content

    def test_falls_back_to_user_prompt(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        prompts = tmp_path / STATE_DIR / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "my-skill.md").write_text("# user prompt")

        assert load_skill("my-skill") == "# user prompt"

    def test_raises_when_no_skill_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent_home")

        with pytest.raises(FileNotFoundError, match="Skill file for 'missing' not found"):
            load_skill("missing")
