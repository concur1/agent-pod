---
title: How to give an agent skills
---

# How to give an agent skills

Any skill you drop into `~/.agent/skills/<name>/SKILL.md` on the host is
discovered by the sandboxed agent — no rebuild, no stale seeded copy. In addition,
agent-pod's bundled `agent-pod-config` skill (how to write `.agent-pod.yaml`) is
generated and mounted on every run (`builtin:agent-pod-config`), and for ephemeral
git runs the `ephemeral-git-workflow` skill is generated and mounted on demand
(`builtin:ephemeral-git-workflow`), even without a host skills dir. See
[Skills, mounted not copied](../explanation/architecture.md) for how the mount
works.

For a *writable* skills workspace (agents that author their own skills), the
[supporting recipe](recipes.md) mounts a seeded copy into session state
instead, so author edits persist without ever touching the host dir.
