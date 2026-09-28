---
title: Tutorials
---

# Tutorials

Learn agent-pod by doing. This walkthrough assumes nothing beyond the
[requirements](index.md#requirements); by the end you'll have run an agent,
used a profile, and persisted a session.

## Install agent-pod

[Install](guides.md#install-agent-pod) agent-pod first, then come back here.

## Run your first agent

Launch the default agent (pi) under the default profile:

```sh title="First run"
ap run
```

On the very first run there is no config anywhere, so `ap` walks you through
`ap init` before launching the sandbox:

!!! note "First run"

    If no config file exists on any level, `ap run` starts the wizard
    automatically — answer a few questions and the sandbox launches with a
    generated config.

`ap run` builds a disposable container image, mounts your repository, and
starts the agent inside. When the agent exits, the container is removed —
nothing is left behind.

## Poke around with `ap shell`

Bash out of any agent run to explore the sandbox yourself:

```sh title="Interactive shell"
ap shell
```

It's the same build, but the entrypoint is an interactive bash shell instead
of the agent. `ap shell` takes an optional profile positional, just like
`ap run`.

## Use a profile

A **profile** is a named bundle of overrides — a different agent, extra
flags, different file mounts. The `default` profile is active unless you name
one:

```sh title="Run a profile"
ap run fixes
```

The harness agent comes from the profile's `agent` (else the config's
`agent`), so `ap run fixes` may launch a completely different tool than plain
`ap run`. Force the harness with `--agent`:

```sh title="Override the harness"
ap run fixes --agent pi
```

See which profiles exist and what each one overrides:

```sh title="List profiles"
ap list
```

## Persist state with a session

Each run gets a fresh humanized session name (`crisp-lamp`, ...) and its own
isolated state. Pass `--session` to keep that state across runs — for parallel
work or to resume later:

```sh title="Named session"
ap run fixes --session dev
```

An explicit session maps to a stable branch, so a later `ap run fixes
--session dev` checks the same branch back out and continues where you left.

## Launch flags you'll meet

```sh
ap run fixes                                        # (1)!
ap run fixes --agent pi                             # (2)!
ap run fixes --session dev                          # (3)!
ap run fixes --settings-file ./settings.json        # (4)!
ap run fixes --context-file ./docs/notes.md --context-file ./docs/api.md:api.md  # (5)!
```

1. Run the `fixes` profile.
2. Force the harness agent regardless of the profile's `agent`.
3. Persist state under the explicit session `dev`.
4. Bake pi settings (incl. its `packages` list) into the sandbox image.
5. Mount extra context files into the agent, `@`-referenced in its
   instructions. Repeatable.

## Next steps

- [How-to guides](guides.md) — configure profiles, mounts, and git sessions.
- [Reference](reference.md) — every command, option, and config key.
- [Explanation](explanation.md) — how sessions and worktrees fit together.
