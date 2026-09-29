---
title: Quickstart
---

# Quickstart

**Installed agent-pod? Follow the
[how-to install](../guides/install.md) first, then pick up here.**

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

## Next

[Use a profile](profiles.md) — why `ap run fixes` launches something different
to plain `ap run`.
