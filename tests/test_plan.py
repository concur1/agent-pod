"""Tests for the `ap plan` permission preview."""

from pathlib import Path

import pytest

from agent_pod.config import get_effective_agent_config
from agent_pod.container.runner import Mount
from agent_pod.plan import EnvVar, Plan, build_plan, render_plan
from agent_pod.types import FileMount, PassthroughEnv


def _envs(*names: str) -> list[PassthroughEnv]:
    """Passthrough env declarations with a generated description per name."""
    return [PassthroughEnv(name=n, description=f"token for {n}") for n in names]


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point home/cwd and the state dir at tmp_path so the plan is deterministic."""
    monkeypatch.setenv("HOME", str(tmp_path))  # so `~`-expansion in mount sources resolves here
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    monkeypatch.setattr(Path, "cwd", lambda: repo)
    monkeypatch.setattr("agent_pod.plan.BASE_STATE_DIR", tmp_path / "state")
    return tmp_path


def _config_with(agent: str, **updates):
    return get_effective_agent_config(agent).model_copy(update=updates)


@pytest.fixture
def passthrough_config(isolated, monkeypatch):
    """Override the effective agent config for the plan's internal lookup."""

    def _apply(agent: str, **updates):
        cfg = _config_with(agent, **updates)
        monkeypatch.setattr("agent_pod.plan.get_effective_agent_config", lambda n, _u=None: cfg)
        return cfg

    return _apply


