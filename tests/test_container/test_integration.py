"""End-to-end launch test (podman-gated).

Builds the opencode image from the bundled flake once, then launches a
container at the REAL image entrypoint (runtime-tail.dockerfile's
agent-pod-entrypoint) with a live repo's .git bound read-write and the AP_*
env vars the runner sets. The runtime matrix always overrides the entrypoint
with /bin/bash, so this is the only test that ever executes the generated
entrypoint script — i.e. the only place worktree fork + resume actually run:

    AGENT_POD_RUN_MATRIX=1 uv run pytest tests/test_container/test_integration.py -v

Skipped unless AGENT_POD_RUN_MATRIX=1 and podman is on PATH (needs network:
base image pull + nix build). The agent command is `--help` — non-interactive,
exits immediately after the entrypoint has set the worktree up — so no TTY is
needed.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import agent_pod.container.builder as builder
from agent_pod.container.builder import _flake_dir_path, build_image
from agent_pod.types import AgentConfig, FlakeConfig

REQUIRES_RUNTIME = os.environ.get("AGENT_POD_RUN_MATRIX") == "1"

pytestmark = pytest.mark.skipif(
    not REQUIRES_RUNTIME or shutil.which("podman") is None,
    reason="set AGENT_POD_RUN_MATRIX=1 and have podman on PATH to run the launch integration tests",
)

BRANCH = "agent/test/integration"
WORKTREE = "/sandbox/integration-instance"


@pytest.fixture(scope="module")
def image_tag(tmp_path_factory):
    """Build the image once; repeating build_image is an O(1) hash-cache skip."""
    tag = "agent-pod/integration:latest"
    cache_dir = tmp_path_factory.mktemp("cache")
    orig_cache_dir = builder.CACHE_DIR
    builder.CACHE_DIR = cache_dir
    try:
        config = AgentConfig(
            flake=FlakeConfig(dir=str(_flake_dir_path("config/agents/opencode"))),
            image_tag=tag,
            container_name="integration",
            container_home="/root",
        )
        build_image("opencode", config)
        return tag
    finally:
        builder.CACHE_DIR = orig_cache_dir


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    """Fresh repo with one committed file, exactly like a user's cwd/.git."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "file.txt").write_text("hello")
    _git(repo, "add", "file.txt")
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-m",
            "seed",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


def _launch(
    image_tag: str, repo: Path, *, branch: str = BRANCH, worktree: str = WORKTREE
) -> subprocess.CompletedProcess[str]:
    """Run the container exactly as run_agent does, minus the TTY and plus --help."""
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return subprocess.run(
        [
            "podman",
            "run",
            "--rm",
            "-v",
            f"{repo}/.git:/repo/.git:rw,z",
            "-e",
            f"AP_BRANCH={branch}",
            "-e",
            f"AP_BASE={head}",
            "-e",
            "AP_REPO_GIT=/repo/.git",
            "-e",
            f"AP_WORKTREE={worktree}",
            image_tag,
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )


def _worktrees(repo: Path) -> str:
    return _git(repo, "worktree", "list", "--porcelain").stdout


def test_entrypoint_forks_branch_worktree_from_host_head(image_tag, tmp_path):
    """Executing the real entrypoint materializes the session branch on the host repo."""
    repo = _init_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    result = _launch(image_tag, repo)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    # Branch was forked from AP_BASE (== host HEAD) — no commits happened, so
    # the tip must equal the seed commit.
    assert _git(repo, "rev-parse", f"{BRANCH}^{{commit}}").stdout.strip() == head
    # The worktree is registered in the host .git at the container-only path.
    wt = _worktrees(repo)
    assert f"worktree {WORKTREE}" in wt
    assert f"branch refs/heads/{BRANCH}" in wt


def test_resumed_session_rechecks_existing_branch(image_tag, tmp_path):
    """A crashed-then-relaunched session re-checks its branch out instead of erroring."""
    repo = _init_repo(tmp_path)

    assert _launch(image_tag, repo).returncode == 0, "first launch should fork the branch"
    # Same branch + worktree again (the `worktree add --force` resume path).
    assert _launch(image_tag, repo).returncode == 0, (
        "resume must not fail on the existing registration"
    )
    assert f"branch refs/heads/{BRANCH}" in _worktrees(repo)


def test_non_ephemeral_run_does_not_create_worktree(image_tag, tmp_path):
    """Without AP_BRANCH the entrypoint must not touch the repo's .git at all."""
    repo = _init_repo(tmp_path)

    result = _launch(image_tag, repo, branch="", worktree="/sandbox/plain")
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    # Only the main working tree is listed — no container-path worktree was added.
    assert "worktree /sandbox/plain" not in _worktrees(repo)
