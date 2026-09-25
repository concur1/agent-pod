"""Tests for container runner module."""

import os
import signal
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from agent_pod.config import get_agent_config, get_effective_agent_config
from agent_pod.container.cleanup import cleanup_stale_container, container_running
from agent_pod.container.runner import _run_podman, ensure_host_paths, run_agent
from agent_pod.types import FileMount
from agent_pod.utils.names import get_instance_name


def _config_with(agent: str, **updates):
    """Return the bundled agent config with the given fields overridden."""
    return get_effective_agent_config(agent).model_copy(update=updates)


def _with_skills_source(config, host_skills):
    """Point the `skills` file entry's host source at `host_skills`."""
    files = [
        f.model_copy(update={"source": str(host_skills)}) if f.name == "skills" else f
        for f in config.files
    ]
    return config.model_copy(update={"files": files})


def _skills_target(config) -> str:
    return next(config.file_container_path(f) for f in config.files if f.name == "skills")


def _minimal_config(container_name="test", container_home="/test", **updates):
    """A valid flake-based AgentConfig for runner tests that don't exercise builds."""
    return get_effective_agent_config("pi").model_copy(
        update={
            "image_tag": "test:latest",
            "container_name": container_name,
            "container_home": container_home,
            **updates,
        }
    )


def _capture_run(monkeypatch, error=None):
    """Patch run_agent's launch to capture the podman command instead of running it.

    `error`, if given, is raised by the fake launcher (e.g. FileNotFoundError).
    """
    captured = {}

    def fake_run(command, instance_name=None):
        captured["args"] = command
        captured["instance"] = instance_name
        if error is not None:
            raise error
        raise SystemExit(0)

    monkeypatch.setattr("agent_pod.container.runner._run_podman", fake_run)
    return captured


class TestPiGlobalAgentsMd:
    def test_pi_instruction_path_is_global_agents_md(self):
        config = get_agent_config("pi")
        instr = next(f for f in config.files if f.source == "builtin:instructions")
        assert config.file_container_path(instr) == "/root/.pi/agent/AGENTS.md"

    def test_run_agent_pi_mounts_agents_md_and_passes_at_args(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        # podman volume inspect/create calls
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )

        captured = _capture_run(monkeypatch)

        ctx = tmp_path / "ctx.md"
        ctx.write_text("# ctx")

        with pytest.raises(SystemExit):
            run_agent(
                "pi",
                ["hello"],
                context_files=[
                    FileMount(source=str(ctx), name="ctx.md", permissions="ro", context=True)
                ],
            )

        args = captured["args"]
        # Global AGENTS.md is mounted into the container
        assert any(a.endswith("/root/.pi/agent/AGENTS.md:ro,z") for a in args)
        # git-workflow is mounted as a discoverable skill, not a context prompt
        assert any("/root/.pi/agent/skills/git-workflow.md:ro,z" in a for a in args)
        assert not any("/etc/agent-instructions" in a for a in args)
        # Context files are still passed as @ file arguments to pi
        assert "@/root/.config/agent/contexts/ctx.md" in args
        # User args still forwarded after the @ args
        assert args[-1] == "hello"

        # Generated AGENTS.md points at the skill and @-references the context file
        agents_md = tmp_path / "state" / "prompts" / "pi-instructions.md"
        content = agents_md.read_text()
        assert "git-workflow" in content
        assert "/root/.pi/agent/skills/git-workflow.md" in content
        assert "/etc/agent-instructions" not in content
        assert "@/root/.config/agent/contexts/ctx.md" in content

    def test_context_flag_in_files_config_equals_context_files(self, tmp_path, monkeypatch):
        """`context: true` in a config `files` entry behaves like --context-file:
        mounted ro, @-referenced in instructions, passed as a pi @ arg."""
        ctx = tmp_path / "spec.md"
        ctx.write_text("# spec\n")
        config = get_agent_config("pi").model_copy(
            update={
                "files": [
                    *get_agent_config("pi").files,
                    FileMount(source=str(ctx), name="spec.md", permissions="ro", context=True),
                ]
            }
        )
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.get_effective_agent_config", lambda name: config
        )
        captured = _capture_run(monkeypatch)

        with pytest.raises(SystemExit):
            run_agent("pi", ["hello"])

        args = captured["args"]
        assert any(a == f"{ctx}:/root/.config/agent/contexts/spec.md:ro,z" for a in args)
        assert "@/root/.config/agent/contexts/spec.md" in args
        agents_md = (tmp_path / "state" / "prompts" / "pi-instructions.md").read_text()
        assert "@/root/.config/agent/contexts/spec.md" in agents_md

    def test_run_agent_pi_bash_does_not_pass_at_args(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )

        captured = _capture_run(monkeypatch)

        with pytest.raises(SystemExit):
            run_agent("pi", ["hello"], use_bash=True)

        args = captured["args"]
        # In bash mode the @ file args are not appended
        assert "@" not in args
        assert "hello" not in args


