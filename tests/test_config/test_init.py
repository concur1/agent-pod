"""Tests for the interactive `ap init` wizard and first-run auto-init."""

from pathlib import Path

import pytest
import yaml

from agent_pod.config import (
    get_global_config_path,
    get_project_config_path,
    get_user_config,
    user_config_paths,
)
from agent_pod.config.init import (
    _validate_field,
    ensure_user_config,
    run_init,
    write_config,
)
from agent_pod.types import UserConfig


class _TtyStdin:
    """Fake stdin whose isatty() reports True (interactive terminal)."""

    def isatty(self) -> bool:
        return True


class _PipeStdin:
    """Fake stdin whose isatty() reports False (non-interactive)."""

    def isatty(self) -> bool:
        return False


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Point home + cwd at tmp_path so global/project discovery is isolated."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def feed_input(monkeypatch):
    def _feed(*answers):
        it = iter(answers)

        def _input(*a):
            try:
                return next(it)
            except StopIteration:
                # Mimic an EOF (Ctrl-D) once the canned answers run out.
                raise EOFError from None

        monkeypatch.setattr("builtins.input", _input)

    return _feed


def _force_tty(monkeypatch):
    monkeypatch.setattr("agent_pod.config.init.sys.stdin", _TtyStdin())


def _force_pipe(monkeypatch):
    monkeypatch.setattr("agent_pod.config.init.sys.stdin", _PipeStdin())


class TestWriteConfig:
    def test_writes_yaml_with_header(self, tmp_path):
        path = tmp_path / ".agent-pod.yaml"
        write_config(path, {"agent": "pi", "extra_packages": ["uv"]})
        text = path.read_text()
        assert text.startswith("# agent-pod user configuration")
        data = yaml.safe_load(text)
        assert data["agent"] == "pi"
        assert data["extra_packages"] == ["uv"]

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / ".config" / "container-agents" / "config.yaml"
        write_config(path, {"agent": "claude"})
        assert path.exists()
        assert yaml.safe_load(path.read_text())["agent"] == "claude"


class TestRunInit:
    def test_writes_project_config_from_answers(self, isolated_paths, feed_input, monkeypatch):
        _force_tty(monkeypatch)
        # location, agent, context_files, extra_packages
        feed_input("project", "opencode", "docs/api.md", "uv")
        written = run_init()
        assert written == get_project_config_path()
        data = yaml.safe_load(written.read_text())
        assert data == {
            "agent": "opencode",
            "context_files": ["docs/api.md"],
            "extra_packages": ["uv"],
        }

    def test_writes_global_config_with_target_flag(self, isolated_paths, feed_input, monkeypatch):
        _force_tty(monkeypatch)
        feed_input("", "pi", "", "")
        written = run_init(target="global")
        assert written == get_global_config_path()
        assert yaml.safe_load(written.read_text()) == {
            "agent": "pi",
            "context_files": [],
            "extra_packages": ["git", "bash"],
        }

    def test_agent_hint_pre_selects_default(self, isolated_paths, feed_input, monkeypatch):
        _force_tty(monkeypatch)
        # The agent default comes from the hint; other questions are answered.
        feed_input("project", "", "", "")
        written = run_init(agent_hint="claude")
        assert yaml.safe_load(written.read_text()) == {
            "agent": "claude",
            "context_files": [],
            "extra_packages": ["git", "bash"],
        }

    def test_extra_packages_are_prefilled_and_editable(
        self, isolated_paths, feed_input, monkeypatch
    ):
        _force_tty(monkeypatch)
        # Accepting the pre-filled default keeps git+bash; answering replaces it.
        feed_input("project", "pi", "", "")
        written = run_init()
        assert yaml.safe_load(written.read_text())["extra_packages"] == ["git", "bash"]

    def test_extra_packages_can_be_overridden(self, isolated_paths, feed_input, monkeypatch):
        _force_tty(monkeypatch)
        feed_input("project", "pi", "", "uv, jq")
        written = run_init()
        assert yaml.safe_load(written.read_text())["extra_packages"] == ["uv", "jq"]

    def test_agent_is_required_when_no_hint(self, isolated_paths, feed_input, monkeypatch, capsys):
        _force_tty(monkeypatch)
        feed_input("project", "", "pi", "", "")
        written = run_init()
        assert "Please provide a value for agent" in capsys.readouterr().err
        assert yaml.safe_load(written.read_text())["agent"] == "pi"

    def test_written_config_validates_through_get_user_config(
        self, isolated_paths, feed_input, monkeypatch
    ):
        _force_tty(monkeypatch)
        feed_input("project", "pi", "docs/api.md", "uv")
        run_init()
        cfg = get_user_config()
        assert cfg.agent == "pi"
        assert cfg.context_files == ["docs/api.md"]
        assert cfg.extra_packages == ["uv"]

    def test_refuses_when_config_exists_without_force(
        self, isolated_paths, feed_input, monkeypatch, capsys
    ):
        _force_tty(monkeypatch)
        (isolated_paths / ".agent-pod.yaml").write_text("agent: claude\n")
        feed_input("project")
        assert run_init() is None
        # Existing file untouched.
        assert yaml.safe_load((isolated_paths / ".agent-pod.yaml").read_text())["agent"] == "claude"
        assert "already exists" in capsys.readouterr().err

    def test_force_overwrites_existing_project_config(
        self, isolated_paths, feed_input, monkeypatch
    ):
        _force_tty(monkeypatch)
        (isolated_paths / ".agent-pod.yaml").write_text("agent: claude\n")
        feed_input("project", "pi", "", "")
        written = run_init(force=True)
        assert written == get_project_config_path()
        assert yaml.safe_load(written.read_text()) == {
            "agent": "pi",
            "context_files": [],
            "extra_packages": ["git", "bash"],
        }

    def test_global_target_allowed_when_only_project_exists(
        self, isolated_paths, feed_input, monkeypatch
    ):
        _force_tty(monkeypatch)
        (isolated_paths / ".agent-pod.yaml").write_text("agent: claude\n")
        feed_input("", "pi", "true", "", "")
        written = run_init(target="global")
        assert written == get_global_config_path()
        assert written.exists()
        # The pre-existing project config is left untouched.
        assert yaml.safe_load((isolated_paths / ".agent-pod.yaml").read_text())["agent"] == "claude"

    def test_goes_straight_to_questions_without_selection_screen(
        self, isolated_paths, feed_input, monkeypatch, capsys
    ):
        _force_tty(monkeypatch)
        feed_input("project", "pi", "", "")
        run_init()
        out = capsys.readouterr().out
        assert "Options to configure" not in out
        assert "The user config can contain these options" not in out

    def test_ctrl_d_cancels_without_writing(self, isolated_paths, feed_input, monkeypatch, capsys):
        _force_tty(monkeypatch)
        feed_input()  # immediate EOF (Ctrl-D)
        assert run_init() is None
        assert not (isolated_paths / ".agent-pod.yaml").exists()
        assert "Cancelled" in capsys.readouterr().err

    def test_rejects_unknown_agent_and_retries(
        self, isolated_paths, feed_input, monkeypatch, capsys
    ):
        _force_tty(monkeypatch)
        feed_input("project", "not-an-agent", "pi", "", "")
        written = run_init()
        assert "Please choose one of" in capsys.readouterr().err
        assert yaml.safe_load(written.read_text()) == {
            "agent": "pi",
            "context_files": [],
            "extra_packages": ["git", "bash"],
        }


