---
title: Persist state with a session
---

# Persist state with a session

**Follow the [profiles tutorial](profiles.md) first** — sessions build on
running a profile.

Each run gets a fresh humanized session name (`crisp-lamp`, ...) and its own
isolated state. Pass `--session` to keep that state across runs — for parallel
work or to resume later:

```sh title="Named session"
ap run fixes --session dev
```

An explicit session maps to a stable branch, so a later `ap run fixes
--session dev` checks the same branch back out and continues where you left.

## Next

You've now run a sandboxed agent end to end. From here:

- [**Config**](../guides/config.md) — configure mounts, git sessions, and
  skills for real work.
- [**Git sessions**](../explanation/git-sessions.md) — how the session state
  and git branches fit together.