class TestOpencodeSkillAndInstructions:
    def test_opencode_instruction_path_is_global_agents_md(self):
        config = get_agent_config("opencode")
        instr = next(f for f in config.files if f.source == "builtin:instructions")
        assert config.file_container_path(instr) == "/root/.config/opencode/AGENTS.md"

    def test_claude_instruction_path_is_user_level(self):
        # User-level ~/.claude/CLAUDE.md auto-loads regardless of where the
        # repo's own CLAUDE.md sits, so it is mounted read-only from the
        # container home.
        config = get_agent_config("claude")
        instr = next(f for f in config.files if f.source == "builtin:instructions")
        assert config.file_container_path(instr) == "/root/.claude/CLAUDE.md"

    def test_run_agent_opencode_mounts_skill_and_agents_md(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )

        captured = _capture_run(monkeypatch)

        with pytest.raises(SystemExit):
            run_agent("opencode", [])

        args = captured["args"]
        # git-workflow skill is mounted into opencode's skills dir as SKILL.md
        assert any(
            a.endswith("/root/.config/opencode/skills/git-workflow/SKILL.md:ro,z") for a in args
        )
        # Global AGENTS.md is mounted for opencode
        assert any(a.endswith("/root/.config/opencode/AGENTS.md:ro,z") for a in args)

        # Generated AGENTS.md points at the opencode skill path
        agents_md = tmp_path / "state" / "prompts" / "opencode-instructions.md"
        content = agents_md.read_text()
        assert "git-workflow" in content
        assert "/root/.config/opencode/skills/git-workflow/SKILL.md" in content


class TestHostSkillsDirPassthrough:
    """The `skills` file entry mounts the host skills dir read-only, when present."""

    def _run(self, tmp_path, monkeypatch, agent="opencode", config=None):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )
        if config is not None:
            monkeypatch.setattr(
                "agent_pod.container.runner.get_effective_agent_config", lambda name: config
            )

        captured = _capture_run(monkeypatch)
        with pytest.raises(SystemExit):
            run_agent(agent, [])
        return captured["args"]

    def test_each_agent_mounts_host_skills_dir_at_its_global_skills_dir(
        self, tmp_path, monkeypatch
    ):
        host_skills = tmp_path / "host-skills"
        (host_skills / "review" / "SKILL.md").parent.mkdir(parents=True)
        (host_skills / "review" / "SKILL.md").write_text("---\nname: review\ndescription: x\n---\n")

        for agent in ("pi", "opencode", "claude"):
            base = get_agent_config(agent)
            config = _with_skills_source(base, host_skills)
            target = _skills_target(config)
            args = self._run(tmp_path, monkeypatch, agent=agent, config=config)
            assert any(a == f"{host_skills}:{target}:ro,z" for a in args), agent

    def test_missing_host_skills_dir_is_not_mounted(self, tmp_path, monkeypatch):
        missing = tmp_path / "does-not-exist"
        config = _with_skills_source(get_agent_config("opencode"), missing)

        args = self._run(tmp_path, monkeypatch, agent="opencode", config=config)
        assert not any("/root/.config/opencode/skills:ro,z" in a for a in args)

    def test_host_skills_dir_mounted_before_git_workflow_file(self, tmp_path, monkeypatch):
        host_skills = tmp_path / "host-skills"
        host_skills.mkdir()
        config = _with_skills_source(get_agent_config("opencode"), host_skills)

        args = self._run(tmp_path, monkeypatch, agent="opencode", config=config)
        # The host skills dir mount precedes the git-workflow file mount so the
        # runner-authoritative git-workflow file wins for that exact path.
        target = _skills_target(config)
        skills_mount = next(i for i, a in enumerate(args) if a == f"{host_skills}:{target}:ro,z")
        git_mount = next(
            i
            for i, a in enumerate(args)
            if a.endswith("/root/.config/opencode/skills/git-workflow/SKILL.md:ro,z")
        )
        assert skills_mount < git_mount


