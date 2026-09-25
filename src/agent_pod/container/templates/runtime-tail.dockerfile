# dockerTools images have no $HOME dir (root's home is /root in /etc/passwd,
# but /root is not created); make it before git needs to write ~/.gitconfig.
RUN mkdir -p /root && \
    git config --global user.name 'AI Agent' && \
    git config --global user.email 'agent@localhost'
# Ephemeral git runs mount the host repo's .git at /repo/.git and let this
# image create its own per-session worktree on it (AP_BRANCH/AP_BASE/AP_WORKTREE
# set by the runner). The worktree lives at AP_WORKTREE — a per-session subfolder
# of /sandbox — so concurrent sessions never collide on one path. First run forks
# AP_BRANCH from AP_BASE; a resumed session re-checks its branch out (--force
# clears any registration a crashed same-session run left at that path). Without
# AP_BRANCH (non-ephemeral or not a git repo) the agent just runs in the /sandbox
# working tree.
RUN cat > /usr/local/bin/agent-pod-entrypoint <<'SH'
#!/bin/sh
set -eu
if [ -n "${AP_BRANCH:-}" ]; then
  mkdir -p /sandbox
  git --git-dir=/repo/.git worktree add -b "$AP_BRANCH" "$AP_WORKTREE" "$AP_BASE" 2>/dev/null \
    || git --git-dir=/repo/.git worktree add --force "$AP_WORKTREE" "$AP_BRANCH"
  cd "$AP_WORKTREE"
fi
exec "@AGENT_CMD@" "$@"
SH
RUN chmod +x /usr/local/bin/agent-pod-entrypoint
WORKDIR /sandbox
ENTRYPOINT ["/usr/local/bin/agent-pod-entrypoint"]
