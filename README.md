# agent-pod

Fast, isolated container sandboxes for AI coding agents, built on **Podman**.

`ap` (short for agent-pod) builds a disposable container image for a supported
coding agent (pi, opencode, claude), wires up persistent state,
mounts your repository and workflow instructions, and launches the agent inside
the sandbox. It cleans up after itself — no stray containers, volumes, or state
left behind.

## Install

Requires Python 3.11+ and [Podman](https://podman.io/).

```sh
# Install the `ap` (and `agent-pod`) command into a managed environment
uv tool install .

# ...or into your current environment
pip install .
```

The console command is `ap`; the full `agent-pod` spelling works as an alias.

Default agent configs (and their Nix flakes) ship inside the package, so `ap`
works straight after install — no repo checkout needed.

## Prerequisites

- [Podman](https://podman.io/) — used for all container and volume operations

## Quick start

```sh
# Run the default agent under the default profile
ap run

# Run a named profile (harness = the profile's `agent`, else the config's `agent`)
ap run fixes

# Override the harness for a profile
ap run fixes --agent pi

# Drop into an interactive bash shell inside the sandbox
ap shell
ap shell fixes

# List configured profiles (and what each one overrides)
ap list

# Run with isolated state (persistent session: own volume + state dir)
ap run fixes --session dev

# Bake pi settings (incl. its packages list) into the sandbox image
ap run fixes --settings-file ./settings.json

# Mount extra context files into the agent (repeatable)
ap run fixes --context-file ./docs/notes.md --context-file ./docs/api.md:api.md

# Generate a config file, picking your defaults interactively
ap init
```

> **First run:** if no config file exists on any level, `ap run` walks you
> through `ap init` automatically before launching the sandbox.

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

### `plan` options

`ap plan [profile]` shows what the agent will be able to reach before you launch
it. Filesystem access lists each host path with its `read-only` / `read/write`
mode, the container path it maps to, and any `description` from the config's
`files` entry, grouped by access type — read/write
first (in red), then read-only, then tmpfs; credentials are flagged `[secret]`
in red and values are never shown. No environment variables are forwarded by
default, so the ENVIRONMENT VARIABLES section lists only agent-pod's own
internal vars; if you opt into passthrough via `passthrough_envs`, it lists
those with a live forwarded/not-forwarded status, flagging secret-looking names
with `[secret]`. A NETWORK & CAPABILITIES section truthfully reports the
sandbox's network and capability posture (currently full outbound, host network
disabled, podman default capabilities). It accepts an optional profile
positional, `--agent`, `--session`, and `--context-file` so you can preview the
exact run.

### `run` options

`run [profile]` selects a named profile. The harness agent comes from the
profile's `agent` (else the config's `agent`), overridable with `--agent`.
Each run gets its own humanized session (e.g. `crisp-lamp`) unless you pass an
explicit `--session`. Define profiles in your config:
  ```yaml
  profile: fixes            # optional default profile
  profiles:
    fixes:
      agent: pi
      extra_args: ["--no-approval"]
    chores:
      agent: opencode
  ```

### Profile ideas

