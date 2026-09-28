---
title: Mounts & context
---

# Mounts & context

Anything the agent should see is declared as a `files:` entry (or via the
`--context-file` shortcut). Context files are mounted read-only and
`@`-referenced in the generated instructions, so they're always present:

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

## Next

- [**Pi settings**](settings.md) — bake pi settings into the image.
- [**Git work**](git.md) — keep the agent on its own private branch.
