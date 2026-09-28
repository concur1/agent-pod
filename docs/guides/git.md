---
title: Git work
---

# Git work

For git repos, agent-pod can keep the agent on its own private branch so your
`main` and working tree are never touched. Enable it in the config:

```yaml title=".agent-pod.yaml"
ephemeral: true     # (1)!
```

1. Requires being inside a git repo with at least one commit.

The agent then commits to `agent/<profile>/<session>` inside the sandbox, and
**only committed files ever reach the host**. To fold a session's work back in,
merge its branch on the host:

```sh
git merge agent/fixes/dev
```

See [Git sessions](../explanation/git-sessions.md) for exactly how the two
modes work — and why only committed files ever reach the host in ephemeral
mode.
