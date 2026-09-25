"""Runtime matrix for the nix-in-docker image path (podman-gated).

These tests actually build flake images with `extra_packages` via the real
nix-in-docker pipeline and run smoke checks inside the resulting containers.
They are slow and need network + podman on the host, so they are skipped unless
`AGENT_POD_RUN_MATRIX=1` is set:

    AGENT_POD_RUN_MATRIX=1 uv run pytest tests/test_container/test_runtime_matrix.py -v

The catalog covers the real-world uv/pnpm workflow (the original
`uv run python -h` bug: uv downloads a glibc CPython that execs via the
standard `/lib64/ld-linux-x86-64.so.2` loader, which the flake's fhs-libs shim
provides) plus edge cases (wrappers, relative-symlink bins, multi-call
binaries). Error cases verify the pre-flight rejects unknown/unfree/insecure
attrs with actionable messages instead of a cryptic nix build error.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_pod.container.builder import (
    _check_extra_packages,
    _flake_dir_path,
    _stage_flake_context,
    build_image,
)
from agent_pod.types import AgentConfig, FlakeConfig

REQUIRES_RUNTIME = os.environ.get("AGENT_POD_RUN_MATRIX") == "1"

pytestmark = pytest.mark.skipif(
    not REQUIRES_RUNTIME or shutil.which("podman") is None,
    reason="set AGENT_POD_RUN_MATRIX=1 and have podman on PATH to run the runtime matrix",
)

# One combined image (single nix build) covering the catalog, then each smoke
# command is run in that image.
CATALOG_PACKAGES = ["uv", "nodejs_22", "pnpm", "python311", "jq", "ripgrep", "busybox", "go"]
SMOKE_COMMANDS = [
    ("uv run --no-project python -h", "uv-downloaded CPython via the FHS loader shim"),
    ("pnpm --version", "pnpm wrapper on node on PATH"),
    ("python3.11 -V", "python311 relative-symlink bin"),
    ("jq --version", "simple static-ish binary"),
    ("rg --version", "ripgrep"),
    ("busybox --list", "busybox multi-call binary"),
    ("go version", "go toolchain"),
]

# (extra_packages, expected fragment in the pre-flight error message). The
# insecure path is covered by unit tests (classification -> friendly message);
# real insecure attrs in nixpkgs are removed on EOL and drift, so there is no
# stable name to pin here.
ERROR_CASES = [
    (["unrar"], "allow_unfree"),
    (["nodejs99"], "not in this flake's locked nixpkgs"),
]


def _bundled_flake_dir() -> Path:
    return _flake_dir_path("config/agents/opencode")


def _matrix_config(flake_dir: Path, image_tag: str, extra: list[str]) -> AgentConfig:
    return AgentConfig(
        flake=FlakeConfig(
            dir=str(flake_dir),
            extra_packages=extra,
        ),
        image_tag=image_tag,
        container_name="runtime-matrix",
        container_home="/root",
    )


def _run_in_image(image_tag: str, command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["podman", "run", "--rm", "--entrypoint", "/bin/bash", image_tag, "-lc", command],
        capture_output=True,
        text=True,
    )


def test_loader_shim_present_in_image(monkeypatch, tmp_path):
    tag = "agent-pod/runtime-matrix:shim"
    monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", tmp_path / "cache")
    config = _matrix_config(_bundled_flake_dir(), tag, ["uv"])
    build_image("opencode", config)

    result = _run_in_image(tag, "test -L /lib64/ld-linux-x86-64.so.2")
    assert result.returncode == 0, result.stderr


def test_ok_catalog_runs_in_image(monkeypatch, tmp_path):
    tag = "agent-pod/runtime-matrix:latest"
    monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", tmp_path / "cache")
    config = _matrix_config(_bundled_flake_dir(), tag, CATALOG_PACKAGES)
    build_image("opencode", config)

    for command, label in SMOKE_COMMANDS:
        result = _run_in_image(tag, command)
        assert result.returncode == 0, f"{label} failed: {result.stdout}\n{result.stderr}"


@pytest.mark.parametrize(("extra", "expected"), ERROR_CASES)
def test_preflight_rejects_bad_attrs(tmp_path, capsys, extra, expected):
    ctx = _stage_flake_context(_bundled_flake_dir(), extra)
    try:
        with pytest.raises(SystemExit) as excinfo:
            _check_extra_packages(ctx, extra)
        assert excinfo.value.code == 1
        assert expected in capsys.readouterr().err
    finally:
        shutil.rmtree(ctx, ignore_errors=True)
