---
title: Tutorials
---

# Tutorials

Learning by doing — a guided run through the core commands and ideas, no prior
knowledge assumed. Start at the top and work down; each page builds on the one
before.

## Prerequisites

Before you start, make sure you have:

- Python 3.11+
- [Podman](https://podman.io/) — used for all container and volume operations

## The path through

**1. [Install agent-pod](install.md)**

Get the `ap` command on your machine. Takes a minute; nothing about agent-pod
itself happens yet.

**2. [Run your first agent](quickstart.md)**

Launch your first sandboxed agent with `ap run`, poke around with `ap shell`,
and meet the launch flags you'll use every day.

**3. [Use a profile](profiles.md)**

A profile is a named bundle of overrides — a different agent, extra flags,
different mounts. Pick one with `ap run <profile>`.

**4. [Persist state with a session](sessions.md)**

Give a run a stable name with `--session` so its state and git branch survive
across runs.

## Next steps

Finished the tutorial? The [**how-to guides**](../guides/) are task recipes for
real work; the [**explanation**](../explanation/) covers how it all fits
together.
