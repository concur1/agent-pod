---
title: Command line
---

# Command line

The reference for the `ap` command: commands, options, and supported agents.

## Commands

| Command | Description |
|---|---|
| `run [profile]` | Build the image and launch the agent under a profile |
| `shell [profile]` | Same build, but replace the agent entrypoint with an interactive bash shell |
| `build <agent>` | Build the container image without running it |
| `init` | Interactively generate a user config file from the model's options |
| `list` | List configured profiles (active marker, agent, flags); `--agents` lists supported agents |
| `plan [profile]` | Preview the files, secrets, and env vars the agent will be granted |
| `sessions <agent>` | List sessions and their container status |
| `sessions <agent> --rm <session>` | Remove a session: its container and session state dir (git history stays in the repo's `.git`) |
| `worktree <agent> keep <session>` | Mark a session's worktree to be kept (auto-tidy leaves it alone) |
| `worktree <agent> integrate <session>` | Merge a session's branch into the main worktree and remove the worktree |

## `run` options

`run [profile]` selects a named profile. The harness agent comes from the
profile's `agent` (else the config's `agent`), overridable with `--agent`.
Each run gets its own humanized session (e.g. `crisp-lamp`) unless you pass an
explicit `--session`. Define profiles in your [config](config.md):

```yaml title="Defining profiles"
profile: fixes            # (1)!
profiles:                 # (2)!
  fixes:
    agent: pi             # (3)!
    extra_args: ["--no-approval"]
  chores:
    agent: opencode
```

1. `profile` — the default profile used by `ap run` with no argument.
2. `profiles` — a map of profile name to overrides.
3. The harness agent for this profile; falls back to the config's `agent`.

### Flags

- `--agent <name>` — override the harness agent for this run. `ap run` with
  no profile runs the config's default agent under the `default` profile;
  `ap run fixes --agent pi` runs pi under the fixes profile's overrides.
- `--session <name>` — explicit persistent session: isolates state for
  parallel runs. Each session keeps its own state dir under
  `~/.config/container-agents/<agent>/<name>/`. An explicit session maps to a
  stable `agent/<profile>/<name>` branch, so a resumed session checks the same
  branch back out. Without `--session`, each run gets a fresh humanized
  session name (e.g. `crisp-lamp`) and its own branch, so two runs never
  collide.
- `--settings-file HOST_PATH` — pi settings used when building the sandbox
  image (defaults to `~/.pi/settings.json`). Its `packages` list is installed
  into the image at build time.
- `--context-file HOST_PATH[:NAME]` — mount a file into the agent and
  reference it from the generated instructions. Repeatable. This is sugar for
  a `files:` entry with `context: true` — the generic form, which behaves
  identically (read-only mount into the shared contexts dir,
  `@`-referenced in the instructions, and passed to pi as `@<path>` args).

Any other arguments are forwarded to the agent itself.

## `plan` options

`ap plan [profile]` shows what the agent will be able to reach before you
launch it:

- **Filesystem access** lists each host path with its `read-only` /
  `read/write` mode, the container path it maps to, and any `description`
  from the config's `files` entry, grouped by access type — read/write first
  (in red), then read-only, then tmpfs. Credentials are flagged `[secret]`
  in red and values are never shown.
- **Environment variables** lists agent-pod's own internal vars by default
  (no env vars are forwarded by default); with `passthrough_envs` it lists
  those with a live forwarded/not-forwarded status, flagging secret-looking
  names with `[secret]`.
- **Network & capabilities** truthfully reports the sandbox's posture
  (currently full outbound, host network disabled, podman default
  capabilities).

It accepts an optional profile positional, `--agent`, `--session`, and
`--context-file` so you can preview the exact run.

## Supported agents

| Agent | Image tag | Persisted state |
|---|---|---|
| `pi` | `localhost/pi-sandbox:latest` | `~/.config/container-agents/pi/` |
| `opencode` | `localhost/opencode-sandbox:latest` | `~/.config/container-agents/opencode/` |
| `claude` | `localhost/claude-sandbox:latest` | `~/.config/container-agents/claude/` |
