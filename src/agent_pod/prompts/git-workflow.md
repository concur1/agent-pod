---
name: git-workflow
description: Version control workflow for sandboxed agents. Use for all git operations, committing work in the container working tree.
---

# Git Workflow

Use `git` for version control.

## Your Environment

- **In a git repository with ephemeral mode enabled (the default):** the host
  repo's `.git` is mounted at `/repo/.git`, and `/sandbox` is a **private
  per-session worktree** of it, checked out on the branch
  `agent/<profile>/<session>` (e.g. `agent/default/crisp-lamp`). The worktree
  and its branch are created inside this container by the entrypoint when you
  start. Uncommitted edits exist only inside this sandbox and are destroyed when
  it exits — never treat the working tree as a source of truth. If you ever need
  to run git outside `/sandbox`, point it at the mounted git dir:
  `git --git-dir=/repo/.git`.
- **Outside a git repository (or with ephemeral mode off):** `/sandbox` is your
  working directory mounted directly from the host, and edits are immediately
  visible to the user. There is no review branch; the user sees every change as
  you make it.

## Committing is the only way the user receives your work

In ephemeral mode, and in any git repository, your changes reach the user only
as a commit on the `agent/<profile>/<session>` branch, which the host reviews
and integrates after the session ends — only committed files ever leave the
sandbox. Therefore committing is **mandatory, not optional**:

- Do not ask "want me to commit?" — just commit when a change is complete. Working on one
  task per commit.
- Never treat a task as done with uncommitted files left in the tree: if it isn't committed,
  the user has not received it.
- Before finishing, run `git status` to confirm the tree is clean and every intended change
  landed in a commit.

## Workflow

1. **Make and commit changes**:
   ```
   git add <files>
   git commit -m "<message>"
   ```

2. **Done** — keep the branch checked out and the tree clean for the host to
   review. Do not merge or rebase onto `main`.

## Rules

- **Do not push** — no SSH/token access in the container; the host reviews the
  `agent/<profile>/<session>` branch.
- **Do not checkout main/master** — stay on your `agent/<profile>/<session>` branch.
- Work on one task per commit.
- **Git identity is preset** (seeded from the host), so `git commit` works as
  is. Do not run `git config --global`: `/root/.gitconfig` is bind-mounted and
  cannot be rewritten in place ("Device or resource busy"). Use repository-local
  `git config` or environment variables if you truly need other settings.

## Quick Reference

| Task | Command |
|---|---|
| Status | `git status` |
| Log | `git log --oneline` |
| Stage | `git add <files>` |
| Commit | `git commit -m "<message>"` |
| Diff | `git diff` |
| New branch | `git checkout -b <name>` |
