"""Tests for skill loader module."""

from pathlib import Path

import pytest

from agent_pod.skills import load_base_prompt


class TestLoadBasePrompt:
    def test_loads_from_bundled_skill(self, tmp_path, monkeypatch):
        bundled = tmp_path / "SKILL.md"
        bundled.write_text("# bundled prompt")

        # Patch the module to use our temp file
        import agent_pod.skills.loader as loader

        monkeypatch.setattr(loader, "_bundled_prompt", lambda: bundled)

        # Also ensure user config dir doesn't have the file
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent_home")

        assert load_base_prompt() == "# bundled prompt"

    def test_raises_when_no_skill_found(self, tmp_path, monkeypatch):
        # No bundled skill, no user skill
        import agent_pod.skills.loader as loader

        monkeypatch.setattr(loader, "_bundled_prompt", lambda: tmp_path / "missing" / "SKILL.md")
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent_home")

        with pytest.raises(FileNotFoundError, match="Ephemeral git-workflow skill file not found"):
            load_base_prompt()
