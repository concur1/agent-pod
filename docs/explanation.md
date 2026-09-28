---
title: Explanation
---

# Explanation

The big picture: how agent-pod fits together, and why the design is the way it
is. For commands and config keys, see the [reference](reference.md).

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

### The worktree lifecycle

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

### Git identity inside the sandbox

The runtime `.gitconfig` is seeded per session from your host git identity
(`git config --global user.name`/`user.email`, honoring `[include]`), falling
back to the image default, so commits in the container work off the shelf. It
is bind-mounted into the container at `/root/.gitconfig`, which means
`git config --global` can't rewrite it in place (rename onto a mounted file
fails with "Device or resource busy") — set additional settings with
repo-local config or environment variables instead.

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
[supporting recipe](guides.md#profile-recipes) mounts a seeded copy into
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
mounts. The full rules live in the [reference](reference.md#precedence).
