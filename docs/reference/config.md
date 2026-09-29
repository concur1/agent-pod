---
title: Config files
---

# Config files

Read from (in order of precedence):

- Global: `~/.config/container-agents/.agent-pod.yaml`
- Project: `.agent-pod.yaml` in the current working directory

Both files are validated with Pydantic using the same strategy as the bundled
agent configs, so malformed YAML or bad types fail with a clear error. An
unknown default `agent` is warned about and ignored.

<!-- generated:config-keys:start -->
## Config keys

Every key you can set, generated from the Pydantic config models so the reference can't drift from the validator.

### Top-level config and profiles

The top level of a config file accepts every key below; all but `profile`/`profiles` are also valid inside a `profiles.<name>` entry.

| Key | Type | Default | Description |
|---|---|---|---|
| `agent` | `str \| null` | `null` | Default agent for `ap run`/`build`/`sessions` when none is given on the CLI. |
| `context_files` | `list[str] \| null` | `null` | Default `--context-file` entries (HOST_PATH[:NAME]). |
| `files` | `list[FileMount] \| null` | `null` | File/dir mounts appended to the agent's `files` (see AgentConfig.files); a later mount at the same container path replaces an earlier one. |
| `extra_args` | `list[str] \| null` | `null` | Default extra args forwarded to the agent. |
| `settings_file` | `str \| null` | `null` | Default `--settings-file` path. |
| `session` | `str \| null` | `null` | Default --session value. |
| `ephemeral` | `bool \| null` | `null` | Ephemeral git sessions: in a git repo, mount the .git read-write so the container creates its own per-session worktree on it — only committed files reach the host. Default false: the working tree is mounted directly at /sandbox. |
| `flake` | `FlakeOverrides \| null` | `null` | Override of the agent's `flake` config (see AgentConfig.flake). |
| `extra_packages` | `list[str] \| null` | `null` | Nix packages to add to the agent's flake image (shorthand for `flake.extra_packages`, so it applies to whichever agent is run). A single string is accepted as a one-item list. |
| `allow_unfree` | `bool \| null` | `null` | Shorthand for `flake.allow_unfree`: allow unfree nixpkgs packages in the agent image. |
| `permitted_insecure` | `list[str] \| null` | `null` | Shorthand for `flake.permitted_insecure`: exact nixpkgs package versions allowed despite being marked insecure. |
| `image_tag` | `str \| null` | `null` | See AgentConfig.image_tag |
| `container_name` | `str \| null` | `null` | See AgentConfig.container_name |
| `container_home` | `str \| null` | `null` | See AgentConfig.container_home |
| `tmpfs_mounts` | `dict[str, str] \| null` | `null` | See AgentConfig.tmpfs_mounts |
| `passthrough_envs` | `list[str] \| null` | `null` | See AgentConfig.passthrough_envs |
| `profile` | `str \| null` | `null` | Default profile name for `ap run`/`plan`. |
| `profiles` | `dict[str, ProfileConfig]` | `{}` | Named profiles: overrides on top of the top-level defaults, plus the `agent/<profile>/<id>` branch namespace for auto-generated sessions. |

### `files` entries

Each entry of the `files` list.

| Key | Type | Default | Description |
|---|---|---|---|
| `source` | `str \| null` | `null` | Host file or folder to mount, or a `builtin:` generator id (`builtin:instructions`, `builtin:git-workflow`) for content agent-pod generates at runtime. Omit for a writable state file/dir with no host seed (it is created empty in the session state dir). |
| `name` | `str` | `—` | Mount name; the container path defaults to `<container_home>/<name>`. Slash-separated names nest (e.g. `skills/git-workflow/SKILL.md`). |
| `permissions` | `ro \| rw` | `—` | Mount permissions: read-only (`ro`) or read/write (`rw`). |
| `description` | `str \| null` | `null` | Human-readable description shown by `ap plan`. |
| `target` | `str \| null` | `null` | Absolute container path override; defaults to `<container_home>/<name>` (e.g. opencode's auth.json lives outside its home). |
| `optional` | `bool` | `false` | Skip silently if the host `source` is missing (default False prints a warning and skips). Writable state entries are always created. |
| `context` | `bool` | `false` | Treat the file as a context file: mounted read-only into the shared contexts dir, listed in the generated instructions, and passed to pi as an `@<path>` arg. `--context-file` / the `context_files` config key are sugar for a `context: true` files entry; adding `context: true` here is the generic form. |
| `seed` | `bool` | `false` | For read/write files: copy the host `source` into the session state dir on first run, then mount the copy writable so the host file is never modified. |
| `secret` | `bool` | `false` | Flag the mount as `[secret]` in `ap plan`; values never shown. |
| `type` | `file \| dir \| null` | `null` | Explicit file/dir kind for writable state entries; inferred when omitted (`file` when `seed` is set, otherwise from the source's type or the name's extension). |

### `flake` entries

`flake` overrides the agent's flake config.

| Key | Type | Default | Description |
|---|---|---|---|
| `dir` | `str \| null` | `null` | See FlakeConfig.dir |
| `extra_packages` | `list[str] \| null` | `null` | See FlakeConfig.extra_packages |
| `allow_unfree` | `bool \| null` | `null` | See FlakeConfig.allow_unfree |
| `permitted_insecure` | `list[str] \| null` | `null` | See FlakeConfig.permitted_insecure |
<!-- generated:config-keys:end -->


Values are merged lowest-to-highest precedence, so more specific layers win:

```text
bundled agent config  <  global config  <  project config  <  CLI flags
```

Merge semantics:

- **dicts merge key-by-key** (e.g. `flake`, `tmpfs_mounts`);
- **lists and scalars are replaced** — a higher layer fully replaces a lower
  layer's list rather than appending;
- **`files` is appended** to the bundled agent's list, so your file entries
  are added without dropping the agent's own (built-in instruction/skill
  mounts keep their position before your entries).

