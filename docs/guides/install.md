---
title: How to install
---

# How to install

Requires Python 3.11+ and [Podman](https://podman.io/) — used for all
container and volume operations. Install the tool first; agent-pod itself runs
on the next page.

=== "uv tool"

    Install the `ap` (and `agent-pod`) command into a managed environment:

    ```sh
    uv tool install .
    ```

=== "pip"

    Install into your current environment:

    ```sh
    pip install .
    ```

The console command is `ap`; the full `agent-pod` spelling works as an alias.
Default agent configs (and their Nix flakes) ship inside the package, so `ap`
works straight after install — no repo checkout needed.

## Next

[Run your first agent](../tutorials/quickstart.md) — build a sandbox and
launch.