class TestEnvPassthrough:
    def test_only_vars_in_launching_shell_are_forwarded(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )
        # Env passthrough is opt-in; exercise it with a config that declares some.
        cfg = get_effective_agent_config("opencode").model_copy(
            update={
                "passthrough_envs": ["EXAMPLE_TOKEN", "EXAMPLE_SECRET_KEY", "EXAMPLE_PROJECT_ID"]
            }
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.get_effective_agent_config", lambda name: cfg
        )

        captured = _capture_run(monkeypatch)

        # Only the vars present in the launching shell are forwarded.
        monkeypatch.setenv("EXAMPLE_SECRET_KEY", "example-secret")
        monkeypatch.setenv("EXAMPLE_PROJECT_ID", "example-project")
        monkeypatch.delenv("EXAMPLE_TOKEN", raising=False)

        with pytest.raises(SystemExit):
            run_agent("opencode", [])

        passed = {captured["args"][i + 1] for i, a in enumerate(captured["args"]) if a == "-e"}
        assert "EXAMPLE_SECRET_KEY" in passed
        assert "EXAMPLE_PROJECT_ID" in passed
        assert "EXAMPLE_TOKEN" not in passed


class TestOpencodeAuthJson:
    def _run_opencode(self, tmp_path, monkeypatch, config):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.get_effective_agent_config", lambda name: config
        )
        captured = _capture_run(monkeypatch)
        with pytest.raises(SystemExit):
            run_agent("opencode", [])
        return captured["args"]

    def _credential_config(self, host_auth):
        files = [
            f for f in _config_with("opencode").files if not (f.name == "auth.json" and f.secret)
        ]
        files.append(
            FileMount(
                source=str(host_auth),
                name="auth.json",
                target="/root/.local/share/opencode/auth.json",
                permissions="rw",
                seed=True,
                secret=True,
            )
        )
        return _config_with("opencode", files=files)

    def test_seeds_and_mounts_auth_json_from_host(self, tmp_path, monkeypatch):
        host_auth = tmp_path / "host-auth.json"
        host_auth.write_text('{"example": {"type": "api", "key": "k"}}\n')
        config = self._credential_config(host_auth)

        args = self._run_opencode(tmp_path, monkeypatch, config)
        # auth.json is persisted into the state dir and mounted at opencode's path
        auth_state = tmp_path / "state" / "opencode" / "auth.json"
        assert auth_state.exists()
        assert auth_state.read_text() == '{"example": {"type": "api", "key": "k"}}\n'
        assert any(a.endswith("/root/.local/share/opencode/auth.json:rw,z") for a in args)

    def test_empty_host_auth_seeds_empty_state_file(self, tmp_path, monkeypatch):
        # A placeholder host auth is copied through; the state file is still
        # mounted so the agent owns its credential file inside the sandbox.
        host_auth = tmp_path / "host-auth.json"
        host_auth.write_text("{}\n")
        config = self._credential_config(host_auth)

        args = self._run_opencode(tmp_path, monkeypatch, config)
        auth_state = tmp_path / "state" / "opencode" / "auth.json"
        assert auth_state.exists()
        assert auth_state.read_text() == "{}\n"
        assert any(a.endswith("/root/.local/share/opencode/auth.json:rw,z") for a in args)