class TestModelValidation:
    def test_validate_field_rejects_wrong_type(self):
        assert _validate_field(UserConfig, "context_files", "oops") is not None
        assert _validate_field(UserConfig, "context_files", ["a"]) is None

    def test_validate_field_rejects_bad_list_item_type(self):
        assert _validate_field(UserConfig, "extra_packages", ["uv", 3]) is not None
        assert _validate_field(UserConfig, "extra_packages", ["uv", "jq"]) is None


class TestUserConfigPaths:
    def test_detects_config_on_any_level(self, isolated_paths):
        assert user_config_paths() == []
        (isolated_paths / ".agent-pod.yaml").write_text("agent: pi\n")
        assert user_config_paths() == [get_project_config_path()]
        global_cfg = isolated_paths / ".config" / "container-agents" / "config.yaml"
        global_cfg.parent.mkdir(parents=True)
        global_cfg.write_text("agent: pi\n")
        assert user_config_paths() == [get_global_config_path(), get_project_config_path()]


class TestEnsureUserConfig:
    def test_noop_when_any_config_exists(self, isolated_paths, monkeypatch):
        (isolated_paths / ".agent-pod.yaml").write_text("agent: claude\n")
        assert ensure_user_config() is None
        # No config file created at the global level.
        assert not (isolated_paths / ".config" / "container-agents" / "config.yaml").exists()

    def test_warns_and_skips_when_non_interactive(self, isolated_paths, capsys, monkeypatch):
        _force_pipe(monkeypatch)
        assert ensure_user_config() is None
        assert not (isolated_paths / ".agent-pod.yaml").exists()
        assert "Run `ap init`" in capsys.readouterr().err

    def test_runs_wizard_when_interactive_and_no_config(
        self, isolated_paths, feed_input, monkeypatch
    ):
        _force_tty(monkeypatch)
        feed_input("project", "opencode", "true", "", "")
        written = ensure_user_config(agent_hint="pi")
        assert written == get_project_config_path()
        data = yaml.safe_load(written.read_text())
        # The selected agent comes from the answer, not the hint default.
        assert data["agent"] == "opencode"
