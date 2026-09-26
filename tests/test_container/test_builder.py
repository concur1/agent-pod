"""Tests for container builder module."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_pod.container.builder import (
    NIX_STORE_VOLUME,
    _check_extra_packages,
    _friendly_extra_package_error,
    _loaded_image_ref,
    _nix_string,
    _write_extra_packages,
    _write_extra_packages_check,
    _write_flake_config,
    build_image,
    generate_runtime_dockerfile,
)
from agent_pod.types import AgentConfig, FlakeConfig


def _fake_run(calls, load_ref=None):
    """Build a subprocess.run fake returning (fake, dockerfiles).

    Records commands into `calls`; `podman load` reports `load_ref`; `podman
    image exists` returns non-zero so the build never short-circuits on a stale
    hash-skip unless a test overrides `_image_exists`. Dockerfiles passed to
    `podman build -f <tmpfile>` are captured into the returned `dockerfiles`
    list (the temp file is unlinked right after the subprocess returns).
    """
    dockerfiles = []

    def fake(cmd, **kw):
        calls.append(cmd)
        if cmd[:3] == ["podman", "build", "-f"]:
            with open(cmd[3]) as f:
                dockerfiles.append(f.read())
        elif cmd[:2] == ["podman", "load"]:
            out = f"Loaded image: {load_ref}\n" if load_ref else ""
            return MagicMock(returncode=0, stdout=out, stderr="")
        elif cmd[:3] == ["podman", "image", "exists"]:
            return MagicMock(returncode=1)
        if cmd[:2] == ["podman", "run"] and "check-extra-packages.nix" in cmd[-1]:
            # Satisfy the extra_packages pre-flight eval: nothing is flagged.
            for i, v in enumerate(cmd):
                if v == "-v" and cmd[i + 1].endswith(":/out"):
                    host = Path(cmd[i + 1][: -len(":/out")])
                    (host / "extra-packages-check.json").write_text("[]")
        return MagicMock(returncode=0)

    return fake, dockerfiles


def _flake_config(tmp_path, agent="pi", extra=None):
    flake_dir = tmp_path / "flake"
    flake_dir.mkdir()
    (flake_dir / "flake.nix").write_text("{}")
    (flake_dir / "flake.lock").write_text("{}")
    kwargs = {"dir": str(flake_dir)}
    if extra is not None:
        kwargs["extra_packages"] = extra
    return FlakeConfig(**kwargs), flake_dir


class TestWriteExtraPackages:
    def test_writes_generated_extra_packages_nix(self, tmp_path):
        flake_dir = tmp_path / "flake"
        flake_dir.mkdir()
        path = _write_extra_packages(flake_dir, ["uv", "gnumake"])
        content = path.read_text()
        assert path.name == "extra-packages.nix"
        assert "{ pkgs }:" in content
        assert "pkgs.uv" in content
        assert "pkgs.gnumake" in content

    def test_writes_empty_list_for_no_extra_packages(self, tmp_path):
        flake_dir = tmp_path / "flake"
        flake_dir.mkdir()
        path = _write_extra_packages(flake_dir, [])
        assert "{ pkgs }:" in path.read_text()
        assert "pkgs." not in path.read_text()


class TestWriteFlakeConfig:
    def test_writes_empty_config_by_default(self, tmp_path):
        flake_dir = tmp_path / "flake"
        flake_dir.mkdir()
        path = _write_flake_config(flake_dir, allow_unfree=False, permitted_insecure=[])
        assert path.name == "flake-config.nix"
        content = path.read_text()
        # Defaults are omitted so the generated config can never override a
        # flake's own required settings (e.g. claude's allowUnfree).
        assert "allowUnfree" not in content
        assert "permittedInsecurePackages" not in content

    def test_writes_only_non_default_keys(self, tmp_path):
        flake_dir = tmp_path / "flake"
        flake_dir.mkdir()
        path = _write_flake_config(
            flake_dir, allow_unfree=True, permitted_insecure=["openssl-1.1.1w"]
        )
        content = path.read_text()
        assert "allowUnfree = true;" in content
        assert 'permittedInsecurePackages = [ "openssl-1.1.1w" ];' in content


class TestWriteExtraPackagesCheck:
    def test_writes_check_nix_with_names(self, tmp_path):
        flake_dir = tmp_path / "flake"
        flake_dir.mkdir()
        path = _write_extra_packages_check(flake_dir, ["uv", "nodejs_22"])
        content = path.read_text()
        assert path.name == "check-extra-packages.nix"
        assert '"uv" "nodejs_22"' in content
        assert "knownVulnerabilities" in content
        assert "builtins.toJSON" in content

    def test_escapes_nix_special_characters(self):
        assert _nix_string('a"b\\c') == '"a\\"b\\\\c"'


class TestFriendlyExtraPackageError:
    def test_unknown(self):
        msg = _friendly_extra_package_error("foo", "unknown")
        assert "`foo` is not in this flake's locked nixpkgs" in msg
        assert "nix search nixpkgs" in msg

    def test_unfree(self):
        msg = _friendly_extra_package_error("unrar", "unfree")
        assert "`unrar` has an unfree license" in msg
        assert "allow_unfree: true" in msg

    def test_insecure(self):
        msg = _friendly_extra_package_error("openssl-1.1.1w", "insecure")
        assert "`openssl-1.1.1w` has a known vulnerability" in msg
        assert "permitted_insecure" in msg


class TestCheckExtraPackages:
    """Unit tests for the pre-flight extra_packages validation (no podman needed)."""

    def _run(self, monkeypatch, tmp_path, json_text, packages=None):
        import shutil

        from agent_pod.container.builder import _stage_flake_context

        flake_dir = tmp_path / "flake"
        flake_dir.mkdir()
        (flake_dir / "flake.nix").write_text("{}\n")
        (flake_dir / "flake.lock").write_text("{}\n")
        ctx = _stage_flake_context(flake_dir, packages if packages is not None else ["uv"])
        calls = []

        def fake(cmd, **kw):
            calls.append(cmd)
            for i, v in enumerate(cmd):
                if v == "-v" and cmd[i + 1].endswith(":/out"):
                    host = Path(cmd[i + 1][: -len(":/out")])
                    (host / "extra-packages-check.json").write_text(json_text)
            return MagicMock(returncode=0)

        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake)
        try:
            _check_extra_packages(ctx, packages if packages is not None else ["uv"])
        finally:
            shutil.rmtree(ctx, ignore_errors=True)
        return calls

    def test_ok_entries_pass(self, monkeypatch, capsys, tmp_path):
        calls = self._run(monkeypatch, tmp_path, '[{"name": "uv", "status": "ok"}]')
        nix_cmd = calls[0]
        assert nix_cmd[:4] == ["podman", "run", "--rm", "-v"]
        assert f"{NIX_STORE_VOLUME}:/nix" in nix_cmd
        assert "check-extra-packages.nix" in nix_cmd[-1]

    def test_empty_list_skips_podman(self, monkeypatch, tmp_path):
        calls = self._run(monkeypatch, tmp_path, "[]", packages=[])
        # _check_extra_packages returns early for an empty list.
        assert calls == []

    def test_unknown_entry_fails_with_friendly_message(self, monkeypatch, capsys, tmp_path):
        import pytest

        with pytest.raises(SystemExit) as excinfo:
            self._run(
                monkeypatch,
                tmp_path,
                '[{"name": "nope", "status": "unknown"}, {"name": "jq", "status": "ok"}]',
            )
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "`nope` is not in this flake's locked nixpkgs" in err
        # The ok entry is not flagged.
        assert "`jq`" not in err

    def test_unfree_entry_fails_with_friendly_message(self, monkeypatch, capsys, tmp_path):
        import pytest

        with pytest.raises(SystemExit) as excinfo:
            self._run(monkeypatch, tmp_path, '[{"name": "unrar", "status": "unfree"}]')
        assert excinfo.value.code == 1
        assert "allow_unfree: true" in capsys.readouterr().err

    def test_insecure_entry_fails_with_friendly_message(self, monkeypatch, capsys, tmp_path):
        import pytest

        with pytest.raises(SystemExit) as excinfo:
            self._run(
                monkeypatch,
                tmp_path,
                '[{"name": "openssl-1.1.1w", "status": "insecure"}]',
            )
        assert excinfo.value.code == 1
        assert "permitted_insecure" in capsys.readouterr().err


class TestGenerateRuntimeDockerfile:
    def test_thin_layer_on_flake_image(self):
        df = generate_runtime_dockerfile("opencode")
        assert df.startswith("FROM agent-pod/opencode:spike")
        assert 'ENTRYPOINT ["/usr/local/bin/agent-pod-entrypoint"]' in df
        assert "WORKDIR /sandbox" in df
        assert "git config --global user.name" in df
        # The ephemeral entrypoint forks the session worktree into AP_WORKTREE,
        # a per-session subfolder of /sandbox so concurrent sessions don't clash.
        assert 'worktree add -b "$AP_BRANCH" "$AP_WORKTREE" "$AP_BASE"' in df
        # A resumed run (or one following a crashed same-session run) re-checks
        # the branch out with --force, which clears a stale registration at the
        # same per-session path.
        assert 'worktree add --force "$AP_WORKTREE" "$AP_BRANCH"' in df
        # The environment is NOT in the Dockerfile: no nix tool RUNs, no apt,
        # no /opt staging. The flake's image is the source of truth.
        assert "nix --extra-experimental-features" not in df
        assert "apt-get install" not in df
        assert "/opt/" not in df

    def test_bakes_pi_settings_and_installs_via_stable_cli(self):
        settings = '{"packages": ["npm:@foo/bar", {"source": "git:github.com/u/r"}]}'
        df = generate_runtime_dockerfile("pi", settings_json=settings)
        assert "cat > /root/.pi/agent/settings.json <<'PI_JSON'" in df
        assert "npm:@foo/bar" in df
        # Extensions install via the stable /usr/local/bin/pi symlink the flake ships.
        assert "/usr/local/bin/pi install npm:@foo/bar --approve" in df
        assert "/usr/local/bin/pi install git:github.com/u/r --approve" in df

    def test_no_settings_no_bake(self):
        assert "settings.json" not in generate_runtime_dockerfile("opencode")


class TestLoadedImageRef:
    def test_parses_single_image(self):
        assert _loaded_image_ref("Loaded image: agent-pod/pi:spike\n") == "agent-pod/pi:spike"

    def test_parses_first_of_many(self):
        assert _loaded_image_ref("Loaded image(s): a:1, b:2\n") == "a:1"

    def test_no_match_returns_empty(self):
        assert _loaded_image_ref("nothing loaded") == ""


class TestBuildImage:
    """Tests for the real build_image() subprocess path."""

    def _config(self, tmp_path, agent="pi", extra=None):
        flake_cfg, _ = _flake_config(tmp_path, agent=agent, extra=extra)
        return AgentConfig(
            flake=flake_cfg,
            image_tag=f"localhost/{agent}-sandbox:latest",
            container_name=agent,
            container_home="/root",
        )

    def test_success_normalizes_baked_settings(self, monkeypatch, capsys, tmp_path):
        """Semantically-equal settings serialize to byte-identical baked JSON text."""
        config = self._config(tmp_path, agent="pi")
        monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", tmp_path / "cache")

        # Differently formatted but semantically identical settings files.
        settings_a = '{"packages": ["npm:@foo/bar"]}'
        settings_b = '\n  {  \n  "packages": [\n    "npm:@foo/bar"\n  ]  \n}\n'

        dockers = []
        for content in (settings_a, settings_b):
            sf = tmp_path / "settings.json"
            sf.write_text(content)
            calls = []
            fake_run, dockerfiles = _fake_run(calls, load_ref="agent-pod/pi:spike")
            monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake_run)
            build_image("pi", config, settings_file=sf)
            dockers.append(dockerfiles[0])

        # Both produce the identical canonical baked block -> stable cache key.
        assert dockers[0] == dockers[1]
        assert '  "packages"' in dockers[0]  # canonical 2-space, sorted keys

    def test_failure_exits_with_error(self, monkeypatch, capsys, tmp_path):
        config = self._config(tmp_path, agent="pi")
        monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", tmp_path / "cache")

        def fake(cmd, **kw):
            if cmd[:3] == ["podman", "build", "-f"]:
                return MagicMock(returncode=1)
            if cmd[:2] == ["podman", "load"]:
                return MagicMock(
                    returncode=0, stdout="Loaded image: agent-pod/pi:spike\n", stderr=""
                )
            if cmd[:3] == ["podman", "image", "exists"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake)

        with pytest.raises(SystemExit) as excinfo:
            build_image("pi", config)
        assert excinfo.value.code == 1
        assert "building image" in capsys.readouterr().err

    def test_logged_dockerfile_redacts_baked_settings(self, monkeypatch, capsys, caplog, tmp_path):
        """The generated Dockerfile goes to the -v debug log only, and even there masks
        the baked settings heredoc so secrets don't leak."""
        import logging

        config = self._config(tmp_path, agent="pi")
        monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", tmp_path / "cache")
        calls = []
        fake_run, _ = _fake_run(calls, load_ref="agent-pod/pi:spike")
        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake_run)

        sf = tmp_path / "settings.json"
        sf.write_text('{"apiKey": "sk-secret-123", "packages": []}')
        with caplog.at_level(logging.DEBUG, logger="agent_pod.container.builder"):
            build_image("pi", config, settings_file=sf)

        # Launch screen (stdout) is the plan, not build internals.
        out = capsys.readouterr().out
        assert "Generated Dockerfile" not in out
        assert "FROM agent-pod/pi:spike" not in out
        # Debug log carries the redacted Dockerfile: secrets masked, the rest shown.
        log = caplog.text
        assert "sk-secret-123" not in log
        assert "<redacted>" in log
        assert "FROM agent-pod/pi:spike" in log

    def test_rebuilds_when_image_missing_despite_hash_match(self, monkeypatch, tmp_path):
        cache_dir = tmp_path / "cache"
        monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", cache_dir)
        config = self._config(tmp_path, agent="pi")

        calls = []
        fake_run, _ = _fake_run(calls, load_ref="agent-pod/pi:spike")
        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake_run)

        # First build records the hash with the image present.
        monkeypatch.setattr("agent_pod.container.builder._image_exists", lambda tag: True)
        build_image("pi", config)
        # The image is then gone (e.g. pruned); even though the hash matches the
        # recorded one, the build must run again.
        monkeypatch.setattr("agent_pod.container.builder._image_exists", lambda tag: False)
        build_image("pi", config)
        # Both runs actually invoked the podman build step (the second despite a
        # matching recorded hash).
        assert sum(1 for c in calls if c[:2] == ["podman", "build"]) == 2

    def test_changed_inputs_force_rebuild(self, monkeypatch, tmp_path):
        cache_dir = tmp_path / "cache"
        monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", cache_dir)
        monkeypatch.setattr("agent_pod.container.builder._image_exists", lambda tag: True)
        config = self._config(tmp_path, agent="pi")

        calls = []
        fake_run, _ = _fake_run(calls, load_ref="agent-pod/pi:spike")
        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake_run)

        # First build records the hash with no settings baked.
        build_image("pi", config)
        # A change to the settings content changes the hash and forces a rebuild.
        sf = tmp_path / "settings.json"
        sf.write_text('{"packages": ["npm:@foo/bar"]}')
        build_image("pi", config, settings_file=sf)
        # Both runs invoked the podman build step (the second took the new hash).
        assert sum(1 for c in calls if c[:2] == ["podman", "build"]) == 2

    # ---- Flake path ----

    def test_flake_path_builds_named_volume_nix_image_then_thin_layer(
        self, monkeypatch, capsys, tmp_path
    ):
        """Flake builds run nix-in-docker with a named-volume store, then load the
        image, then podman-build the thin runner layer."""
        flake_cfg, flake_dir = _flake_config(tmp_path, agent="pi", extra=["uv"])
        config = AgentConfig(
            flake=flake_cfg,
            image_tag="localhost/pi-sandbox:latest",
            container_name="pi",
            container_home="/root",
        )
        monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", tmp_path / "cache")
        calls = []
        fake_run, dockerfiles = _fake_run(calls, load_ref="agent-pod/pi:spike")
        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake_run)
        build_image("pi", config)

        # 4 subprocess runs: extra_packages pre-flight check (podman run), nix
        # build (podman run), podman load, thin layer build — asserted structurally
        # below by the per-index content checks, not a raw call count.
        # calls[0] is the extra_packages pre-flight eval.
        assert "check-extra-packages.nix" in calls[0][-1]
        nix_cmd = calls[1]
        assert nix_cmd[:4] == ["podman", "run", "--rm", "-v"]
        # The nix store is a named volume (fast native-fs I/O, not a host bind mount).
        assert f"{NIX_STORE_VOLUME}:/nix" in nix_cmd
        # The flake is mounted read-only at /src from a staged build context
        # (flake.nix + flake.lock + generated extra-packages.nix), not the
        # possibly read-only bundled flake dir directly.
        src_mount = next(v for v in nix_cmd if v.endswith(":/src:ro"))
        assert src_mount != f"{flake_dir}:/src:ro"
        assert Path(src_mount[: -len(":/src:ro")]).name.startswith("agent-pod-flake-")
        script = nix_cmd[-1]
        assert "build /src#image -o /tmp/image" in script
        assert "sandbox false" in script
        # /src is mounted read-only, so the script must not try to write the lock.
        assert "--no-write-lock-file" not in script
        # No per-tool RUNs: the whole environment comes from the flake's image output.
        assert "git" not in script.split("build")[0]

        load_cmd = calls[2]
        assert load_cmd[:3] == ["podman", "load", "-i"]
        assert load_cmd[3].endswith("/image.tar.gz")

        thin_cmd = calls[3]
        assert thin_cmd[0:3] == ["podman", "build", "-f"]
        assert thin_cmd[4:6] == ["-t", config.image_tag]
        assert "--pull=never" in thin_cmd
        # Build context is the staged flake context (same dir mounted at /src).
        assert Path(thin_cmd[-1]).name.startswith("agent-pod-flake-")
        assert len(dockerfiles) == 1
        assert dockerfiles[0].startswith("FROM agent-pod/pi:spike")
        assert 'ENTRYPOINT ["/usr/local/bin/agent-pod-entrypoint"]' in dockerfiles[0]

    def test_flake_path_stages_writable_context_with_extra_packages(
        self, monkeypatch, capsys, tmp_path
    ):
        """The build stages a writable context (flake + generated extra-packages.nix)."""
        flake_cfg, flake_dir = _flake_config(tmp_path, agent="pi", extra=["uv", "gnumake"])
        config = AgentConfig(
            flake=flake_cfg,
            image_tag="localhost/pi-sandbox:latest",
            container_name="pi",
            container_home="/root",
        )
        monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", tmp_path / "cache")
        calls = []
        fake_run, _ = _fake_run(calls, load_ref="agent-pod/pi:spike")
        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake_run)
        build_image("pi", config)

        # The /src mount source is a staged temp context, not the flake dir.
        # calls[0] is the extra_packages pre-flight eval; calls[1] is the nix build.
        nix_cmd = calls[1]
        src_mount = next(v for v in nix_cmd if v.endswith(":/src:ro"))
        assert src_mount != f"{flake_dir}:/src:ro"

    def test_flake_path_stages_generated_config(self, monkeypatch, capsys, tmp_path):
        """allow_unfree/permitted_insecure flow into the staged flake-config.nix."""
        flake_cfg, _ = _flake_config(tmp_path, agent="opencode", extra=["unrar"])
        config = AgentConfig(
            flake=FlakeConfig(
                dir=flake_cfg.dir,
                extra_packages=["unrar"],
                allow_unfree=True,
                permitted_insecure=["openssl-1.1.1w"],
            ),
            image_tag="localhost/opencode-sandbox:latest",
            container_name="oc",
            container_home="/root",
        )
        written: dict[str, str] = {}
        real = _write_flake_config

        def spy(flake_dir, allow_unfree, permitted_insecure):
            path = real(flake_dir, allow_unfree, permitted_insecure)
            written["content"] = path.read_text()
            return path

        monkeypatch.setattr("agent_pod.container.builder._write_flake_config", spy)
        monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", tmp_path / "cache")
        calls = []
        fake_run, _ = _fake_run(calls, load_ref="agent-pod/opencode:spike")
        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake_run)
        build_image("opencode", config)

        assert "allowUnfree = true;" in written["content"]
        assert 'permittedInsecurePackages = [ "openssl-1.1.1w" ];' in written["content"]

    def test_stage_flake_context_copies_flake_and_writes_extra_packages(self, tmp_path):
        import shutil

        from agent_pod.container.builder import _stage_flake_context

        flake_dir = tmp_path / "flake"
        flake_dir.mkdir()
        (flake_dir / "flake.nix").write_text("{}\n")
        (flake_dir / "flake.lock").write_text("{}\n")
        ctx = _stage_flake_context(flake_dir, ["uv", "gnumake"])
        try:
            assert (ctx / "flake.nix").read_text() == "{}\n"
            assert (ctx / "flake.lock").exists()
            content = (ctx / "extra-packages.nix").read_text()
            assert "pkgs.uv" in content
            assert "pkgs.gnumake" in content
            # The original flake dir is left untouched (read-only wheel case).
            assert not (flake_dir / "extra-packages.nix").exists()
        finally:
            shutil.rmtree(ctx, ignore_errors=True)

    def test_stage_flake_context_writes_generated_config(self, tmp_path):
        import shutil

        from agent_pod.container.builder import _stage_flake_context

        flake_dir = tmp_path / "flake"
        flake_dir.mkdir()
        (flake_dir / "flake.nix").write_text("{}\n")
        (flake_dir / "flake.lock").write_text("{}\n")
        ctx = _stage_flake_context(
            flake_dir,
            ["uv"],
            allow_unfree=True,
            permitted_insecure=["openssl-1.1.1w"],
        )
        try:
            config = (ctx / "flake-config.nix").read_text()
            assert "allowUnfree = true;" in config
            assert 'permittedInsecurePackages = [ "openssl-1.1.1w" ];' in config
            # The original flake dir is left untouched.
            assert not (flake_dir / "flake-config.nix").exists()
        finally:
            shutil.rmtree(ctx, ignore_errors=True)

    def test_flake_path_retags_loaded_image_to_canonical_ref(self, monkeypatch, capsys, tmp_path):
        flake_cfg, _ = _flake_config(tmp_path, agent="pi")
        config = AgentConfig(
            flake=flake_cfg,
            image_tag="localhost/pi-sandbox:latest",
            container_name="pi",
            container_home="/root",
        )
        monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", tmp_path / "cache")
        calls = []
        fake_run, _ = _fake_run(calls, load_ref="docker.io/library/custom:latest")
        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake_run)
        build_image("pi", config)

        # The loaded image is normalized to the reference the thin layer FROMs.
        tag_cmd = calls[2]
        assert tag_cmd[:3] == ["podman", "tag", "docker.io/library/custom:latest"]
        assert tag_cmd[3] == "agent-pod/pi:spike"
        assert calls[-1][0:3] == ["podman", "build", "-f"]

    def test_flake_path_skips_build_when_hash_matches(self, monkeypatch, capsys, tmp_path):
        flake_cfg, _ = _flake_config(tmp_path, agent="pi")
        config = AgentConfig(
            flake=flake_cfg,
            image_tag="localhost/pi-sandbox:latest",
            container_name="pi",
            container_home="/root",
        )
        cache_dir = tmp_path / "cache"
        monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", cache_dir)
        monkeypatch.setattr("agent_pod.container.builder._image_exists", lambda tag: True)
        calls = []
        fake_run, _ = _fake_run(calls, load_ref="agent-pod/pi:spike")
        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake_run)
        build_image("pi", config)
        # The second run skipped the actual build steps entirely (only the first
        # invoked the podman build), per the matching hash cache.
        build_image("pi", config)
        assert sum(1 for c in calls if c[:2] == ["podman", "build"]) == 1
        assert "skipping build" in capsys.readouterr().out

    def test_non_pi_agent_skips_pi_settings_bake(self, monkeypatch, capsys, tmp_path):
        """opencode must not get pi packages installed via its own CLI at build time."""
        flake_cfg, _ = _flake_config(tmp_path, agent="opencode")
        config = AgentConfig(
            flake=flake_cfg,
            image_tag="localhost/opencode-sandbox:latest",
            container_name="oc",
            container_home="/root",
        )
        sf = tmp_path / "settings.json"
        sf.write_text('{"packages": ["npm:pi-web-access@0.29.0"]}')

        monkeypatch.setattr("agent_pod.container.builder.CACHE_DIR", tmp_path / "cache")
        calls = []
        fake_run, dockerfiles = _fake_run(calls, load_ref="agent-pod/opencode:spike")
        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", fake_run)
        build_image("opencode", config, settings_file=sf)

        # The pi package list is never baked nor installed via the agent CLI.
        assert len(dockerfiles) == 1
        assert "settings.json" not in dockerfiles[0]
        assert "pi-web-access" not in dockerfiles[0]
        assert "install" not in dockerfiles[0]

    def test_flake_path_missing_podman_reports_clean_error(self, monkeypatch, capsys, tmp_path):
        flake_cfg, _ = _flake_config(tmp_path, agent="pi")
        config = AgentConfig(
            flake=flake_cfg,
            image_tag="localhost/pi-sandbox:latest",
            container_name="pi",
            container_home="/root",
        )

        def raise_not_found(*a, **k):
            raise FileNotFoundError

        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", raise_not_found)

        with pytest.raises(SystemExit) as excinfo:
            build_image("pi", config)
        assert excinfo.value.code == 1
        assert "'podman' was not found on PATH" in capsys.readouterr().err

    def test_flake_path_nix_build_failure_exits(self, monkeypatch, capsys, tmp_path):
        flake_cfg, _ = _flake_config(tmp_path, agent="pi")
        config = AgentConfig(
            flake=flake_cfg,
            image_tag="localhost/pi-sandbox:latest",
            container_name="pi",
            container_home="/root",
        )

        def failing_run(cmd, **kw):
            return MagicMock(returncode=1)

        monkeypatch.setattr("agent_pod.container.builder.subprocess.run", failing_run)

        with pytest.raises(SystemExit) as excinfo:
            build_image("pi", config)
        assert excinfo.value.code == 1
        assert "nix build of the flake image failed" in capsys.readouterr().err
