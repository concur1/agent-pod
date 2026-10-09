"""Tests for CLI module."""

import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agent_pod.cli import (
    _open_session_instances,
    _parse_context_files,
    _session_label,
    cmd_sessions,
    main,
)
from agent_pod.types import FileMount


class TestParseContextFiles:
    def test_accepts_host_path_with_implicit_name(self, tmp_path):
        f = tmp_path / "notes.md"
        f.write_text("x")
        mounts = _parse_context_files([str(f)])
        assert len(mounts) == 1
        assert mounts[0].name == "notes.md"
        assert mounts[0].source == str(f.resolve())
        assert mounts[0].context is True
        assert mounts[0].permissions == "ro"

    def test_accepts_explicit_plain_name(self, tmp_path):
        f = tmp_path / "notes.md"
        f.write_text("x")
        mounts = _parse_context_files([f"{f}:api.md"])
        assert len(mounts) == 1
        assert (mounts[0].name, mounts[0].source) == ("api.md", str(f.resolve()))

    @pytest.mark.parametrize(
        "bad",
        [
            "a/b.md",
            "a\\b.md",
            "..",
            ".",
            "a b.md",
            "a\tb.md",
            "",
            "x:",
        ],
    )
    def test_rejects_unsafe_names(self, bad, tmp_path, capsys):
        f = tmp_path / "notes.md"
        f.write_text("x")
        with pytest.raises(SystemExit) as excinfo:
            _parse_context_files([f"{f}:{bad}"])
        assert excinfo.value.code == 2
        assert "invalid --context-file name" in capsys.readouterr().err


