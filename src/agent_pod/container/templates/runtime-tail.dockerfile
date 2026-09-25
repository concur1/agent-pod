# dockerTools images have no $HOME dir (root's home is /root in /etc/passwd,
# but /root is not created); make it before git needs to write ~/.gitconfig.
RUN mkdir -p /root && \
    git config --global user.name 'AI Agent' && \
    git config --global user.email 'agent@localhost'
# Ephemeral git runs mount the host repo's .git at /repo/.git and let this
# image create its own per-session worktree on it (AP_BRANCH/AP_BASE set by the
# runner). First run forks AP_BRANCH from AP_BASE; resume re-checks the branch
# out. Without AP_BRANCH (non-ephemeral or not a git repo) the agent just runs
# in the /sandbox working tree.
RUN cat > /usr/local/bin/agent-pod-entrypoint <<'SH'
#!/bin/sh
set -eu
if [ -n "${AP_BRANCH:-}" ]; then
  git --git-dir=/repo/.git worktree add -b "$AP_BRANCH" /sandbox "$AP_BASE" 2>/dev/null \
    || git --git-dir=/repo/.git worktree add /sandbox "$AP_BRANCH"
fi
exec "@AGENT_CMD@" "$@"
SH
RUN chmod +x /usr/local/bin/agent-pod-entrypoint
WORKDIR /sandbox
ENTRYPOINT ["/usr/local/bin/agent-pod-entrypoint"]
