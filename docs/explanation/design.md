---
title: Design
---

# Design

The core model: what agent-pod is for, why the sandbox is disposable, and how
cleanup works.

## What agent-pod is for

Running an AI coding agent safely means isolating it from your machine: it
shouldn't be able to touch your home directory, reach arbitrary host mounts,
or leave stray processes eating memory after you close the terminal. agent-pod
builds a **disposable container image** per run, wires up persistent state and
your repository, launches the agent inside, and removes the container when it
exits — no stray containers, volumes, or state left behind.

Default agent configs (and their Nix flakes) ship *inside the package*, so the
tool works straight after install with no repo checkout needed.

## Disposable, not virtual

Each run is a fresh container come from a cached image. Everything the agent
is allowed to keep — config, skills, session state — is *mounted in*, not
copied into the image. That's what makes teardown trivial: when the run ends,
the container is removed and the mounts (which live in volume/session state)
survive deliberately.

## Terminal-close cleanup

The sandbox container is removed when the agent exits. It is also removed when
the terminal it runs in is closed — including closing a pane/tab in a terminal
multiplexer such as zellij — so a TUI agent's background process can't linger
and keep consuming memory. `ap` traps `SIGHUP` and force-removes the
container (`podman stop -t 0` + `podman rm -f`) instead of relying on `--rm`
alone.
