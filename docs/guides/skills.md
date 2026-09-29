---
title: How to give an agent skills
---

# How to give an agent skills

Any skill you drop into `~/.agent/skills/<name>/SKILL.md` on the host is
discovered by the sandboxed agent — no rebuild, no stale seeded copy. The
shared git-workflow skill is always mounted on demand, even without a host
skills dir. See [Skills, mounted not copied](../explanation/architecture.md)
for how the mount works.

For a *writable* skills workspace (agents that author their own skills), the
[supporting recipe](recipes.md) mounts a seeded copy into session state
instead, so author edits persist without ever touching the host dir.