class TestOpenSessions:
    def test_session_label(self):
        base = "pi-sandbox-instance"
        assert _session_label(base, base) == "default"
        assert _session_label(base, "pi-sandbox-instance-crisp-lamp") == "crisp-lamp"

    def test_open_session_instances_filters_by_base_and_running_only(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return type(
                "R",
                (),
                {"stdout": "pi-sandbox-instance\npi-sandbox-instance-alpha\nother-sandbox\n"},
            )()

        monkeypatch.setattr("agent_pod.cli.subprocess.run", fake_run)
        assert _open_session_instances("pi-sandbox-instance") == [
            "pi-sandbox-instance",
            "pi-sandbox-instance-alpha",
        ]
        assert calls == [["podman", "ps", "--format", "{{.Names}}"]]

    def test_open_session_instances_handles_missing_podman(self, monkeypatch):
        monkeypatch.setattr(
            "agent_pod.cli.subprocess.run",
            lambda cmd, **kwargs: (_ for _ in ()).throw(FileNotFoundError("podman")),
        )
        assert _open_session_instances("pi-sandbox-instance") == []


class TestMainArgparse:
    @pytest.fixture
    def no_config(self, tmp_path, monkeypatch):
        """Isolated home + cwd with no user config on any level."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return tmp_path

    @patch("agent_pod.cli.humanized_id", return_value="crisp-lamp")
    @patch("agent_pod.cli.run_agent")
    def test_run_subcommand(self, mock_run_agent, mock_humanized, no_config):
        with patch.object(sys, "argv", ["ap", "run", "--agent", "pi"]):
            main()
        mock_run_agent.assert_called_once()
        args, kwargs = mock_run_agent.call_args
        assert args[0] == "pi"
        # Auto sessions get a fresh humanized id, not the profile name.
        assert kwargs["session"] == "crisp-lamp"
        assert kwargs["profile"] == "default"
        assert kwargs["use_bash"] is False

    @patch("agent_pod.container.build_image")
    def test_build_subcommand(self, mock_build_image):
        with patch.object(sys, "argv", ["ap", "build", "claude"]):
            main()
        mock_build_image.assert_called_once()
        args = mock_build_image.call_args.args
        assert args[0] == "claude"

    @patch("builtins.print")
    def test_list_subcommand_lists_default_profile(self, mock_print, no_config):
        # `ap list` always shows the `default` profile (the baseline config),
        # not agents — those are `ap list --agents` territory.
        with patch.object(sys, "argv", ["ap", "list"]):
            main()
        output = " ".join(str(call) for call in mock_print.call_args_list)
        assert "Configured Profiles" in output
        assert "- default" in output
        assert "No profiles configured" not in output

    @patch("builtins.print")
    def test_list_agents_subcommand(self, mock_print, no_config):
        with patch.object(sys, "argv", ["ap", "list", "--agents"]):
            main()
        output = " ".join(str(call) for call in mock_print.call_args_list)
        assert "Configured Agents" in output
        assert "pi" in output
        assert "opencode" in output

    @patch("builtins.print")
    def test_list_subcommand_default_profile_shows_agent(self, mock_print, tmp_path, monkeypatch):
        """The default profile's summary reflects its effective agent — including
        when the agent is set inside a `profiles: {default: …}` block."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".agent-pod.yaml").write_text(
            "profile: default\nprofiles:\n  default:\n    agent: pi\n"
        )
        with patch.object(sys, "argv", ["ap", "list"]):
            main()
        out = " ".join(str(call) for call in mock_print.call_args_list)
        assert "default (active)" in out
        assert "agent=pi" in out
        # The profiles.default key is not repeated as a named profile.
        assert out.count("- default") == 1

    @patch("builtins.print")
    def test_list_subcommand_lists_profiles(self, mock_print, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".agent-pod.yaml").write_text(
            "profile: fixes\n"
            "profiles:\n"
            "  fixes:\n"
            "    agent: pi\n"
            "    extra_args: [--no-approval]\n"
            "  chores:\n"
            "    agent: opencode\n"
            "    context_files: [docs/notes.md]\n"
        )
        with patch.object(sys, "argv", ["ap", "list"]):
            main()
        out = " ".join(str(call) for call in mock_print.call_args_list)
        # The default profile row always precedes the named ones.
        assert out.index("- default") < out.index("- fixes")
        assert "fixes (active)" in out
        assert "agent=pi" in out
        assert "--no-approval" in out
        assert "chores" in out
        assert "agent=opencode" in out
        assert "1 context file(s)" in out

    @patch("builtins.print")
    def test_plan_subcommand_renders_permission_screen(self, mock_print, no_config):
        with patch.object(sys, "argv", ["ap", "plan", "--agent", "pi"]):
            main()
        output = " ".join(str(call) for call in mock_print.call_args_list)
        assert "FILESYSTEM ACCESS" in output
        assert "ENVIRONMENT VARIABLES" in output
        assert "NETWORK & CAPABILITIES" in output
        assert "read/write" in output

    def test_context_subcommand_prints_generated_instructions(self, no_config, capsys):
        # `ap context` renders the exact AGENTS.md the agent would get: the
        # live sandbox grants, not the plan's summary screen.
        with patch.object(sys, "argv", ["ap", "context", "--agent", "pi"]):
            main()
        out = capsys.readouterr().out
        assert out.startswith("# Agent instructions")
        assert "## Environment" in out
        # No ephemeral mode configured here, so no version-control section.
        assert "## Version control" not in out
        assert "## Sandbox access" in out
        # Empty context-files section is omitted (no context files here).
        assert "## Context files" not in out
        assert "/sandbox — read/write" in out
        # No plan-screen framing leaked in.
        assert "FILESYSTEM ACCESS" not in out
        assert "NETWORK & CAPABILITIES" not in out

    def test_context_in_help(self, no_config, capsys):
        with pytest.raises(SystemExit) as exc, patch.object(sys, "argv", ["ap", "--help"]):
            main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "context" in out

    @patch("agent_pod.cli.run_agent")
    def test_run_with_session(self, mock_run_agent, no_config):
        with patch.object(sys, "argv", ["ap", "run", "--agent", "pi", "--session", "dev"]):
            main()
        _, kwargs = mock_run_agent.call_args
        assert kwargs["session"] == "dev"

    @patch("agent_pod.cli.run_agent")
    def test_shell_subcommand(self, mock_run_agent, no_config):
        with patch.object(sys, "argv", ["ap", "shell", "--agent", "pi"]):
            main()
        args, kwargs = mock_run_agent.call_args
        assert args[0] == "pi"
        assert kwargs["use_bash"] is True

    @patch("agent_pod.cli.run_agent")
    def test_shell_drops_extra_agent_args_in_bash_mode(self, mock_run_agent, no_config):
        with patch.object(sys, "argv", ["ap", "shell", "--agent", "claude", "--", "--foo"]):
            main()
        args, kwargs = mock_run_agent.call_args
        assert args[0] == "claude"
        assert kwargs["use_bash"] is True
        # CLI args are still threaded; the runner ignores them in bash mode.
        assert args[1] == ["--foo"]

    @patch("agent_pod.cli.run_agent")
    def test_shell_attaches_to_picked_session(self, mock_run_agent, no_config, monkeypatch):
        """With open sessions `ap shell` execs into the chosen one, never launching."""
        exec_calls = []

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["podman", "ps"]:
                return type("R", (), {"stdout": "pi-sandbox-instance-alpha\n"})()
            exec_calls.append(cmd)
            return type("R", (), {"returncode": 0})()

        monkeypatch.setattr("agent_pod.cli.subprocess.run", fake_run)
        with (
            patch.object(sys, "argv", ["ap", "shell", "--agent", "pi"]),
            patch("builtins.input", return_value="1"),
            pytest.raises(SystemExit) as exc,
        ):
            main()
        assert exc.value.code == 0
        mock_run_agent.assert_not_called()
        assert exec_calls == [["podman", "exec", "-it", "pi-sandbox-instance-alpha", "bash"]]

    @patch("agent_pod.cli.run_agent")
    def test_shell_no_open_sessions_still_launches(self, mock_run_agent, no_config, monkeypatch):
        monkeypatch.setattr(
            "agent_pod.cli.subprocess.run",
            lambda cmd, **kwargs: type("R", (), {"stdout": ""})(),
        )
        with patch.object(sys, "argv", ["ap", "shell", "--agent", "pi"]):
            main()
        mock_run_agent.assert_called_once()

    @patch("agent_pod.cli.run_agent")
    def test_run_with_context_file(self, mock_run_agent, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        ctx = tmp_path / "context.md"
        ctx.write_text("# context")
        with patch.object(sys, "argv", ["ap", "run", "--agent", "pi", "--context-file", str(ctx)]):
            main()
        _, kwargs = mock_run_agent.call_args
        context_mounts = kwargs["context_files"]
        assert len(context_mounts) == 1
        assert context_mounts[0].source == str(ctx.resolve())
        assert context_mounts[0].name == "context.md"
        assert context_mounts[0].context is True

    @patch("agent_pod.cli.run_agent")
    def test_run_settings_file_defaults_to_pi_global(self, mock_run_agent, no_config):
        with patch.object(sys, "argv", ["ap", "run", "--agent", "pi"]):
            main()
        _, kwargs = mock_run_agent.call_args
        assert kwargs["settings_file"] == (Path.home() / ".pi" / "settings.json").resolve()

    @patch("agent_pod.cli.run_agent")
    def test_run_non_pi_agent_gets_no_settings_file(self, mock_run_agent, no_config):
        # The settings-file bake is pi-specific; other agents resolve none, so no
        # spurious "settings file not found" warning is printed for them.
        with patch.object(sys, "argv", ["ap", "run", "--agent", "claude"]):
            main()
        _, kwargs = mock_run_agent.call_args
        assert kwargs["settings_file"] is None

    @patch("agent_pod.container.build_image")
    def test_build_settings_file_defaults_to_pi_global(self, mock_build_image):
        with patch.object(sys, "argv", ["ap", "build", "pi"]):
            main()
        args = mock_build_image.call_args.args
        assert args[2] == (Path.home() / ".pi" / "settings.json").resolve()

    @patch("agent_pod.container.build_image")
    def test_build_non_pi_agent_gets_no_settings_file(self, mock_build_image):
        with patch.object(sys, "argv", ["ap", "build", "claude"]):
            main()
        args = mock_build_image.call_args.args
        # The settings-file bake is pi-specific; non-pi agents resolve none.
        assert args[2] is None

    @patch("agent_pod.cli.run_agent")
    def test_run_ignores_standalone_double_dash(self, mock_run_agent, no_config):
        with patch.object(sys, "argv", ["ap", "run", "--agent", "pi", "--", "--flag"]):
            main()
        args, _ = mock_run_agent.call_args
        # The standalone '--' is stripped from extra args
        assert args[1] == ["--flag"]

    @patch("agent_pod.cli.run_agent")
    def test_run_with_context_file_and_name(self, mock_run_agent, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        ctx = tmp_path / "mydir" / "custom-name.md"
        ctx.parent.mkdir(parents=True)
        ctx.write_text("# context")
        with patch.object(
            sys,
            "argv",
            ["ap", "run", "--agent", "pi", "--context-file", f"{ctx}:renamed.md"],
        ):
            main()
        _, kwargs = mock_run_agent.call_args
        context_mounts = kwargs["context_files"]
        assert len(context_mounts) == 1
        assert (context_mounts[0].source, context_mounts[0].name) == (
            str(ctx.resolve()),
            "renamed.md",
        )


class TestRunUsesUserConfig:
    @pytest.fixture
    def user_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        global_dir = tmp_path / ".config" / "container-agents"
        global_dir.mkdir(parents=True)
        (global_dir / ".agent-pod.yaml").write_text(
            "agent: opencode\nsession: dev\ncontext_files:\n  - docs/notes.md\n"
            "extra_args: [--verbose]\n"
        )
        return tmp_path

    @patch("agent_pod.cli.run_agent")
    def test_run_defaults_to_config_agent(self, mock_run_agent, user_config):
        with patch.object(sys, "argv", ["ap", "run"]):
            main()
        args, _ = mock_run_agent.call_args
        assert args[0] == "opencode"

    @patch("agent_pod.cli.run_agent")
    def test_agent_flag_overrides_config_default(self, mock_run_agent, user_config):
        with patch.object(sys, "argv", ["ap", "run", "--agent", "pi"]):
            main()
        args, _ = mock_run_agent.call_args
        assert args[0] == "pi"

    @patch("agent_pod.cli.run_agent")
    def test_config_values_apply_when_flags_absent(self, mock_run_agent, user_config):
        ctx = user_config / "docs" / "notes.md"
        ctx.parent.mkdir(parents=True)
        ctx.write_text("x")
        with patch.object(sys, "argv", ["ap", "run", "--agent", "pi"]):
            main()
        args, kwargs = mock_run_agent.call_args
        assert kwargs["session"] == "dev"
        assert len(kwargs["context_files"]) == 1
        context_mount = kwargs["context_files"][0]
        assert (context_mount.source, context_mount.name) == (
            str(ctx.resolve()),
            "notes.md",
        )
        assert args[1] == ["--verbose"]

    @patch("agent_pod.cli.run_agent")
    def test_agent_flag_overrides_config_session(self, mock_run_agent, user_config):
        with patch.object(sys, "argv", ["ap", "run", "--agent", "pi", "--session", "prod"]):
            main()
        _, kwargs = mock_run_agent.call_args
        assert kwargs["session"] == "prod"

    @patch("agent_pod.cli.run_agent")
    def test_extra_args_override_config_extra_args(self, mock_run_agent, user_config):
        with patch.object(sys, "argv", ["ap", "run", "--agent", "pi", "--", "--foo"]):
            main()
        args, _ = mock_run_agent.call_args
        assert args[1] == ["--foo"]

    def test_unknown_config_agent_exits_with_friendly_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        global_dir = tmp_path / ".config" / "container-agents"
        global_dir.mkdir(parents=True)
        (global_dir / ".agent-pod.yaml").write_text("agent: nonexistent-agent\n")

        with (
            patch.object(sys, "argv", ["ap", "run"]),
            patch("agent_pod.cli.run_agent") as mock_run_agent,
            pytest.raises(SystemExit) as excinfo,
        ):
            main()
        assert excinfo.value.code == 2
        assert "unknown agent 'nonexistent-agent'" in capsys.readouterr().err
        mock_run_agent.assert_not_called()


class TestCmdSessions:
    """Tests for the 'sessions' subcommand (list and --rm)."""

    def _home(self, tmp_path, monkeypatch):
        # cmd_sessions computes BASE_STATE_DIR from Path.home()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        state_dir = tmp_path / ".config" / "container-agents" / "pi"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir

    def _fake_subprocess(self, monkeypatch, calls):
        monkeypatch.setattr(
            "agent_pod.cli.subprocess.run",
            lambda *a, **k: calls.append(a[0]) or MagicMock(stdout="", returncode=0, stderr=""),
        )

    def test_list_shows_default_and_named_sessions(self, tmp_path, monkeypatch, capsys):
        state_dir = self._home(tmp_path, monkeypatch)
        (state_dir / "trust.json").write_text("{}\n")  # triggers "default" detection
        (state_dir / "dev").mkdir(parents=True)
        self._fake_subprocess(monkeypatch, [])

        cmd_sessions(Namespace(agent="pi", rm=None))
        out = capsys.readouterr().out
        assert "default" in out
        assert "dev" in out

    def test_list_reports_status_from_podman_ps(self, tmp_path, monkeypatch, capsys):
        state_dir = self._home(tmp_path, monkeypatch)
        (state_dir / "trust.json").write_text("{}\n")
        (state_dir / "dev").mkdir(parents=True)

        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            # Only the default instance appears in `podman ps` output -> dev is stopped
            return MagicMock(
                stdout="pi-sandbox-instance\tUp 3 hours\n",
                returncode=0,
                stderr="",
            )

        monkeypatch.setattr("agent_pod.cli.subprocess.run", fake_run)
        cmd_sessions(Namespace(agent="pi", rm=None))
        out = capsys.readouterr().out
        assert "Up 3 hours" in out  # default marked Running
        assert "stopped" in out  # dev has no matching ps line
        # One podman ps lookup per detected session (default + dev).
        podman_calls = [c for c in calls if c[0] == "podman"]
        assert len(podman_calls) == 2
        assert all(c[0] == "podman" and c[1] == "ps" for c in podman_calls)

    @pytest.mark.parametrize(
        "bad",
        ["../pi2", "/tmp/evil", "a/b", "a\\b", "..", ".", "a b", "a\tb"],
    )
    def test_rm_rejects_unsafe_session_names(self, tmp_path, monkeypatch, capsys, bad):
        state_dir = self._home(tmp_path, monkeypatch)
        (state_dir / "trust.json").write_text("{}\n")
        victim = tmp_path / ".config" / "container-agents" / "pi2"
        victim.mkdir(parents=True)
        (victim / "secret.json").write_text("keep")

        with pytest.raises(SystemExit) as excinfo:
            cmd_sessions(Namespace(agent="pi", rm=bad))
        assert excinfo.value.code == 2
        assert "invalid session name" in capsys.readouterr().err
        # No session state was removed for the unsafe name.
        assert (state_dir / "trust.json").exists()
        assert (victim / "secret.json").read_text() == "keep"

    def test_rm_named_session_removes_state_and_volumes(self, tmp_path, monkeypatch, capsys):
        state_dir = self._home(tmp_path, monkeypatch) / "dev"
        (state_dir / "sessions").mkdir(parents=True)
        (state_dir / "trust.json").write_text("{}\n")

        calls = []
        self._fake_subprocess(monkeypatch, calls)
        cmd_sessions(Namespace(agent="pi", rm="dev"))
        out = capsys.readouterr().out
        assert "Removed session 'dev'" in out
        # Named session state dir is removed wholesale
        assert not state_dir.exists()
        # podman rm -f instance was invoked
        assert ["podman", "rm", "-f", "pi-sandbox-instance-dev"] in calls
        assert not any(c[0] == "podman" and c[1] == "volume" for c in calls)

    def test_rm_leaves_repo_git_alone(self, tmp_path, monkeypatch, capsys):
        """Session git history lives in the repo's .git (owned by the container);
        `sessions --rm` cleans container + state only, no host-side git calls."""
        state_dir = self._home(tmp_path, monkeypatch)
        (state_dir / "dev").mkdir(parents=True)
        (state_dir / "dev" / "trust.json").write_text("{}\n")

        calls = []
        self._fake_subprocess(monkeypatch, calls)
        cmd_sessions(Namespace(agent="pi", rm="dev"))
        out = capsys.readouterr().out
        assert "Removed session 'dev'" in out
        assert not (state_dir / "dev").exists()
        # No git subprocess calls: the session's history is untouched on the host.
        assert not any(c[0] == "git" for c in calls), calls

    def test_rm_default_removes_individual_files(self, tmp_path, monkeypatch, capsys):
        state_dir = self._home(tmp_path, monkeypatch)
        (state_dir / "trust.json").write_text("{}\n")
        (state_dir / "sessions").mkdir(parents=True)
        (state_dir / ".gitconfig").write_text("[safe]\n")

        calls = []
        self._fake_subprocess(monkeypatch, calls)
        cmd_sessions(Namespace(agent="pi", rm="default"))
        out = capsys.readouterr().out
        assert "Removed session 'default'" in out
        # Persisted files, persistent dirs, and gitconfig removed individually
        assert not (state_dir / "trust.json").exists()
        assert not (state_dir / "sessions").exists()
        assert not (state_dir / ".gitconfig").exists()
        # podman rm -f for the default instance, no volume cleanup.
        assert ["podman", "rm", "-f", "pi-sandbox-instance"] in calls
        assert not any(c[0] == "podman" and c[1] == "volume" for c in calls)


class _TtyStdin:
    """Fake stdin whose isatty() reports True (interactive terminal)."""

    def isatty(self) -> bool:
        return True


def _feed_input(monkeypatch, *answers):
    """Mock input(); EOF (Ctrl-D) once the canned answers run out."""
    it = iter(answers)

    def _input(*a):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", _input)


class TestInitSubcommand:
    @pytest.fixture
    def isolated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return tmp_path

    def test_init_writes_project_config(self, isolated, monkeypatch, capsys):
        _feed_input(monkeypatch, "project", "pi", "", "")
        with patch.object(sys, "argv", ["ap", "init"]):
            main()
        cfg = isolated / ".agent-pod.yaml"
        assert cfg.exists()
        assert yaml.safe_load(cfg.read_text()) == {
            "agent": "pi",
            "context_files": [],
            "extra_packages": ["git", "bash"],
        }
        assert "Created config" in capsys.readouterr().out

    def test_init_target_global_writes_global_config(self, isolated, monkeypatch):
        _feed_input(monkeypatch, "", "pi", "", "")
        with patch.object(sys, "argv", ["ap", "init", "--target", "global"]):
            main()
        cfg = isolated / ".config" / "container-agents" / ".agent-pod.yaml"
        assert cfg.exists()
        assert yaml.safe_load(cfg.read_text()) == {
            "agent": "pi",
            "context_files": [],
            "extra_packages": ["git", "bash"],
        }

    def test_init_refuses_overwrite_without_force(self, isolated, monkeypatch, capsys):
        (isolated / ".agent-pod.yaml").write_text("agent: claude\n")
        _feed_input(monkeypatch, "project")
        with patch.object(sys, "argv", ["ap", "init"]):
            main()
        assert yaml.safe_load((isolated / ".agent-pod.yaml").read_text())["agent"] == "claude"
        assert "already exists" in capsys.readouterr().err


class TestRunAutoInit:
    @pytest.fixture
    def no_config_env(self, tmp_path, monkeypatch):
        """Home and cwd with no user config on any level."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr("agent_pod.config.init.sys.stdin", _TtyStdin())
        return tmp_path

    @patch("agent_pod.cli.run_agent")
    def test_run_auto_inits_when_no_config(self, mock_run_agent, no_config_env, monkeypatch):
        _feed_input(monkeypatch, "project", "opencode", "", "")
        with patch.object(sys, "argv", ["ap", "run"]):
            main()
        cfg = no_config_env / ".agent-pod.yaml"
        assert cfg.exists()
        assert yaml.safe_load(cfg.read_text())["agent"] == "opencode"
        args, _ = mock_run_agent.call_args
        # The wizard's chosen agent flows through to the sandbox launch.
        assert args[0] == "opencode"

    @patch("agent_pod.cli.humanized_id", return_value="crisp-lamp")
    @patch("agent_pod.cli.run_agent")
    def test_run_uses_agent_flag_as_wizard_hint(
        self, mock_run_agent, mock_humanized, no_config_env, monkeypatch
    ):
        _feed_input(monkeypatch, "project", "", "", "")
        with patch.object(sys, "argv", ["ap", "run", "--agent", "claude"]):
            main()
        cfg = no_config_env / ".agent-pod.yaml"
        data = yaml.safe_load(cfg.read_text())
        # Agent default came from the CLI hint; context_files/extra_packages answered.
        assert data == {
            "agent": "claude",
            "context_files": [],
            "extra_packages": ["git", "bash"],
        }
        args, _ = mock_run_agent.call_args
        assert args[0] == "claude"
        _, kwargs = mock_run_agent.call_args
        assert kwargs["session"] == "crisp-lamp"


class TestRunProfiles:
    """Profiles as the positional: auto sessions and run-level overrides. The
    harness comes from the profile's `agent` (else config default), overridable
    with `--agent`."""

    def _write_config(self, tmp_path, text):
        (tmp_path / ".agent-pod.yaml").write_text(text)
        return tmp_path

    @patch("agent_pod.cli.humanized_id", return_value="crisp-lamp")
    @patch("agent_pod.cli.run_agent")
    def test_default_profile_resolves_agent(
        self, mock_run_agent, mock_humanized, tmp_path, monkeypatch
    ):
        """`.agent-pod.yaml` profile-centric shape: `profile: default` + a
        `profiles.default` block carrying the agent — `ap run` gets the agent
        from the active profile, not the top level."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        self._write_config(
            tmp_path,
            "profile: default\n"
            "profiles:\n"
            "  default:\n"
            "    agent: pi\n"
            "ephemeral: false\nextra_packages: [uv]\n",
        )
        with patch.object(sys, "argv", ["ap", "run"]):
            main()
        args, kwargs = mock_run_agent.call_args
        assert args[0] == "pi"
        assert kwargs["profile"] == "default"
        assert kwargs["session"] == "crisp-lamp"
        # Everything config-driven rides on the resolved profile config: top-level
        # `ephemeral: false` and `extra_packages` with the profile's `agent`.
        eff = kwargs["user_cfg"]
        assert eff.agent == "pi"
        assert eff.ephemeral is False
        assert eff.extra_packages == ["uv"]
        assert "ephemeral" not in kwargs

    @patch("agent_pod.cli.humanized_id", return_value="crisp-lamp")
    @patch("agent_pod.cli.run_agent")
    def test_profile_auto_session_sets_state(
        self, mock_run_agent, mock_humanized, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        self._write_config(
            tmp_path, "profiles:\n  fixes:\n    agent: pi\n    extra_args: [--fast]\n"
        )
        with patch.object(sys, "argv", ["ap", "run", "fixes"]):
            main()
        args, kwargs = mock_run_agent.call_args
        # Profile drives the branch namespace + overrides; the auto session is a
        # fresh humanized id, so two runs of the profile never collide.
        assert args[0] == "pi"
        assert args[1] == ["--fast"]
        assert kwargs["session"] == "crisp-lamp"
        assert kwargs["profile"] == "fixes"

    @patch("agent_pod.cli.humanized_id", return_value="crisp-lamp")
    @patch("agent_pod.cli.run_agent")
    def test_config_default_profile_used_without_flags(
        self, mock_run_agent, mock_humanized, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        self._write_config(tmp_path, "profile: chores\nprofiles:\n  chores:\n    agent: opencode\n")
        with patch.object(sys, "argv", ["ap", "run"]):
            main()
        args, kwargs = mock_run_agent.call_args
        assert args[0] == "opencode"
        assert kwargs["session"] == "crisp-lamp"
        assert kwargs["profile"] == "chores"

    @patch("agent_pod.cli.humanized_id", return_value="crisp-lamp")
    @patch("agent_pod.cli.run_agent")
    def test_agent_flag_overrides_profile_agent(
        self, mock_run_agent, mock_humanized, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        self._write_config(tmp_path, "profiles:\n  fixes:\n    agent: pi\n")
        with patch.object(sys, "argv", ["ap", "run", "fixes", "--agent", "claude"]):
            main()
        args, kwargs = mock_run_agent.call_args
        # The explicit --agent beats the profile's agent; profile overrides remain.
        assert args[0] == "claude"
        assert kwargs["session"] == "crisp-lamp"
        assert kwargs["profile"] == "fixes"

    @patch("agent_pod.cli.humanized_id", return_value="crisp-lamp")
    @patch("agent_pod.cli.run_agent")
    def test_shell_profile_sets_bash_and_session(
        self, mock_run_agent, mock_humanized, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        self._write_config(tmp_path, "profiles:\n  fixes:\n    agent: pi\n")
        with patch.object(sys, "argv", ["ap", "shell", "fixes"]):
            main()
        args, kwargs = mock_run_agent.call_args
        assert args[0] == "pi"
        assert kwargs["session"] == "crisp-lamp"
        assert kwargs["profile"] == "fixes"
        assert kwargs["use_bash"] is True

    @patch("agent_pod.cli.run_agent")
    def test_plan_profile_positional_and_agent_flag(
        self, mock_run_agent, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        self._write_config(tmp_path, "profiles:\n  fixes:\n    agent: pi\n")
        with patch.object(sys, "argv", ["ap", "plan", "fixes"]):
            main()
        out = capsys.readouterr().out
        assert "pi" in out
        assert "session: fixes" in out

    @patch("agent_pod.cli.run_agent")
    def test_profile_files_merged_and_flow_to_runner(self, mock_run_agent, tmp_path, monkeypatch):
        """A profile's `files` are appended after the top-level defaults on the
        resolved config `run_agent` receives (which `get_effective_agent_config`
        mounts once — no separate slice, so top-level files aren't duplicated)."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        self._write_config(
            tmp_path,
            "files:\n"
            "  - source: ./base.md\n"
            "    name: base.md\n"
            "    permissions: ro\n"
            "profiles:\n"
            "  skills:\n"
            "    agent: pi\n"
            "    files:\n"
            "      - source: ~/.agent/skills\n"
            "        name: skills\n"
            "        permissions: rw\n"
            "        seed: true\n",
        )
        with patch.object(sys, "argv", ["ap", "run", "skills"]):
            main()
        _, kwargs = mock_run_agent.call_args
        eff = kwargs["user_cfg"]
        # Top-level files first, the profile's appended after, exactly once each.
        assert [f.name for f in eff.files] == ["base.md", "skills"]
        assert eff.files[0].name == "base.md"
        assert eff.files[1] == FileMount(
            source="~/.agent/skills", name="skills", permissions="rw", seed=True
        )

    @patch("agent_pod.cli.run_agent")
    def test_explicit_session_keeps_legacy_path(self, mock_run_agent, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        self._write_config(tmp_path, "profiles:\n  fixes:\n    agent: pi\n")
        with patch.object(sys, "argv", ["ap", "run", "fixes", "--session", "dev"]):
            main()
        _, kwargs = mock_run_agent.call_args
        assert kwargs["session"] == "dev"

    def test_unknown_profile_exits(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        self._write_config(tmp_path, "profiles:\n  fixes:\n    agent: pi\n")
        with (
            patch.object(sys, "argv", ["ap", "run", "nope"]),
            pytest.raises(SystemExit) as excinfo,
        ):
            main()
        assert excinfo.value.code == 2
        assert "unknown profile" in capsys.readouterr().err
