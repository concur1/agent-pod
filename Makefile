.PHONY: clean check lint typecheck test format build run

# Run all checks: ruff lint + ty type check
check: lint typecheck

# Ruff lint (includes import sorting)
lint:
	uv run ruff check .

# Ty type check
typecheck:
	uv run ty check

# Run the test suite
test:
	uv run pytest

# Auto-format with ruff (and fix lint issues)
format:
	uv run ruff check . --fix
	uv run ruff format .

# Remove Python bytecode caches. When a package is renamed or removed, its
# old __pycache__ dirs linger here, ignored by git and invisible to git status.
clean:
	uv run python -c 'import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path(".").rglob("__pycache__") if ".venv" not in p.parts and ".git" not in p.parts]'

# Clear the agent-pod package cache and (re)install `ap` from source
build:
	uv cache clean agent-pod --force
	uv tool install --force --reinstall .

# Rebuild the tool, then run it
run: build
	ap run
