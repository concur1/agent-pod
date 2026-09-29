---
title: How to contribute
---

# How to contribute

Set up the dev environment and run the checks:

```sh title="Development"
uv sync --group dev        # (1)!
uv run pytest              # (2)!
uv run ruff check .        # (3)!
```

1. Install dev dependencies.
2. Run the test suite.
3. Lint. `uv run ruff check . --fix && uv run ruff format .` auto-formats;
   `uv run ty check` type-checks.

Uses [uv](https://docs.astral.sh/uv/) for dependency management and a
[Nix flake](https://github.com/concur1/agent-pod/blob/main/flake.nix)
(uv2nix) for a reproducible dev environment.
