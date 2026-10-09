# Agent instructions


## Conventions

- uv is used for the python environment. The sandbox has no standalone
  `python3` — run Python through uv (`uv run python ...`), and call tools as
  `uv run pytest` / `uv run ruff` / `uv run ty`, never bare.
- Prefer a functional style with logic in pure functions. However use non-pure functions and classes where practical.
- Use strong and specific types.
- Simple concise code is preferable, when writing if statements try to use the never-nesting approach.
- Comments must be minimal and useful, if it can be inffered from the code do not make a comment about it.

## Repo map

- `src/agent_pod/cli.py` — `ap` entry (`main()`), argparse dispatch for all subcommands.
- `src/agent_pod/types.py` — Pydantic config models (AgentConfig, ProfileConfig, UserConfig, FileMount, ...).
- `src/agent_pod/plan.py` — `ap plan` preview: builds the same mount list the runner uses.
- `src/agent_pod/config/` — config loading (`loader.py`), `ap init` (`init.py`), bundled per-agent flakes (`agents/`).
- `src/agent_pod/container/` — `builder.py` (image/Dockerfile build), `runner.py` (mounts, git worktree, podman run loop), `cleanup.py`.
- `src/agent_pod/prompts/` — `loader.py` + the bundled `ephemeral-git-workflow` skill.
- `src/agent_pod/gen_config_docs.py` — regenerates `docs/reference/config.md` from the config models.
- `src/agent_pod/utils/` — `names.py` (humanized session ids), `paths.py` (package root).
- `src/agent_pod/log.py` — stdlib logging, pre-wired to stderr.
- `tests/` — pytest suite mirroring the package layout.

## Python checks

- Run `make format` (ruff `--fix` + `ruff format`) **before** hand-fixing any
  remaining problems — it resolves most lint issues automatically.
- Only then fix what `make format` leaves behind, and verify with
  `make check` (ruff lint + ty typecheck) and `make test` (pytest).
- Run `make clean` after renaming or removing a Python package — the old
  package's `__pycache__` dirs linger, ignored by git and invisible to
  `git status`.
- `docs/reference/config.md` is **generated** from the Pydantic models in
  `types.py` (`make docs-ref`) — don't hand-edit it; regenerate after changing
  a config model.
