---
title: Profiles to taste
---

# Profiles to taste

Each profile is an overlay on top of the top-level config. The same file
defines them all — here are a few shapes that work out of the box:

=== "readonly"

    A different (cheaper/reviewer) harness configured for read-only review:

    ```yaml
    profiles:
      readonly:
        agent: pi
    ```

=== "daily"

    A fast loop — trusted repo, auto-commit style:

    ```yaml
    profiles:
      daily:
        agent: pi
        extra_args: ["--no-approval"]
    ```

=== "skills"

    Read/write access to the agent's skills dir via a seeded copy in session
    state:

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

=== "grunt"

    A different agent for mechanical tasks (or one pinned to a cheaper model):

    ```yaml
    profiles:
      grunt:
        agent: opencode
        extra_args: ["--model", "fast"]
    ```

=== "audit"

    Mount context docs read-only for review-heavy work:

    ```yaml
    profiles:
      audit:
        agent: claude
        context_files: [docs/spec.md, docs/api.md:api.md]
    ```

`ap list` lists what each profile does — `(active)` marks the config's
`profile:` default, else `default`. Any option settable at the top level is
settable per profile, with top-level values as the baseline; profile `files`
entries append after the top-level user `files`, and a later mount at the same
container path replaces an earlier one — so a profile can flip a bundled
read-only mount to read/write. Profile `files` *source* may be `builtin:`
generators like `builtin:instructions` or `builtin:git-workflow`.

Define profiles in the same config file, alongside the top-level keys — see
the [config guide](config.md) and the [config reference](../reference/config.md).
