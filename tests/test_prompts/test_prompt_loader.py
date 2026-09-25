"""Tests for prompt loader module."""

from pathlib import Path

import pytest

from agent_pod.prompts import load_base_prompt


class TestLoadBasePrompt:
    def test_loads_from_bundled_prompt(self, tmp_path, monkeypatch):
        bundled = tmp_path / "git-workflow.md"
        bundled.write_text("# bundled prompt")

        # Patch the module to use our temp file
        import agent_pod.prompts.loader as loader

        monkeypatch.setattr(loader, "_bundled_prompt", lambda: bundled)

        # Also ensure user config dir doesn't have the file
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent_home")

        assert load_base_prompt() == "# bundled prompt"

    def test_raises_when_no_prompt_found(self, tmp_path, monkeypatch):
        # No bundled prompt, no user prompt
        import agent_pod.prompts.loader as loader

        monkeypatch.setattr(
            loader, "_bundled_prompt", lambda: tmp_path / "missing" / "git-workflow.md"
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent_home")

        with pytest.raises(FileNotFoundError, match="Git-workflow skill file not found"):
            load_base_prompt()

    def test_prompt_mentions_git_workflow(self, tmp_path, monkeypatch):
        # Ensure the bundled prompt file exists and has expected content
        bundled = tmp_path / "git-workflow.md"
        bundled.write_text("# Agent workflow\n\nUse `git`")

        import agent_pod.prompts.loader as loader

        monkeypatch.setattr(loader, "_bundled_prompt", lambda: bundled)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent_home")

        result = load_base_prompt()
        assert "git" in result
        assert "workflow" in result.lower()