Only the fields you set need to appear; the rest fall back to the bundled
agent config / CLI defaults.

## Example

The same config as annotated snippets. The
[`agent-pod.example.yaml`](https://github.com/concur1/agent-pod/blob/main/agent-pod.example.yaml)
at the repo root is the fully-commented, pasteable version.

=== "Run defaults"

    ```yaml
    agent: opencode            # (1)!
    session: dev               # (2)!
    bash: false                # (3)!
    context_files:             # (4)!
      - docs/notes.md
      - docs/api.md:api.md
    settings_file: ~/.pi/settings.json   # (5)!
    extra_args: [--model, sonnet]        # (6)!
    ```

    1. Default agent for `ap run`, `build`, and `sessions`.
    2. Persistent session name used by every run.
    3. Run the agent directly instead of through an interactive bash shell.
    4. Context files mounted read-only and shown to the agent.
    5. Path to pi settings used when building the sandbox image.
    6. Extra arguments forwarded to the agent.

=== "Agent-config overrides"

    Flat top-level keys, applied to whichever agent is run:

    ```yaml
    extra_packages:                              # (1)!
      - uv
      - jq
    allow_unfree: true                           # (2)!
    permitted_insecure: [openssl-1.1.1w]         # (3)!
    passthrough_envs: [MY_API_KEY]               # (4)!
    image_tag: localhost/opencode-sandbox:latest # (5)!
    tmpfs_mounts:                                # (6)!
      /tmp: rw,exec,size=512m
    ```

    1. Runtime tooling (raw nixpkgs attrs, e.g. `nodejs_22` not `node:22`)
       added to the flake image; shorthand for `flake.extra_packages`. A bare
       string like `uv` is accepted as a one-item list.
    2. Permit unfree-licensed packages (default: deny).
    3. Permit the exact version of a package with known vulnerabilities
       (default: deny — an agent sandbox executes potentially untrusted code).
    4. Opt-in to forwarding these env vars into the sandbox; no vars are
       forwarded by default, so `ap plan` won't list unused API keys unless
       you ask for them.
    5. Override the built image tag.
    6. Extra tmpfs mounts.

=== "Files"

    `files` entries are appended to the agent's own `files` list:

    ```yaml
    files:
      - source: ~/dotfiles/aliases.sh   # (1)!
        name: .bashrc.d/aliases.sh      # (2)!
        permissions: ro                 # (3)!
        description: shared aliases     # (4)!
      - source: ./docs/spec.md          # (5)!
        name: spec.md
        context: true                   # (6)!
        description: spec shown to every agent run
      - name: scratch                   # (7)!
        permissions: rw
        description: scratch area (writable state dir)
    ```

    1. `source` — host file/folder, or a `builtin:` generator
       (`builtin:instructions`, `builtin:git-workflow`); omit for a writable
       state file/dir.
    2. `name` — mount name; container path defaults to
       `<container_home>/<name>`.
    3. `permissions` — `ro` or `rw`.
    4. `description` — shown by `ap plan`.
    5. `target` (not shown) — absolute container path override; `optional`
       skips silently if the host `source` is missing.
    6. `context` — mount read-only into the shared contexts dir and
       `@`-reference it in instructions + pi args (the generic form of
       `context_files:`/`--context-file`, which are sugar for it).
    7. Writable state entry — no `source`; `type` (`file`|`dir`) inferred;
       `seed` copies host `source` into session state on first run; `secret`
       flags it `[secret]` in `ap plan`.

## Overridable fields

The config can override any `AgentConfig` field as a flat key (`flake`,
`image_tag`, `container_name`, `container_home`, `files`, `tmpfs_mounts`,
`passthrough_envs`). Notably:

- `passthrough_envs` is the opt-in for env forwarding — no vars are forwarded
  by default.
- `extra_packages` adds runtime tooling (e.g. `uv`) to the agent's flake
  image; it was removed from the bundled agent configs, so the user config is
  the source of truth for it. Overrides apply to whatever agent is run, so a
  config like `extra_packages: uv` gives every agent that package.
- Two nixpkgs safety gates are surfaced as overrides: `allow_unfree` (default
  false) permits unfree-licensed packages (e.g. `unrar`), and
  `permitted_insecure` (default empty) permits the exact version of a package
  with known vulnerabilities — default-deny, since an agent sandbox executes
  potentially untrusted code.
