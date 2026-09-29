---
title: Git sessions
---

# Git sessions

How agent-pod handles your repository — ephemeral sessions vs direct mode.

## Ephemeral vs direct

The `ephemeral` field (default off) selects where the agent works:

- **Direct (`ephemeral: false`, or not a git repo):** your working directory
  is mounted at `/sandbox`, and edits are immediately visible to the host.
- **Ephemeral git sessions (`ephemeral: true`, inside a git repo with at
  least one commit):** `ap` mounts your repo's **`.git` directory** read-write
  at `/repo/.git` — not your working tree. The container's entrypoint then
  creates its own **private per-session worktree** inside the pod
  (`git worktree add` on branch `agent/<profile>/<session>` at `/sandbox`,
  forked from your current HEAD), so the agent's commits land on its own
  branch, never on `main`, and the host checkout is never touched.

Because only `.git` is mounted in the ephemeral mode, **only committed files
ever reach the host**: uncommitted edits, untracked files, and your host's
working tree stay out of the container entirely.

Enable it, and fold a session's branch back in on the host, per the
[How to work in git](../guides/git.md) guide.

## The worktree lifecycle

On exit the host runs a best-effort `git worktree prune` to drop the
container-written worktree metadata from your `.git`; the `agent/` branch
stays behind for review — unless it adds nothing to `main` (a no-op session,
or one whose commits were already folded back), in which case it's pruned
automatically. Each `ap run`/`ap shell` sweeps any leftover `agent/*`
branches that add nothing to `main` before launching, so stragglers from a
crashed or pre-pruning session don't accumulate.

Explicit sessions (`--session dev`) resume by checking the same branch back
out; auto sessions (fresh `adjective-noun` names) each fork their own branch
from your then-current HEAD. The old host-side worktree management
(`ap worktree keep|integrate`) is gone — to fold a session's branch into your
mainline, just `git merge agent/<profile>/<session>` on the host.

## Git identity inside the sandbox

The runtime `.gitconfig` is seeded per session from your host git identity
(`git config --global user.name`/`user.email`, honoring `[include]`), falling
back to the image default, so commits in the container work off the shelf. It
is bind-mounted into the container at `/root/.gitconfig`, which means
`git config --global` can't rewrite it in place (rename onto a mounted file
fails with "Device or resource busy") — set additional settings with
repo-local config or environment variables instead.