class TestReadonlyConfigMounts:
    def _run(self, tmp_path, monkeypatch, agent, files):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )
        config = _config_with(agent, files=files)
        monkeypatch.setattr(
            "agent_pod.container.runner.get_effective_agent_config", lambda name: config
        )

        captured = _capture_run(monkeypatch)
        with pytest.raises(SystemExit):
            run_agent(agent, [])
        return captured["args"]

    def test_opencode_mounts_host_config_readonly(self, tmp_path, monkeypatch):
        host_cfg = tmp_path / "opencode.json"
        host_cfg.write_text('{"permission": "allow"}\n')
        args = self._run(
            tmp_path,
            monkeypatch,
            "opencode",
            [
                FileMount(
                    source=str(host_cfg),
                    name="opencode.json",
                    target="/root/.config/opencode/opencode.json",
                    permissions="ro",
                )
            ],
        )
        # Host config is mounted at opencode's path, read-only
        assert any(a == f"{host_cfg}:/root/.config/opencode/opencode.json:ro,z" for a in args)

    def test_opencode_missing_host_config_is_not_mounted(self, tmp_path, monkeypatch):
        missing = tmp_path / "does-not-exist.json"
        args = self._run(
            tmp_path,
            monkeypatch,
            "opencode",
            [
                FileMount(
                    source=str(missing),
                    name="opencode.json",
                    target="/root/.config/opencode/opencode.json",
                    permissions="ro",
                    optional=True,
                )
            ],
        )
        assert not any("/root/.config/opencode/opencode.json" in a for a in args)

    def test_pi_mounts_settings_and_models_readonly(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.json"
        settings.write_text('{"provider": "example"}\n')
        models = tmp_path / "models.json"
        models.write_text("{}\n")
        files = [
            FileMount(source=str(settings), name="settings.json", permissions="ro"),
            FileMount(source=str(models), name="models.json", permissions="ro"),
            FileMount(
                source=str(tmp_path / "models-store.json"),
                name="models-store.json",
                permissions="ro",
                optional=True,
            ),
        ]
        args = self._run(tmp_path, monkeypatch, "pi", files)
        assert any(a == f"{settings}:/root/.pi/agent/settings.json:ro,z" for a in args)
        assert any(a == f"{models}:/root/.pi/agent/models.json:ro,z" for a in args)
        # models-store.json missing on host -> not mounted
        assert not any("/root/.pi/agent/models-store.json" in a for a in args)


class TestRunAgentSessionValidation:
    def _patch_prereqs(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )

    @pytest.mark.parametrize(
        "bad",
        ["../pi2", "/tmp/evil", "a/b", "a\\b", "..", ".", "a b", "a\tb"],
    )
    def test_unsafe_session_name_exits_and_creates_no_state(
        self, tmp_path, monkeypatch, capsys, bad
    ):
        self._patch_prereqs(tmp_path, monkeypatch)
        with pytest.raises(SystemExit) as excinfo:
            run_agent("pi", [], session=bad)
        assert excinfo.value.code == 2
        assert "invalid session name" in capsys.readouterr().err
        # No state dir was created for the unsafe name.
        assert not (tmp_path / "state" / "pi").exists()

    def test_valid_session_name_starts(self, tmp_path, monkeypatch, capsys):
        self._patch_prereqs(tmp_path, monkeypatch)
        captured = _capture_run(monkeypatch)
        with pytest.raises(SystemExit):
            run_agent("pi", [], session="dev")
        # The session flows into the podman args via the instance name and the
        # state-dir mount paths.
        assert captured["instance"] == "pi-sandbox-instance-dev"
        # The session's state mounts point into the per-session state dir.
        state_root = f"{tmp_path / 'state' / 'pi' / 'dev'}/"
        assert any(str(v).startswith(state_root) for v in captured["args"])


class TestGetInstanceName:
    def test_default_session_returns_base_name(self):
        config = _minimal_config(container_name="pi-sandbox-instance")
        assert get_instance_name(config, "default") == "pi-sandbox-instance"

    def test_named_session_appends_suffix(self):
        config = _minimal_config(container_name="pi-sandbox-instance")
        assert get_instance_name(config, "dev") == "pi-sandbox-instance-dev"


class TestEnsureHostPaths:
    def test_creates_directories_and_files(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", state)

        config = _minimal_config(
            files=[
                FileMount(name="settings.json", permissions="rw"),
                FileMount(name="trust.json", permissions="rw"),
                FileMount(name="sessions", permissions="rw"),
            ]
        )
        result = ensure_host_paths("pi", config, session="default")

        assert result == state / "pi"
        assert (state / "pi" / ".gitconfig").exists()
        assert (state / "pi" / "sessions").is_dir()
        assert (state / "pi" / "settings.json").exists()
        assert (state / "pi" / "trust.json").exists()
        # JSON files should contain empty object when not seeded
        assert (state / "pi" / "settings.json").read_text() == "{}\n"

    def test_seeds_host_git_identity(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", state)
        gitconfig = tmp_path / "host-gitconfig"
        gitconfig.write_text("[user]\n\tname = Ada\n\temail = ada@example.com\n")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
        monkeypatch.setenv("HOME", str(tmp_path))

        config = _minimal_config(files=[FileMount(name="x.json", permissions="rw")])
        ensure_host_paths("pi", config)
        content = (state / "pi" / ".gitconfig").read_text()
        assert "[safe]" in content
        assert "name = Ada" in content
        assert "ada@example.com" in content

    def test_seeds_default_git_identity_when_host_unset(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", state)
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "empty"))
        monkeypatch.setenv("HOME", str(tmp_path))

        config = _minimal_config(files=[FileMount(name="x.json", permissions="rw")])
        ensure_host_paths("pi", config)
        content = (state / "pi" / ".gitconfig").read_text()
        assert "agent@localhost" in content

    def test_named_session_creates_nested_dir(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", state)

        config = _minimal_config()
        result = ensure_host_paths("pi", config, session="dev")
        assert result == state / "pi" / "dev"

    def test_idempotent(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", state)

        config = _minimal_config(files=[FileMount(name="x.json", permissions="rw")])
        ensure_host_paths("pi", config)
        # modify the file
        (state / "pi" / "x.json").write_text("changed")
        # second call should not overwrite existing file
        ensure_host_paths("pi", config)
        assert (state / "pi" / "x.json").read_text() == "changed"

    def test_supplied_settings_file_copied_on_new_session(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", state)

        supplied = tmp_path / "supplied-settings.json"
        supplied.write_text('{"packages": ["npm:pi-web-access"]}\n')

        config = _minimal_config(files=[FileMount(name="settings.json", permissions="rw")])
        ensure_host_paths("pi", config, session="default", settings_file=supplied)
        assert (state / "pi" / "settings.json").read_text() == (
            '{"packages": ["npm:pi-web-access"]}\n'
        )

    def test_supplied_settings_file_overrides_default_seed(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", state)
        default_seed = tmp_path / "default.json"
        default_seed.write_text('{"defaultProvider": "host"}\n')

        supplied = tmp_path / "supplied.json"
        supplied.write_text('{"defaultProvider": "supplied"}\n')

        config = _minimal_config(
            files=[
                FileMount(
                    name="settings.json",
                    permissions="rw",
                    source=str(default_seed),
                    seed=True,
                )
            ]
        )
        ensure_host_paths("pi", config, settings_file=supplied)
        assert (state / "pi" / "settings.json").read_text() == ('{"defaultProvider": "supplied"}\n')

    def test_missing_supplied_settings_file_falls_back_to_default_seed(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", state)
        default_seed = tmp_path / "default.json"
        default_seed.write_text('{"defaultProvider": "host"}\n')

        config = _minimal_config(
            files=[
                FileMount(
                    name="settings.json",
                    permissions="rw",
                    source=str(default_seed),
                    seed=True,
                )
            ]
        )
        # Supplied file does not exist -> default seed source is used instead.
        ensure_host_paths("pi", config, settings_file=tmp_path / "nope.json")
        assert (state / "pi" / "settings.json").read_text() == ('{"defaultProvider": "host"}\n')

    def test_supplied_settings_file_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", state)

        supplied = tmp_path / "supplied.json"
        supplied.write_text('{"x": 1}\n')

        config = _minimal_config(files=[FileMount(name="settings.json", permissions="rw")])
        state_dir = state / "pi"
        state_dir.mkdir(parents=True)
        (state_dir / "settings.json").write_text('{"existing": true}\n')
        # Existing session settings are never clobbered, even when a file is supplied.
        ensure_host_paths("pi", config, settings_file=supplied)
        assert (state_dir / "settings.json").read_text() == '{"existing": true}\n'


class TestRunAgentErrorHandling:
    """Tests for the podman launch failure paths in run_agent."""

    def _patch_prereqs(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )

    def test_podman_not_found_exits_with_message(self, tmp_path, monkeypatch, capsys):
        self._patch_prereqs(tmp_path, monkeypatch)
        _capture_run(monkeypatch, error=FileNotFoundError("podman"))
        with pytest.raises(SystemExit) as excinfo:
            run_agent("pi", ["hello"])
        assert excinfo.value.code == 1
        assert "podman" in capsys.readouterr().err.lower()

    def test_generic_exec_error_exits_with_message(self, tmp_path, monkeypatch, capsys):
        self._patch_prereqs(tmp_path, monkeypatch)
        _capture_run(monkeypatch, error=RuntimeError("boom"))
        with pytest.raises(SystemExit) as excinfo:
            run_agent("pi", ["hello"])
        assert excinfo.value.code == 1
        assert "boom" in capsys.readouterr().err

    def test_launch_receives_full_podman_command(self, tmp_path, monkeypatch):
        """Ensure the launcher gets the podman binary and full command list."""
        self._patch_prereqs(tmp_path, monkeypatch)
        captured = _capture_run(monkeypatch)
        with pytest.raises(SystemExit):
            run_agent("pi", ["hello"])
        assert captured["args"][0] == "podman"
        assert "run" in captured["args"]
        assert captured["args"][-1] == "hello"  # user args appended last

    def test_missing_settings_file_warns_and_falls_back(self, tmp_path, monkeypatch, capsys):
        """A missing --settings-file warns on stderr and falls back to default seeding."""
        self._patch_prereqs(tmp_path, monkeypatch)
        captured = _capture_run(monkeypatch)
        with pytest.raises(SystemExit):
            run_agent("pi", ["hello"], settings_file=tmp_path / "nonexistent.json")
        assert "settings file not found" in capsys.readouterr().err.lower()
        assert captured["args"][0] == "podman"


class TestRunAgentDirectWorkspaceFallback:
    """With ephemeral off (or the cwd not a git repo) the agent works directly
    in the mounted /sandbox working tree."""

    def _patch_prereqs(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )

    def test_works_directly_in_sandbox(self, tmp_path, monkeypatch):
        self._patch_prereqs(tmp_path, monkeypatch)
        captured = _capture_run(monkeypatch)
        with pytest.raises(SystemExit):
            run_agent("pi", ["hello"])
        args = captured["args"]
        # Repo is mounted at /sandbox and set as the working dir.
        assert any(":/sandbox:rw,z" in a for a in args)
        assert "-w" in args and args[args.index("-w") + 1] == "/sandbox"
        # No worktree tmpfs or worktree env is passed.
        assert not any(a == "/worktrees" for a in args)
        assert not any("AGENT_WORKTREE_PATH" in a for a in args)


class TestCleanupStaleContainer:
    @patch("agent_pod.container.cleanup.subprocess.run")
    def test_successful_removal(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        cleanup_stale_container("foo-instance")
        mock_run.assert_called_once_with(
            ["podman", "rm", "-f", "foo-instance"],
            capture_output=True,
            text=True,
        )

    @patch("agent_pod.container.cleanup.subprocess.run")
    def test_no_such_container_is_silent(self, mock_run, capsys):
        mock_run.return_value = MagicMock(returncode=1, stderr="Error: no such container\n")
        cleanup_stale_container("foo-instance")
        captured = capsys.readouterr()
        assert captured.err == ""

    @patch("agent_pod.container.cleanup.subprocess.run")
    def test_other_error_prints_warning(self, mock_run, capsys):
        mock_run.return_value = MagicMock(returncode=1, stderr="some other error")
        cleanup_stale_container("foo-instance")
        captured = capsys.readouterr()
        assert "Warning: Failed to clean up" in captured.err
        assert "some other error" in captured.err


class TestContainerRunning:
    @patch("agent_pod.container.cleanup.subprocess.run")
    def test_running_name_is_detected(self, mock_run):
        mock_run.return_value = MagicMock(stdout="foo-instance\nother\n")
        assert container_running("foo-instance") is True

    @patch("agent_pod.container.cleanup.subprocess.run")
    def test_not_running_name_is_false(self, mock_run):
        mock_run.return_value = MagicMock(stdout="foo-instance-deux\n")
        # A substring name must not match the exact container.
        assert container_running("foo-instance") is False

    @patch(
        "agent_pod.container.cleanup.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_missing_podman_is_not_running(self, mock_run):
        assert container_running("foo-instance") is False


class TestRunAgentRefusesLiveSession:
    """A session with a running container must not be force-removed on relaunch;
    launching it again is refused with a clear error instead (concurrent agents
    with the same session name must not kill each other)."""

    def test_refuses_when_session_already_running(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.container_running", lambda name: True)
        mock_build = MagicMock()
        monkeypatch.setattr("agent_pod.container.runner.build_image", mock_build)

        with pytest.raises(SystemExit) as excinfo:
            run_agent("pi", [], session="dev")

        assert excinfo.value.code == 1
        mock_build.assert_not_called()
        captured = capsys.readouterr()
        assert "already running" in captured.err


class TestRunAgentEphemeral:
    """With ephemeral on in a git repo, run_agent mounts the repo's .git so the
    container can create its own per-session worktree on agent/<profile>/<session>.
    Only committed files reach the host; worktree metadata the container wrote into
    .git is pruned on exit, while the session branch stays for review."""

    def _make_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        for cmd in (
            ["git", "-C", str(repo), "init", "-b", "main"],
            ["git", "-C", str(repo), "config", "user.name", "test"],
            ["git", "-C", str(repo), "config", "user.email", "t@t"],
        ):
            subprocess.run(cmd, check=True, capture_output=True)
        (repo / "f.txt").write_text("one\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True
        )
        return repo

    def _patch_prereqs(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        # runner.subprocess.run is intentionally NOT patched: podman never runs
        # (launch is mocked), so the only subprocess calls are the real git ones
        # that read HEAD and prune worktree metadata.

    def test_mounts_git_and_passes_worktree_env(self, tmp_path, monkeypatch):
        repo = self._make_repo(tmp_path)
        self._patch_prereqs(tmp_path, monkeypatch)
        captured = _capture_run(monkeypatch)
        monkeypatch.chdir(repo)

        with pytest.raises(SystemExit):
            run_agent("pi", ["hello"], ephemeral=True, session="crisp-lamp", profile="fixes")

        args = captured["args"]
        # The repo's .git is mounted read-write (the container owns the worktree),
        # not the host working tree.
        assert any(a == f"{repo / '.git'}:/repo/.git:rw,z" for a in args)
        assert not any(a.startswith(f"{repo}:") for a in args)
        # The image entrypoint gets the branch/base/gitdir/worktree it needs.
        envs = {args[i + 1] for i, a in enumerate(args) if a == "-e"}
        assert "AP_REPO_GIT=/repo/.git" in envs
        assert "AP_BRANCH=agent/fixes/crisp-lamp" in envs
        # The worktree lives in a per-session subfolder of /sandbox named after
        # the instance, so concurrent sessions on one repo never collide on a
        # single shared path.
        assert "AP_WORKTREE=/sandbox/pi-sandbox-instance-crisp-lamp" in envs
        # Start in the always-present /sandbox; the entrypoint `cd`s into the
        # per-session worktree after creating it (podman rejects a missing
        # workdir).
        assert args[args.index("-w") + 1] == "/sandbox"
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        assert f"AP_BASE={head}" in envs

    def test_removes_worktree_metadata_on_exit(self, tmp_path, monkeypatch):
        """On exit the host drops this session's own worktree registration
        (whose gitdir points at the container-only /sandbox/<instance> path)
        with a targeted remove, not a blanket prune, so a live session's
        worktree is never yanked out from under it."""
        repo = self._make_repo(tmp_path)
        self._patch_prereqs(tmp_path, monkeypatch)
        calls = []
        real_run = subprocess.run

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return real_run(cmd, **kw)

        monkeypatch.setattr("agent_pod.container.runner.subprocess.run", fake_run)
        monkeypatch.chdir(repo)
        with pytest.raises(SystemExit):
            run_agent("pi", [], ephemeral=True)

        remove = [
            "git",
            "-C",
            str(repo),
            "worktree",
            "remove",
            "--force",
            "/sandbox/pi-sandbox-instance",
        ]
        assert remove in calls
        # No blanket prune that could sweep up another session's live worktree.
        assert ["git", "-C", str(repo), "worktree", "prune"] not in calls

    def test_empty_repo_falls_back_to_direct_mount(self, tmp_path, monkeypatch):
        """A git repo with no commits yet has no HEAD to fork from, so the
        working tree is mounted directly at /sandbox instead."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(
            ["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True
        )
        self._patch_prereqs(tmp_path, monkeypatch)
        captured = _capture_run(monkeypatch)
        monkeypatch.chdir(repo)

        with pytest.raises(SystemExit):
            run_agent("pi", [], ephemeral=True)

        args = captured["args"]
        assert any(a == f"{repo}:/sandbox:rw,z" for a in args)
        assert not any(a.endswith(":/repo/.git:rw,z") for a in args)
        envs = {args[i + 1] for i, a in enumerate(args) if a == "-e"}
        assert not any(e.startswith("AP_BRANCH=") for e in envs)


class TestRunningDirectlyInSandbox:
    def _run(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )
        captured = _capture_run(monkeypatch)
        with pytest.raises(SystemExit):
            run_agent("pi", [])
        return captured["args"]

    def test_repo_mounted_at_sandbox_no_worktree_tmpfs(self, tmp_path, monkeypatch):
        args = self._run(tmp_path, monkeypatch)
        # Repo still mounted at /sandbox
        assert any(a.endswith(":/sandbox:rw,z") for a in args)
        # No worktree tmpfs and no worktree env
        assert not any("--tmpfs" in a and "/worktrees" in a for a in args)
        assert not any("AGENT_WORKTREE_PATH" in a for a in args)
        assert not any(a == "/worktrees" for a in args)


class TestRunPodman:
    """The launcher that runs podman and force-cleans on terminal teardown."""

    def _proc(self, monkeypatch, proc):
        monkeypatch.setattr("agent_pod.container.runner.subprocess.Popen", lambda *a, **k: proc)

    def _fake_subprocess_run(self, monkeypatch, calls):
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0, stderr="")

        monkeypatch.setattr("agent_pod.container.runner.subprocess.run", fake_run)

    def test_propagates_podman_returncode(self, monkeypatch):
        proc = MagicMock()
        proc.wait.return_value = None
        proc.returncode = 7
        self._proc(monkeypatch, proc)

        with pytest.raises(SystemExit) as excinfo:
            _run_podman(["podman", "run", "img"], "inst")
        assert excinfo.value.code == 7

    def test_sighup_force_removes_container(self, monkeypatch):
        """Closing the terminal (e.g. a zellij pane) force-stops and removes the container."""
        proc = MagicMock()
        calls = []

        def fake_wait():
            os.kill(os.getpid(), signal.SIGHUP)
            return None

        proc.wait.side_effect = fake_wait
        proc.returncode = None
        self._proc(monkeypatch, proc)
        self._fake_subprocess_run(monkeypatch, calls)

        with pytest.raises(SystemExit) as excinfo:
            _run_podman(["podman", "run", "img"], "inst")
        assert excinfo.value.code == 128 + signal.SIGHUP
        assert ["podman", "stop", "-t", "0", "--ignore", "inst"] in calls
        assert ["podman", "rm", "-f", "--ignore", "inst"] in calls

    def test_run_command_forces_immediate_stop(self, tmp_path, monkeypatch):
        """--stop-timeout 0 means podman's own stop path kills the container instantly."""
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )
        captured = _capture_run(monkeypatch)
        with pytest.raises(SystemExit):
            run_agent("pi", ["hello"])
        args = captured["args"]
        assert "--stop-timeout" in args
        assert args[args.index("--stop-timeout") + 1] == "0"


class TestLaunchScreen:
    def test_run_prints_the_plan_before_launching(self, tmp_path, monkeypatch, capsys):
        """A launch renders the `ap plan` preview (files/env/security) as the launch
        screen, built from the exact mounts handed to podman."""
        monkeypatch.setattr("agent_pod.container.runner.BASE_STATE_DIR", tmp_path / "state")
        monkeypatch.setattr("agent_pod.container.runner.cleanup_stale_container", lambda name: None)
        monkeypatch.setattr(
            "agent_pod.container.runner.build_image", lambda name, cfg, settings_file=None: None
        )
        monkeypatch.setattr(
            "agent_pod.container.runner.subprocess.run",
            lambda *a, **k: MagicMock(returncode=1, stderr=""),
        )
        captured = _capture_run(monkeypatch)

        with pytest.raises(SystemExit):
            run_agent("pi", ["hello"])

        out = capsys.readouterr().out
        assert "FILESYSTEM ACCESS" in out
        assert "ENVIRONMENT VARIABLES" in out
        assert "NETWORK & CAPABILITIES" in out
        assert "pi  ·  session: default" in out
        assert "hello" in captured["args"]