class TestBuildPlan:
    def test_opencode_mounts_and_modes(self, isolated):
        host_cfg = isolated / ".config" / "opencode" / "opencode.json"
        host_cfg.parent.mkdir(parents=True)
        host_cfg.write_text("{}\n")
        host_auth = isolated / ".local" / "share" / "opencode" / "auth.json"
        host_auth.parent.mkdir(parents=True)
        host_auth.write_text('{"example": {"key": "k"}}\n')

        plan = build_plan(agent="opencode", env={})
        by_kind = {m.kind: m for m in plan.mounts}
        assert by_kind["repo"].mode == "rw"
        assert by_kind["repo"].container_path == "/sandbox"
        assert by_kind["config"].mode == "ro"
        assert by_kind["credential"].mode == "rw"
        assert by_kind["credential"].secret is True
        # opencode's own tmpfs cache mounts.
        assert any(m.tmpfs for m in plan.mounts)

    def test_repo_rw_and_generated_instruction_mounts(self, isolated):
        plan = build_plan(agent="pi", env={})
        kinds = [m.kind for m in plan.mounts]
        assert "repo" in kinds
        assert "instructions" in kinds
        assert "skill" in kinds

    def test_secret_envs_and_credential_are_secrets(self, isolated, passthrough_config):
        host_auth = isolated / ".local" / "share" / "opencode" / "auth.json"
        host_auth.parent.mkdir(parents=True)
        host_auth.write_text('{"example": {"key": "k"}}\n')
        # Env passthrough is opt-in (no defaults); the plan lists what a user
        # explicitly opts into, flagging secrets inline as [secret].
        passthrough_config(
            "opencode",
            passthrough_envs=_envs("OPENAI_API_KEY", "EXAMPLE_TOKEN", "EXAMPLE_PROJECT_ID"),
        )

        plan = build_plan(agent="opencode", env={"OPENAI_API_KEY": "v", "EXAMPLE_PROJECT_ID": "p"})
        out = render_plan(plan, color=False)
        fs = out.split("FILESYSTEM ACCESS")[1].split("ENVIRONMENT VARIABLES")[0]
        env_sec = out.split("ENVIRONMENT VARIABLES")[1].split("NETWORK & CAPABILITIES")[0]

        def _tagged(name):
            return any(
                "[secret]" in line for line in env_sec.splitlines() if line.startswith(f"  {name}")
            )

        # The credential file is flagged [secret] in the filesystem section.
        assert "[secret]" in fs and "auth.json" in fs
        # Secret env vars are flagged; EXAMPLE_PROJECT_ID (an identifier) is not.
        assert _tagged("OPENAI_API_KEY") is True
        assert _tagged("EXAMPLE_TOKEN") is True
        assert _tagged("EXAMPLE_PROJECT_ID") is False

    def test_no_internal_envs_by_default(self, isolated):
        plan = build_plan(agent="pi", env={})
        assert plan.envs == []

    def test_ephemeral_mounts_git_and_internal_envs(self, isolated, monkeypatch):
        import subprocess

        repo = isolated / "repo"
        for cmd in (
            ["git", "-C", str(repo), "init", "-b", "main"],
            ["git", "-C", str(repo), "config", "user.name", "t"],
            ["git", "-C", str(repo), "config", "user.email", "t@t"],
        ):
            subprocess.run(cmd, check=True, capture_output=True)
        (repo / "f").write_text("x\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True
        )

        plan = build_plan(
            agent="pi",
            env={},
            ephemeral=True,
            session="crisp-lamp",
            profile="fixes",
        )
        by_kind = {m.kind: m for m in plan.mounts}
        assert by_kind["repo"].host_path == repo / ".git"
        assert by_kind["repo"].container_path == "/repo/.git"
        internal = {e.name: e for e in plan.envs if e.internal}
        assert set(internal) == {"AP_BRANCH", "AP_BASE", "AP_REPO_GIT", "AP_WORKTREE"}
        # Values never appear in the plan; the entrypoint gets them via podman -e.
        env_section = render_plan(plan, color=False).split("ENVIRONMENT VARIABLES")[1]
        assert "AP_BRANCH" in env_section and "agent/fixes/crisp-lamp" not in env_section

    def test_ephemeral_falls_back_without_git(self, isolated):
        plan = build_plan(agent="pi", env={}, ephemeral=True)
        by_kind = {m.kind: m for m in plan.mounts}
        assert by_kind["repo"].host_path == isolated / "repo"
        assert by_kind["repo"].container_path == "/sandbox"
        assert not any(e.internal for e in plan.envs)

    def test_passthrough_envs_report_forwarded_status(self, isolated, passthrough_config):
        passthrough_config(
            "pi", passthrough_envs=_envs("HF_TOKEN", "EXAMPLE_TOKEN", "OPENAI_API_KEY")
        )
        plan = build_plan(agent="pi", env={"HF_TOKEN": "h", "EXAMPLE_TOKEN": "s"})
        status = {e.name: e.forwarded for e in plan.envs}
        assert status["HF_TOKEN"] is True
        assert status["EXAMPLE_TOKEN"] is True
        # A passthrough var absent from the launching shell is not forwarded.
        assert status["OPENAI_API_KEY"] is False

    def test_no_passthrough_envs_by_default(self, isolated):
        # Bundled agent configs forward nothing by default, so the env section
        # is empty (no internal vars, no secrets).
        plan = build_plan(agent="opencode", env={"OPENAI_API_KEY": "v"})
        assert plan.envs == []
        out = render_plan(plan, color=False)
        env_sec = out.split("ENVIRONMENT VARIABLES")[1].split("NETWORK & CAPABILITIES")[0]
        assert "[secret]" not in env_sec

    def test_context_files_appear_as_readonly_mounts(self, isolated):
        ctx = isolated / "docs" / "notes.md"
        ctx.parent.mkdir(parents=True)
        ctx.write_text("# notes\n")
        plan = build_plan(
            agent="pi",
            context_files=[
                FileMount(source=str(ctx), name="notes.md", permissions="ro", context=True)
            ],
            env={},
        )
        contexts = [m for m in plan.mounts if m.kind == "context"]
        assert len(contexts) == 1
        assert contexts[0].mode == "ro"
        assert contexts[0].container_path == "/root/.config/agent/contexts/notes.md"

    def test_later_mount_at_same_path_replaces_earlier(self, isolated):
        """A profile rw `skills` entry mounted after the bundled ro one wins:
        exactly one mount for the skills path, read/write state copy."""
        rw_skills = FileMount(source="~/.agent/skills", name="skills", permissions="rw", seed=True)
        plan = build_plan(
            agent="pi",
            files=[rw_skills],
            env={},
        )
        skills_mounts = [m for m in plan.mounts if m.container_path == "/root/.pi/agent/skills"]
        assert len(skills_mounts) == 1
        assert skills_mounts[0].mode == "rw"
        assert skills_mounts[0].kind == "state"

    def test_rw_skills_folds_builtin_skill_into_state_dir(self, isolated):
        """No file-under-dir bind survives when a profile replaces the skills dir:
        the builtin git-workflow is folded into the on-disk state dir instead of
        mounting at .../skills/git-workflow.md (which crun rejects)."""
        rw_skills = FileMount(source="~/.agent/skills", name="skills", permissions="rw", seed=True)
        plan = build_plan(agent="pi", files=[rw_skills], env={})
        nested = [m for m in plan.mounts if m.container_path.endswith("skills/git-workflow.md")]
        assert nested == []
        folded = isolated / "state" / "pi" / "skills" / "git-workflow.md"
        assert folded.exists()
        assert "git-workflow" in folded.read_text()

    def test_file_descriptions_rendered_in_plan(self, isolated, passthrough_config):
        extra = isolated / "extra.md"
        extra.write_text("# extra\n")
        passthrough_config(
            "opencode",
            files=[
                FileMount(
                    source=str(extra),
                    name="extra.md",
                    permissions="ro",
                    description="extra reference notes",
                ),
                *get_effective_agent_config("opencode").files,
            ],
        )
        out = render_plan(build_plan(agent="opencode", env={}), color=False)
        # The user-supplied entry shows its host source, container path and description.
        assert "extra reference notes" in out
        assert "~/extra.md" in out
        assert "→ /root/.config/opencode/extra.md" in out


