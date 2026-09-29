---
title: How to mount files and context
---

# How to mount files and context

Give the agent access to files on your host. Anything the agent should see is
declared as a `files:` entry (or via the `--context-file` shortcut). Context
files are mounted read-only and `@`-referenced in the generated instructions,
so they're always present:

```sh title="Context files (repeatable)"
ap run fixes --context-file ./docs/notes.md --context-file ./docs/api.md:api.md
```

`--context-file HOST_PATH[:NAME]` is sugar for a `files:` entry with
`context: true`. For the full `files` schema — permissions, seeding, secrets,
writable state dirs — see the [config reference](../reference/config.md).

You can also declare mounts in your config so every run gets them:

```yaml title=".agent-pod.yaml"
files:
  - source: ~/dotfiles/aliases.sh
    name: .bashrc.d/aliases.sh
    permissions: ro
    description: shared aliases
  - source: ./docs/spec.md
    name: spec.md
    context: true
    description: spec shown to every agent run
```

- `source` — host file/folder, or a `builtin:` generator
  (`builtin:instructions`, `builtin:git-workflow`); omit for a writable state
  file/dir.
- `name` — mount name; container path defaults to
  `<container_home>/<name>`.
- `permissions` — `ro` or `rw`.

## Bake pi settings into the image

Sometimes the agent needs pi-specific setup — its `packages` list, model
defaults — not as a mounted file but *baked into* the sandbox image so they're
present before the agent runs:

```sh title="Settings file"
ap run fixes --settings-file ./settings.json
```

Defaults to `~/.pi/settings.json` if the flag is omitted; set a config default
with `settings_file: ~/.pi/settings.json`. This is the one thing that's built
into the image rather than mounted, but it's part of the same picture: what the
agent gets to use.

## Next

- [**How to work in git**](git.md) — keep the agent on its own private branch.