Each profile is a set of run-level overrides. `ap list` lists what each one
does (`(active)` marks the config's `profile:` default, else `default`). A few
shapes that work out of the box:

- **`readonly` (locked-down)** — a different (cheaper/reviewer) harness agent
  configured for read-only review work:
  ```yaml
  profiles:
    readonly:
      agent: pi
  ```
  Today profiles control *run* options (agent, flags, context files, settings)
  and per-profile `files:` mounts. Profile `files` entries
  append after the top-level user `files`, and a later mount at the same
  container path replaces an earlier one — so a profile can flip a bundled
  read-only mount to read/write. The one thing still not expressible per
  profile is container networking (sandbox egress is all-or-nothing), so
  "only reach the Scaleway API" remains a natural next step.
- **`daily` (fast loop)** — trusted repo / auto-commit style:
  ```yaml
  profiles:
    daily:
      agent: pi
      extra_args: ["--no-approval"]
  ```
- **`skills` (write/install skills)** — read/write access to the agent's
  skills dir: host `~/.agent/skills` is seeded into session state on the
  first run and the *copy* is mounted read/write. New skills the agent
  authors persist across runs of this profile without ever touching the
  host dir (drop `seed: true` and it mounts the host dir directly, writes
  flowing back). Add a `context: true` entry (or a `--context-file`) to
  point it at an existing skills spec:
  ```yaml
  profiles:
    skills:
      agent: pi
      files:
        - source: ~/.agent/skills
          name: skills
          permissions: rw
          seed: true
          description: your skills dir (seeded copy; writes kept in session state)
  ```
- **`grunt` (chores)** — a different agent for mechanical tasks (or one
  pinned to a cheaper model):
  ```yaml
  profiles:
    grunt:
      agent: opencode
      extra_args: ["--model", "fast"]
  ```
- **`audit` (plan-first)** — mount context docs read-only for review-heavy
  work:
  ```yaml
  profiles:
    audit:
      agent: claude
      context_files: [docs/spec.md, docs/api.md:api.md]
  ```
- `--agent <name>` — override the harness agent for this run (defaults to the
  profile's `agent`, else the config's `agent`). `ap run` with no profile runs
  the config's default agent under the `default` profile; `ap run fixes --agent
  pi` runs pi under the fixes profile's overrides.
- `--session <name>` — explicit persistent session: isolate state for parallel
  runs. Each session keeps its own state dir under
  `~/.config/container-agents/<agent>/<name>/`. An explicit session maps to a
  stable `agent/<profile>/<name>` branch, so a resumed session checks the same
  branch back out. Without `--session`, each run gets a fresh humanized session
  name (e.g. `crisp-lamp`) and its own branch,
  so two runs never collide.
- `--settings-file HOST_PATH` — pi settings used when building the sandbox
  image (defaults to `~/.pi/settings.json`). Its `packages` list is installed
  into the image at build time.
- `--context-file HOST_PATH[:NAME]` — mount a file into the agent and reference
  it from the generated instructions. Repeatable. This is sugar for a `files:`
  entry with `context: true` — the generic form, which behaves identically
  (read-only mount into the shared contexts dir, `@`-referenced in the
  instructions, and passed to pi as `@<path>` args).

Any other arguments are forwarded to the agent itself.

### Terminal-close cleanup

The sandbox container is removed when the agent exits. It is also removed when
the terminal it runs in is closed — including closing a pane/tab in a terminal
multiplexer such as zellij — so a TUI agent's background process can't linger
and keep consuming memory. `ap` traps `SIGHUP` and force-removes the container
(`podman stop -t 0` + `podman rm -f`) instead of relying on `--rm` alone.

## User configuration

`ap` reads an optional YAML config from your **global** directory and the
**working directory**, letting you set defaults for run flags and override any
agent setting without editing the bundled agent configs.

- Global: `~/.config/container-agents/config.yaml`
- Project: `.agent-pod.yaml` in the current working directory

A fully-commented reference is in [`agent-pod.example.yaml`](agent-pod.example.yaml) at
the repo root.

### Generating a config with `ap init`

Rather than hand-writing YAML, run `ap init` to generate a config
interactively. It asks where to write the file (project or global), then walks
through a short set of questions — the default agent, context
files, and extra Nix packages (pre-filled with `git, bash`, which you can
extend or change). Every answer is validated against the config model and
re-asked until valid, and each one is written to the file, so the generated
config records exactly what you chose. The result is a commented file you can
extend later:

```sh
ap init                       # answer a few questions, writes ./.agent-pod.yaml
ap init --target global       # write ~/.config/container-agents/config.yaml
ap init --force               # overwrite the target config instead of refusing
```

### Automatic first-run init

If no user config exists on **any level** (no global file *and* no project
file), `ap run` automatically starts the wizard before launching the sandbox,
so the generated config is ready before the agent starts. This is a no-op when
a config already exists on either level. In non-interactive contexts (CI,
pipes) it skips the wizard and prints a pointer to `ap init` instead of
silently writing a file.

### Precedence

Values are merged lowest-to-highest precedence, so more specific layers win:

```
bundled agent config  <  global config  <  project config  <  CLI flags
```

Merge semantics: **dicts merge key-by-key** (e.g. `flake`, `tmpfs_mounts`),
while **lists and scalars are replaced** (a higher layer fully replaces a lower
layer's list rather than appending). The one exception is `files`, which is
**appended** to the bundled agent's list — so your file entries are added
without dropping the agent's own (built-in instruction/skill mounts keep their
position before your entries). Only the fields you set need to appear; the rest
fall back to the bundled agent config / CLI defaults.

### Example

```yaml
# ~/.config/container-agents/config.yaml (or ./.agent-pod.yaml)
agent: opencode            # default agent for `ap run`/`build`/`sessions`
session: dev
bash: false
context_files:
  - docs/notes.md
  - docs/api.md:api.md
settings_file: ~/.pi/settings.json
extra_args: [--model, sonnet]

# Agent-config overrides are flat top-level keys, applied to whichever agent is
# run. extra_packages is shorthand for flake.extra_packages (a bare string like
# `uv` is accepted as a one-item list). allow_unfree / permitted_insecure are
# shorthand for flake.allow_unfree / flake.permitted_insecure (nixpkgs safety
# gates; insecure is default-deny).
extra_packages:
  - uv
  - jq
allow_unfree: true
permitted_insecure: [openssl-1.1.1w]
passthrough_envs: [MY_API_KEY]
image_tag: localhost/opencode-sandbox:latest
tmpfs_mounts:
  /tmp: rw,exec,size=512m

# Files/dirs to add to the sandbox (appended to the agent's own `files`):
#   source      — host file/folder, or `builtin:` generator (`builtin:instructions`,
#                 `builtin:git-workflow`); omit for a writable state file/dir.
#   name        — mount name; container path defaults to <container_home>/<name>.
#   permissions — ro | rw
#   description — shown by `ap plan`.
#   target      — absolute container path override.
#   optional    — skip silently if the host `source` is missing.
#   seed        — rw files: copy host `source` into session state on first run.
#   secret      — flag as [secret] in `ap plan`.
#   type        — file | dir for writable state entries (inferred otherwise).
#   context     — true: mount read-only into the shared contexts dir and
#                 @-reference it in instructions + pi args (the generic form of
#                 `context_files:`/`--context-file`, which are sugar for it).
files:
  - source: ~/dotfiles/aliases.sh
    name: .bashrc.d/aliases.sh
    permissions: ro
    description: shared aliases
  - source: ./docs/spec.md
    name: spec.md
    context: true
    description: spec shown to every agent run
  - name: scratch
    permissions: rw
    description: scratch area (writable state dir)
```

The config can override any `AgentConfig` field as a flat key (`flake`,
`image_tag`, `container_name`, `container_home`, `files`, `tmpfs_mounts`,
`passthrough_envs`). `passthrough_envs` is the opt-in for env
forwarding — no vars are forwarded by default, so `ap plan` won't list a wall
of unused API keys unless you ask for them. `extra_packages` adds runtime
tooling (e.g. `uv`) to the agent's flake image; it was removed from the bundled
agent configs, so the user config is the source of truth for it. Overrides
apply to whatever agent is run, so a config like `extra_packages: uv` gives
every agent that package. Names are raw nixpkgs attributes (`nodejs_22`, not
`node:22`). Two nixpkgs safety gates are surfaced as overrides:
`allow_unfree` (default false) permits unfree-licensed packages (e.g. `unrar`),
and `permitted_insecure` (default empty) permits the exact version of a package
with known vulnerabilities — default-deny, since an agent sandbox executes
potentially untrusted code.

Both files are validated with Pydantic using the same strategy as the bundled
agent configs, so malformed YAML or bad types fail with a clear error. An unknown
default `agent` is warned about and ignored.


## Supported agents

| Agent | Image tag | Persisted state |
|---|---|---|
| `pi` | `localhost/pi-sandbox:latest` | `~/.config/container-agents/pi/` |
| `opencode` | `localhost/opencode-sandbox:latest` | `~/.config/container-agents/opencode/` |
| `claude` | `localhost/claude-sandbox:latest` | `~/.config/container-agents/claude/` |

## Skills

Each agent's global skills dir (`~/.pi/agent/skills/`, `~/.config/opencode/skills/`,
`~/.claude/skills/`) is declared in the agent's `files` list, with your
**global, cross-platform skills directory** `~/.agent/skills/` (portable
`<name>/SKILL.md` folders) mounted **read-only** into it — so any skill you
drop into `~/.agent/skills/<name>/SKILL.md` on the host is discovered by the
sandboxed agent: no rebuild, no stale seeded copy. The skills entry is
`optional`, so it is skipped silently when the host dir is absent.

The shared git-workflow skill is also mounted (via the `builtin:git-workflow`
file entry) into each supported agent's global skills dir and loaded on demand,
so it works even without a host skills dir present.

## Where the agent works

Two modes, selected by the `ephemeral` field (default off):

- **Ephemeral git sessions (`ephemeral: true`, inside a git repo with at least
  one commit):** `ap` mounts your repo's **`.git` directory** read-write at
  `/repo/.git` — not your working tree. The container's entrypoint then creates
  its own **private per-session worktree** inside the pod (`git worktree add` on
  branch `agent/<profile>/<session>` at `/sandbox`, forked from your current
  HEAD), so the agent's commits land on its own branch, never on `main`, and the
  host checkout is never touched. Because only `.git` is mounted, **only
  committed files ever reach the host**: uncommitted edits, untracked files, and
  your host's working tree stay out of the container entirely.
- **Direct (`ephemeral: false`, or not a git repo):** your working directory is
  mounted at `/sandbox` as before, and edits are immediately visible to the host.

On exit the host runs a best-effort `git worktree prune` to drop the
container-written worktree metadata from your `.git`; the `agent/` branch itself
stays behind for review. Explicit sessions resume by checking the same branch
back out; auto sessions (fresh `adjective-noun` names) each fork their own
branch from your then-current HEAD. The old host-side worktree management
(`ap worktree keep|integrate`) is gone — to fold a session's branch into your
mainline, just `git merge agent/<profile>/<session>` on the host.

Git identity inside the sandbox: the runtime `.gitconfig` is seeded per session
from your host git identity (`git config --global user.name`/`user.email`,
honoring `[include]`), falling back to the image default, so commits in the
container work off the shelf. It's bind-mounted into the container at
`/root/.gitconfig`, which means `git config --global` can't rewrite it in place
(rename onto a mounted file fails with "Device or resource busy"); set
additional settings with repo-local config or environment variables instead.

## Development

```sh
uv sync --group dev       # install dev dependencies
uv run pytest             # tests
uv run ruff check .       # lint
```

Uses [uv](https://docs.astral.sh/uv/) for dependency management and a
[Nix flake](flake.nix) (uv2nix) for a reproducible dev environment.

## Layout

```
src/agent_pod/             # CLI implementation + bundled configs, flakes, and prompts
tests/                     # pytest suite
adr/                       # architecture decision records
flake.nix                  # Nix dev environment
```

For details on how the sandbox is built and run, see
[`src/agent_pod/container/README.md`](src/agent_pod/container/README.md).
