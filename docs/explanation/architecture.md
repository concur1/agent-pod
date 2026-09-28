---
title: Architecture
---

# Architecture

Skills, profiles, and config merging — the design decisions beyond the core
model.

## Skills, mounted not copied

Each agent's global skills dir (`~/.pi/agent/skills/`,
`~/.config/opencode/skills/`, `~/.claude/skills/`) is declared in the agent's
`files` list, with your **global, cross-platform skills directory**
`~/.agent/skills/` (portable `<name>/SKILL.md` folders) mounted **read-only**
into it. Because it's a live mount rather than a seeded copy, any skill you
drop in on the host is discovered by the sandboxed agent with no rebuild and
no stale copy. The entry is `optional`, so it is skipped silently when the
host dir is absent, and the shared git-workflow skill is always mounted via
the `builtin:git-workflow` file entry, so it works even without a host skills
dir present.

For a *writable* skills workspace (agents that author their own skills), the
[supporting recipe](../guides/recipes.md) mounts a seeded copy into
session state instead, so author edits persist without ever touching the host
dir.

## Profiles are overlays

A profile is not a separate config — it's an overlay on top of the top-level
config. Any option settable at the top level is settable per profile, with
top-level values as the baseline, so a profile is a *delta* rather than a
copy. That keeps the common case (`agent: pi` plus a flag) one line, while
still letting a profile flip a bundled read-only mount to read/write or pin a
different harness.

The one thing still not expressible per profile is container networking —
sandbox egress is all-or-nothing — so "only reach the API endpoint" remains a
natural next step.

## Why config merges the way it does

Config layers merge lowest-to-highest precedence
(`bundled < global < project < CLI flags`) with simple, predictable rules:
dicts merge key-by-key, lists and scalars are replaced, and `files` is
appended. The append-only exception for `files` exists so your mounts add to —
rather than silently drop — the agent's own built-in instruction/skill
mounts. The full rules live in the [config reference](../reference/config.md).
