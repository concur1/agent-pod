---
name: agent-pod-config
description: How to read, write, and edit agent-pod's `.agent-pod.yaml` sandbox config — mounts, profiles, passthrough env vars, nix packages, and the image/flake overrides. Use when a task involves configuring agent-pod itself (creating or editing .agent-pod.yaml, adding a mount or profile, or changing the sandbox's tools/envs).
---

# Configuring agent-pod (`.agent-pod.yaml`)

`.agent-pod.yaml` is the config file that controls how `ap run` builds and
launches a sandbox. Editing it changes what the **next** session gets; it does
not change the session you are in.

Two files are read, and merged (project wins per key):

| Scope | Path |
|---|---|
| Global | `~/.config/container-agents/.agent-pod.yaml` |
| Project | `./.agent-pod.yaml` in the working directory |

Full precedence:

```text
bundled agent config  <  global  <  project  <  CLI flags
```

Merge semantics: **dicts** (e.g. `flake`, `tmpfs_mounts`) merge key-by-key;
**lists and scalars are replaced** by a higher layer — except `files`, which
**appends** to the bundled agent's entries. Only set the keys you care about.

## Validating an edit

There is no schema command, but the file is validated by pydantic on load, so a
bad type fails `ap run` with a clear message. **Unknown keys are silently
ignored**, though — a typo doesn't warn, it just has no effect. Preview the exact
mounts and env vars an edit produces before launching:

```sh
ap plan <profile>
```

`ap plan` renders the same mount list the runner uses, with secrets flagged and
never shown. `ap init` generates a barebones config interactively if you want a
starting point.

## Top-level keys

Common ones; agent-pod's `docs/reference/config.md` and the annotated
`agent-pod.example.yaml` at its repo root document every key.

| Key | Meaning |
|---|---|
| `agent` | Default harness for `ap run` when none is given (`pi`, `opencode`, `claude`). |
| `session` | Default `--session` value. |
| `ephemeral` | `true`: mount the repo's `.git` read-write and let the container commit to its own `agent/<profile>/<session>` worktree. Default `false` mounts the working tree directly at `/sandbox`. |
| `context_files` | Default `--context-file` entries, `HOST_PATH[:NAME]`. |
| `files` | Extra mounts; appends to the agent's own list. |
| `passthrough_envs` | Host env vars to forward into the sandbox (each needs a `description`). |
| `extra_packages` | Nix packages added to the image (e.g. `uv`, `jq`); shorthand for `flake.extra_packages`. |
| `flake` | Image/flake overrides: `dir`, `extra_packages`, `allow_unfree`, `permitted_insecure`. |
| `prompt` | Custom text injected into the generated agent instructions. |
| `profile` / `profiles` | Default profile and named profile overlays. |
| `image_tag`, `container_name`, `container_home`, `tmpfs_mounts` | Lower-level container settings. |

## Profiles are overlays

A profile is a delta on top of the top-level keys, not a separate config: the
top level is the baseline for every profile, and `profiles.<name>` overrides per
key. `ap run <profile>` (or the positional argument) selects it.

```yaml
agent: pi
session: dev

profiles:
  readonly:
    agent: claude
    extra_args: [--model, sonnet]
  skills:
    files:
      - source: ~/.agent/skills
        name: skills
        permissions: rw
        seed: true
```

## `files` entries

The most-used key. Each entry mounts a host path (or generated content) into the
sandbox:

```yaml
files:
  - source: ~/dotfiles/aliases.sh   # host file/dir, or a `builtin:` id; omit for empty state
    name: .bashrc.d/aliases.sh      # container path defaults to <container_home>/<name>
    permissions: ro                 # ro | rw
    description: shared aliases     # shown by `ap plan`
  - source: ./docs/spec.md
    name: spec.md
    context: true                   # mount ro + @-reference it in instructions
  - source: ~/.config/myagent/config.json
    name: config.json
    permissions: rw
    seed: true                      # copy host file into session state on first run
    secret: true                    # flag [secret] in `ap plan`
  - name: scratch                   # no source: empty writable state dir/file
    permissions: rw
```

Other entry fields: `target` (absolute container path override), `optional`
(skip silently when `source` is missing), `type` (`file`/`dir` for state), and
`shared` (keep writable state across sessions in the agent's `.shared` dir).

A later entry at the same container path replaces an earlier one — that is how a
profile flips the bundled read-only `~/.agent/skills` mount to read/write.

## Environment variables

Forwarding a host variable requires a description, so the generated sandbox
instructions and `ap plan` can tell the agent what the value grants:

```yaml
passthrough_envs:
  - name: HF_TOKEN
    description: Hugging Face token for model downloads
```

The var is only forwarded when it is set in the launching shell; a missing one
aborts the launch with an error. Credential-looking names are flagged `[secret]`.

## Rules

- **Don't invent keys.** Only the documented keys have an effect, and unknown
  keys are silently ignored (no warning) — so a typo looks like it worked. Check
  `agent-pod.example.yaml` at the agent-pod repo root when unsure of a shape.
- **`files` appends, everything else replaces.** To drop a bundled mount, you
  can't remove it with a config entry — override its container path with your
  own entry instead.
- **`extra_packages` are raw nixpkgs attribute names** (e.g. `nodejs_22`), not
  distro package names. Unfree/insecure packages need `allow_unfree: true` /
  `permitted_insecure: ["<pkg>-<version>"]`.
- **Edits apply to future sessions.** The current sandbox's mounts are fixed at
  launch; there is no reload.
