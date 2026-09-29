---
title: How to configure
---

# How to configure

Create a user config file — either let `ap init` generate one, or write it by
hand. Config files are optional YAML read from your **global** directory and
the **working directory**, letting you set defaults for run flags and override
any agent setting without editing the bundled agent configs:

- Global: `~/.config/container-agents/.agent-pod.yaml`
- Project: `.agent-pod.yaml` in the current working directory

## Create a config with `ap init`

Rather than hand-writing YAML, let `ap init` generate a config for you. It
asks where to write the file (project or global), then walks through a short
set of questions — the default agent, context files, and extra Nix packages.
Every answer is validated against the config model and re-asked until valid.
The result is a commented file you can extend later.

```sh title="ap init"
ap init                        # (1)!
ap init --target global        # (2)!
ap init --force                # (3)!
```

1. Answer a few questions; writes `./.agent-pod.yaml`.
2. Write to `~/.config/container-agents/.agent-pod.yaml` instead.
3. Overwrite an existing target instead of refusing.

If no config exists on **any level** (no global file *and* no project file),
`ap run` starts the wizard automatically before launching the sandbox, so the
generated config is ready before the agent starts. In non-interactive contexts
(CI, pipes) it skips the wizard and prints a pointer to `ap init` instead of
silently writing a file.

## Write a config by hand

Every key, the merge rules, and a fully-annotated example are in the
[config reference](../reference/config.md). The
[`agent-pod.example.yaml`](https://github.com/concur1/agent-pod/blob/main/agent-pod.example.yaml)
at the repo root is the pasteable, fully-commented version of the same thing.

Start small — the smallest useful project config is one line:

```yaml title=".agent-pod.yaml"
extra_packages: uv
```

## Next

- [**How to mount files and context**](mounts.md) — declare files for the
  agent to see.
- [**How to use profiles**](recipes.md) — define `profiles:` entries in the
  same file.
