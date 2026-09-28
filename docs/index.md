---
title: agent-pod
description: Fast, isolated container sandboxes for AI coding agents, built on Podman.
hide:
  - path
---

# agent-pod

Fast, isolated container sandboxes for AI coding agents, built on **Podman**.

`ap` (short for agent-pod) builds a disposable container image for a supported
coding agent (pi, opencode, claude), wires up persistent state,
mounts your repository and workflow instructions, and launches the agent inside
the sandbox. It cleans up after itself — no stray containers, volumes, or state
left behind.

!!! tip "Start here"

    **New to agent-pod?** Follow the
    [**installation guide**](tutorials/install.md) to get set up, then
    [**run your first agent**](tutorials/quickstart.md) — you'll have a
    sandboxed agent working in minutes. The full
    [**Tutorials**](tutorials/) take you from there.

## What's in these docs

The four quadrants of the [Diátaxis](https://diataxis.fr/) model:

- [**Tutorials**](tutorials/) — learning by doing: install, first run,
  profiles, and sessions, no prior knowledge assumed.
- [**How-to guides**](guides/) — task recipes: configure agent-pod, mount
  files, work in git-heavy repositories, add skills.
- [**Reference**](reference/) — the facts: the command line and the config
  files.
- [**Explanation**](explanation/) — the big picture: how the sandbox, sessions,
  and git worktrees fit together and why it works this way.

## Requirements

- Python 3.11+
- [Podman](https://podman.io/) — used for all container and volume operations
