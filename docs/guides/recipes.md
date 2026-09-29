---
title: How to use profiles
---

# How to use profiles

Each profile is an overlay on top of the top-level config. The same file
defines them all — here are a few shapes that work out of the box:

=== "readonly"

    A different (cheaper/reviewer) harness configured for read-only review:

    ```yaml
    profiles:
      readonly:
        agent: pi
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

=== "infra"

    Infrastructure work behind a **downscoped** GCP token, minted per-task
    with the Security Token Service — so a mistake can only touch the exact
    resource the token scopes, never your ambient project credentials:

    ```yaml
    profiles:
      infra:
        agent: pi
        passthrough_envs: [GCP_ACCESS_TOKEN]
    ```

    Mint the token with `gcloud iam downscoped-tokens` (scoping it to the
    project/resource and roles the task needs), export it as
    `GCP_ACCESS_TOKEN`, then run the profile. `passthrough_envs` is the
    opt-in for env forwarding: no vars pass by default, and the run fails
    loudly if the named var isn't set in your shell.

=== "github-review"

    PR review with a scoped GitHub token — a fine-grained PAT limited to the
    repo(s) needing review, with read on pull requests and write on review
    comments:

    ```yaml
    profiles:
      github-review:
        agent: pi
        passthrough_envs: [GITHUB_TOKEN]
    ```

    Export it as `GITHUB_TOKEN` and run the profile — the agent can read PRs
    and post reviews through `gh`/the API. Nothing else is forwarded, and the
    run fails if the token isn't set.

`ap list` lists what each profile does — `(active)` marks the config's
`profile:` default, else `default`. Any option settable at the top level is
settable per profile, with top-level values as the baseline; profile `files`
entries append after the top-level user `files`, and a later mount at the same
container path replaces an earlier one — so a profile can flip a bundled
read-only mount to read/write. Profile `files` *source* may be `builtin:`
generators like `builtin:instructions` or `builtin:git-workflow`.

Define profiles in the same config file, alongside the top-level keys — see
the [config guide](config.md) and the [config reference](../reference/config.md).
