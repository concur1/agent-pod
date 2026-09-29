# Contributing

Set up the dev environment and run the checks:

```sh
uv sync --group dev
uv run pytest
uv run ruff check .
```

- `uv sync --group dev` — install dev dependencies.
- `uv run pytest` — run the test suite.
- `uv run ruff check .` — lint; `uv run ruff check . --fix && uv run ruff format .`
  auto-formats, and `uv run ty check` type-checks.

Uses [uv](https://docs.astral.sh/uv/) for dependency management and a
[Nix flake](https://github.com/concur1/agent-pod/blob/main/flake.nix)
(uv2nix) for a reproducible dev environment.
