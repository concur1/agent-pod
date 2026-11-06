---
title: How to pass secrets
---

# How to pass secrets

Nothing is forwarded into a sandbox by default: the agent gets no host env vars
and only the mounts you declare. Credentials travel one of two ways — an
environment variable from the launching shell, or a credentials file mounted
read-only. Either way the **config holds the name, never the value**, so
`.agent-pod.yaml` is safe to commit.

## Pass an environment variable

Declare the variable once, export it in the shell that launches the sandbox:

```yaml title=".agent-pod.yaml"
passthrough_envs:
  - name: GITHUB_TOKEN
    description: fine-grained PAT — read PRs, write review comments
```

```sh
export GITHUB_TOKEN=github_pat_...
ap run review
```

- Only the variable **name** reaches the container (`podman -e GITHUB_TOKEN`
  copies the value from the launching environment), so the secret never lands
  in a command line or in the config file.
- The variable is forwarded **only if it is set** in the launching shell. A
  missing one aborts the launch with an error instead of starting a sandbox
  that silently lacks credentials.
- `description` is required: it is what the generated agent instructions use to
  tell the agent what the value grants.
- Names matching `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, or `CREDENTIAL` are
  flagged `[secret]` in `ap plan` and in the instructions.

## Mount a credentials file

For tools that read credentials from disk, mount the file instead:

```yaml title=".agent-pod.yaml"
files:
  - source: ~/.config/gh/hosts.yml
    name: gh-hosts.yml
    target: /root/.config/gh/hosts.yml
    permissions: ro
    secret: true
    description: gh CLI login (read-only)
```

- `secret: true` flags the mount `[secret]` in `ap plan` and in the generated
  instructions — the host path is still shown, the contents never are.
- Use `permissions: rw` with `seed: true` when the tool rewrites its credential
  file: agent-pod copies it into session state on first run and mounts the
  copy, so the host file is never modified (and refreshed tokens don't
  survive past the session).
- `optional: true` skips the mount silently when the host file is missing —
  useful for shared configs where not every machine is logged in.

## Prefer scoped, short-lived credentials

A sandbox can run for a while and the agent may do anything you did not
forbid. Mint the narrowest credential that covers the task — a downscoped
token, a repo-scoped PAT, a short TTL — and pass that, rather than your ambient
long-lived key. The [infra and github-review recipes](recipes.md) show both.

## Check what you are about to grant

```sh
ap plan review
```

The same mount and env list the runner uses: mounts flagged `[secret]`,
each variable's status (`forwarded`, or `not set — not forwarded`), and the
network/capability posture. Values are never printed.

## Don't

- Put a credential value in `.agent-pod.yaml` — it lands in git, and the config
  only reads variable names and host paths anyway.
- Bake secrets into the image or flake: the image is reused across sessions, so
  a baked secret outlives the task.

The full `files` and `passthrough_envs` schemas are in the
[config reference](../reference/config.md).
