---
name: ephemeral-git-workflow
description: Committing delivery to the host in ephemeral mode, where the sandbox owns a private worktree on the agent/<profile>/<session> branch. Only relevant when ephemeral mode is active.
---

# Ephemeral Git Workflow

This skill applies **only in ephemeral mode** — when the host repo's `.git` is
mounted at `/repo/.git` and `/sandbox` is a private per-session worktree of it,
checked out on `agent/<profile>/<session>` (e.g. `agent/default/crisp-lamp`),
created by the entrypoint when you start. If you are working directly in the
host's tree (ephemeral off), none of this applies — edit and commit as you
normally would.

## Commits are the only way your work reaches the host

Your changes leave the sandbox only as commits on `agent/<profile>/<session>`,
which the host reviews and integrates after the session ends. Uncommitted edits
exist only inside this container and are destroyed when it exits — never treat
the working tree as a source of truth. Committing is therefore **mandatory**:

- Do not ask "want me to commit?" — commit when a change is complete; one task per commit.
- Never call a task done with uncommitted files in the tree: if it isn't committed, the user has not received it.
- Before finishing, run `git status` and confirm the tree is clean and every intended change landed in a commit.

## Workflow

1. Make and commit your changes:
   ```
   git add <files>
   git commit -m "<message>"
   ```
2. Done — keep the branch checked out and the tree clean for the host to
   review. Do not merge or rebase onto `main`.

## Rules

- **Do not push** — there is no SSH/token access in the container; the host
  reviews the `agent/<profile>/<session>` branch.
- **Do not check out `main`/`master`** — stay on your `agent/<profile>/<session>`
  branch.
- Work on one task per commit.
- **Git identity is preset** (seeded from the host), so `git commit` works as
  is. Do not run `git config --global`: `/root/.gitconfig` is bind-mounted and
  cannot be rewritten in place ("Device or resource busy"). Use repository-local
  `git config` or environment variables if you truly need other settings.
- To inspect the host repo from inside the worktree, point git at the mounted
  dir: `git --git-dir=/repo/.git`.

## Quick Reference

| Task | Command |
|---|---|
| Status | `git status` |
| Log | `git log --oneline` |
| Stage | `git add <files>` |
| Commit | `git commit -m "<message>"` |
| Diff | `git diff` |
