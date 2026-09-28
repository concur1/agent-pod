---
title: How-to guides
---

# How-to guides

Task-oriented recipes. For the underlying ideas, see
[explanation](explanation.md); for the full set of options and config keys,
see [reference](reference.md).

## Install agent-pod

Requires Python 3.11+ and [Podman](https://podman.io/) — used for all
container and volume operations.

=== "uv tool"

    Install the `ap` (and `agent-pod`) command into a managed environment:

    ```sh
    uv tool install .
    ```

=== "pip"

    Install into your current environment:

    ```sh
    pip install .
    ```

The console command is `ap`; the full `agent-pod` spelling works as an alias.
Default agent configs (and their Nix flakes) ship inside the package, so `ap`
works straight after install — no repo checkout needed.

## Create a config with `ap init`

Rather than hand-writing YAML, let `ap init` generate a config for you. It
asks where to write the file (project or global), then walks through a short
set of questions — the default agent, context files, and extra Nix packages.
Every answer is validated against the config model and re-asked until valid.
The result is a commented file you can extend later.

```sh title="ap init"
ap init                        # (1)!
ap init --target global        # (2)!
ap init --force                # (3)!
```

1. Answer a few questions; writes `./.agent-pod.yaml`.
2. Write to `~/.config/container-agents/config.yaml` instead.
3. Overwrite an existing target instead of refusing.

If no config exists on **any level** (no global file *and* no project file),
`ap run` starts the wizard automatically before launching the sandbox, so the
generated config is ready before the agent starts. In non-interactive contexts
(CI, pipes) it skips the wizard and prints a pointer to `ap init` instead of
silently writing a file.

## Write a config by hand

Config files are optional YAML read from your **global** directory and the
**working directory**, letting you set defaults for run flags and override any
agent setting without editing the bundled agent configs:

- Global: `~/.config/container-agents/config.yaml`
- Project: `.agent-pod.yaml` in the current working directory

For every key, the merge rules, and a fully-annotated example, see [Config
files](reference.md#config-files) in the reference. The
[`agent-pod.example.yaml`](https://github.com/concur1/agent-pod/blob/main/agent-pod.example.yaml)
at the repo root is the pasteable, fully-commented version of the same thing.

## Mount files and context into the agent

Anything the agent should see is declared as a `files:` entry (or via the
`--context-file` shortcut). Context files are mounted read-only and
`@`-referenced in the generated instructions, so they're always present:

```sh title="Context files (repeatable)"
ap run fixes --context-file ./docs/notes.md --context-file ./docs/api.md:api.md
```

`--context-file HOST_PATH[:NAME]` is sugar for a `files:` entry with
`context: true`. For the full `files` schema — permissions, seeding, secrets,
writable state dirs — see [the reference](reference.md#config-files).

## Bake pi settings into the image

Pi settings (including its `packages` list) are baked into the sandbox image
at build time:

```sh title="Settings file"
ap run fixes --settings-file ./settings.json
```

Defaults to `~/.pi/settings.json` if the flag is omitted.

## Work in git repositories

For git repos, agent-pod can keep the agent on its own private branch so your
`main` and working tree are never touched. Enable it in the config:

```yaml title="agent-pod.yaml"
ephemeral: true     # (1)!
```

1. Requires being inside a git repo with at least one commit.

The agent then commits to `agent/<profile>/<session>` inside the sandbox, and
**only committed files ever reach the host**. To fold a session's work back in,
merge its branch on the host:

```sh
git merge agent/fixes/dev
```

See [Ephemeral vs direct](explanation.md#ephemeral-vs-direct) for exactly how
the two modes work.

## Give an agent skills

Any skill you drop into `~/.agent/skills/<name>/SKILL.md` on the host is
discovered by the sandboxed agent — no rebuild, no stale seeded copy. The
shared git-workflow skill is always mounted on demand, even without a host
skills dir.

## Profile recipes

Each profile is an overlay on top of the top-level config. The same file
defines them all — here are a few shapes that work out of the box:

=== "readonly"

    A different (cheaper/reviewer) harness configured for read-only review:

    ```yaml
    profiles:
      readonly:
        agent: pi
    ```

=== "daily"

    A fast loop — trusted repo, auto-commit style:

    ```yaml
    profiles:
      daily:
        agent: pi
        extra_args: ["--no-approval"]
    ```

=== "skills"

    Read/write access to the agent's skills dir via a seeded copy in session
    state:

    ```yaml
    profiles:
      skills:
        agent: pi
        files:
          - source: ~/.agent/skills
            name: skills
            permissions: rw
            seed: true
            description: your skills dir (seeded copy; writes kept in session state)
    ```

=== "grunt"

    A different agent for mechanical tasks (or one pinned to a cheaper model):

    ```yaml
    profiles:
      grunt:
        agent: opencode
        extra_args: ["--model", "fast"]
    ```

=== "audit"

    Mount context docs read-only for review-heavy work:

    ```yaml
    profiles:
      audit:
        agent: claude
        context_files: [docs/spec.md, docs/api.md:api.md]
    ```

`ap list` lists what each profile does — `(active)` marks the config's
`profile:` default, else `default`. Any option settable at the top level is
settable per profile, with top-level values as the baseline; profile `files`
entries append after the top-level user `files`, and a later mount at the same
container path replaces an earlier one — so a profile can flip a bundled
read-only mount to read/write. Profile `files` *source* may be `builtin:`
generators like `builtin:instructions` or `builtin:git-workflow`.

## Contribute

Set up the dev environment and run the checks:

```sh title="Development"
uv sync --group dev        # (1)!
uv run pytest              # (2)!
uv run ruff check .        # (3)!
```

1. Install dev dependencies.
2. Run the test suite.
3. Lint. `uv run ruff check . --fix && uv run ruff format .` auto-formats;
   `uv run ty check` type-checks.

Uses [uv](https://docs.astral.sh/uv/) for dependency management and a
[Nix flake](https://github.com/concur1/agent-pod/blob/main/flake.nix)
(uv2nix) for a reproducible dev environment.
