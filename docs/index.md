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

    The [tutorial](tutorials.md) gets you running in minutes; the
    [reference](reference.md) describes every command and config key.

## What's in these docs

The four quadrants of the [Diátaxis](https://diataxis.fr/) model:

- [**Tutorials**](tutorials.md) — learning by doing: a guided run through the
  core commands and ideas, no prior knowledge assumed.
- [**How-to guides**](guides.md) — task recipes: install, configure, mount
  files, work in git-heavy repositories.
- [**Reference**](reference.md) — the facts: every command, option, config
  key, and path.
- [**Explanation**](explanation.md) — the big picture: how the sandbox,
  sessions, and git worktrees fit together and why it works this way.

## Requirements

- Python 3.11+
- [Podman](https://podman.io/) — used for all container and volume operations
