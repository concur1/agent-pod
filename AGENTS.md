# Agent instructions


## Conventions

- uv is used for the python environment.
- Prefer a functional style with logic in pure functions. However use non-pure functions and classes where practical.
- Use strong and specific types.
- Simple concise code is preferable, when writing if statements try to use the never-nesting approach.
- Comments must be minimal and useful, if it can be inffered from the code do not make a comment about it.

## Python checks

- Run `make format` (ruff `--fix` + `ruff format`) **before** hand-fixing any
  remaining problems — it resolves most lint issues automatically.
- Only then fix what `make format` leaves behind, and verify with
  `make check` (ruff lint + ty typecheck) and `make test` (pytest).
- Run `make clean` after renaming or removing a Python package — the old
  package's `__pycache__` dirs linger, ignored by git and invisible to
  `git status`.