class TestRenderPlan:
    def test_sections_and_plain_output(self, isolated):
        plan = build_plan(agent="pi", env={})
        out = render_plan(plan, color=False)
        assert "FILESYSTEM ACCESS" in out
        assert "ENVIRONMENT VARIABLES" in out
        assert "NETWORK & CAPABILITIES" in out
        assert "read/write" in out
        assert "\033[" not in out

    def test_write_access_is_colored_red(self, isolated):
        plan = build_plan(agent="pi", env={})
        out = render_plan(plan, color=True)
        assert "\033[31mread/write\033[0m" in out

    def test_secret_flag_is_red(self, isolated):
        host_auth = isolated / ".local" / "share" / "opencode" / "auth.json"
        host_auth.parent.mkdir(parents=True)
        host_auth.write_text('{"example": {"key": "k"}}\n')
        plan = build_plan(agent="opencode", env={})
        out = render_plan(plan, color=True)
        assert "\033[31m  [secret]\033[0m" in out

    def test_generated_instructions_describe_sandbox_access(self, isolated, passthrough_config):
        """The generated AGENTS.md lists mounts (secrets flagged), forwarded env
        vars with descriptions, and the network posture — the agent's readable
        picture of what it can touch."""
        host_auth = isolated / ".local" / "share" / "opencode" / "auth.json"
        host_auth.parent.mkdir(parents=True)
        host_auth.write_text('{"example": {"key": "k"}}\n')
        passthrough_config(
            "opencode",
            passthrough_envs=_envs("OPENAI_API_KEY", "EXAMPLE_PROJECT_ID"),
        )

        build_plan(agent="opencode", env={"OPENAI_API_KEY": "v"})
        content = (isolated / "state" / "prompts" / "opencode-instructions.md").read_text()
        assert "Sandbox access" in content
        assert "/sandbox — read/write — Your repository" in content
        assert "auth.json — read/write [secret]" in content
        assert "Full outbound (default bridge) network, host network disabled" in content
        assert "OPENAI_API_KEY [secret] — token for OPENAI_API_KEY" in content
        # A declared env absent from the launching shell is shown as not forwarded.
        missing = "EXAMPLE_PROJECT_ID — token for EXAMPLE_PROJECT_ID (not set — not forwarded)"
        assert missing in content

    def test_env_descriptions_rendered_in_plan(self, isolated, passthrough_config):
        passthrough_config("pi", passthrough_envs=_envs("HF_TOKEN"))
        plan = build_plan(agent="pi", env={"HF_TOKEN": "h"})
        out = render_plan(plan, color=False)
        assert "forwarded (set in this shell)" in out
        assert "· token for HF_TOKEN" in out

    def test_custom_prompt_lands_at_top_of_instructions(self, isolated, passthrough_config):
        passthrough_config(
            "pi",
            prompt=(
                "You are the release engineer. Verify the build before every merge.\n\n"
                "Follow these steps."
            ),
        )
        build_plan(agent="pi", env={})
        content = (isolated / "state" / "prompts" / "pi-instructions.md").read_text()
        assert content.startswith("# Agent instructions")
        prompt_section = content.split("## Version control")[0]
        assert "## Instructions" in prompt_section
        assert "You are the release engineer." in prompt_section
        assert "Verify the build before every merge." in prompt_section
        assert "Follow these steps." in prompt_section

    def test_no_prompt_renders_no_instructions_section(self, isolated, passthrough_config):
        passthrough_config("pi", prompt=None)
        build_plan(agent="pi", env={})
        content = (isolated / "state" / "prompts" / "pi-instructions.md").read_text()
        assert "## Instructions" not in content

    def test_instructions_open_with_environment_section(self, isolated):
        """The generated AGENTS.md opens by describing the sandbox and pointing
        at the detailed environment sections that follow; the version-control
        line just names the skill (no DVCS choice), and an empty context-files
        section is omitted entirely."""
        build_plan(agent="pi", env={})
        content = (isolated / "state" / "prompts" / "pi-instructions.md").read_text()
        assert content.startswith("# Agent instructions")
        head = content.split("## Version control")[0]
        assert "## Environment" in head
        assert "container sandbox" in head
        assert "rest of this file" in head
        vc_line = next(
            line
            for line in content.splitlines()
            if line.startswith("Follow the `git-workflow` skill")
        )
        assert vc_line == "Follow the `git-workflow` skill for all code change operations."
        assert "Context files" not in content

    def test_secret_values_never_leak(self, isolated, passthrough_config):
        secret_value = "super-secret-value-xyz"
        host_auth = isolated / ".local" / "share" / "opencode" / "auth.json"
        host_auth.parent.mkdir(parents=True)
        host_auth.write_text(f'{{"example": {{"key": "{secret_value}"}}}}\n')
        passthrough_config("opencode", passthrough_envs=_envs("EXAMPLE_TOKEN"))
        plan = build_plan(agent="opencode", env={"EXAMPLE_TOKEN": secret_value})
        out = render_plan(plan, color=False)
        assert "[secret]" in out
        assert secret_value not in out
        assert secret_value not in render_plan(plan, color=True)

    def test_broad_readonly_dir_is_colored_red(self, isolated):
        home = Path.home()
        (home / "narrow").mkdir(parents=True)
        (home / "narrow" / "file.txt").write_text("x")
        plan = Plan(
            agent="x",
            session="default",
            mounts=[
                # home itself -> broad read-only -> red
                Mount(host_path=home, container_path="/etc/home", mode="ro", kind="config"),
                # direct child dir of home -> broad -> red
                Mount(
                    host_path=home / "narrow",
                    container_path="/etc/narrow",
                    mode="ro",
                    kind="config",
                ),
                # single file -> narrow -> not red
                Mount(
                    host_path=home / "narrow" / "file.txt",
                    container_path="/etc/file",
                    mode="ro",
                    kind="config",
                ),
            ],
            envs=[EnvVar(name="A", forwarded=False)],
        )
        out = render_plan(plan, color=True)
        assert out.count("\033[31mread-only\033[0m") == 2

    def test_tmpfs_listed_without_host_path(self, isolated):
        plan = build_plan(agent="pi", env={})
        out = render_plan(plan, color=False)
        assert "tmpfs (no host access)" in out
        assert "/tmp" in out

    def test_filesystem_grouped_by_access(self, isolated):
        plan = build_plan(agent="pi", env={})
        fs = (
            render_plan(plan, color=False)
            .split("FILESYSTEM ACCESS")[1]
            .split("ENVIRONMENT VARIABLES")[0]
        )
        lines = [line for line in fs.splitlines() if line.startswith("  read")]
        rw = [i for i, line in enumerate(lines) if line.startswith("  read/write")]
        ro = [i for i, line in enumerate(lines) if line.startswith("  read-only")]
        # Every read/write row precedes every read-only row.
        assert max(rw) < min(ro)

    def test_network_section_truthful_no_restriction(self, isolated):
        plan = build_plan(agent="opencode", env={})
        out = render_plan(plan, color=False)
        assert "NETWORK & CAPABILITIES" in out
        assert "no restriction" in out
        assert "Host Network" in out and "Disabled" in out
        assert "no hardening" in out
