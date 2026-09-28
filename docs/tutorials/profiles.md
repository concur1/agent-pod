---
title: Use a profile
---

# Use a profile

**Follow the [quickstart](quickstart.md) first** — the same machinery powers
profiles.

A **profile** is a named bundle of overrides — a different agent, extra
flags, different file mounts. The `default` profile is active unless you name
one:

```sh title="Run a profile"
ap run fixes
```

The harness agent comes from the profile's `agent` (else the config's
`agent`), so `ap run fixes` may launch a completely different tool than plain
`ap run`. Force the harness with `--agent`:

```sh title="Override the harness"
ap run fixes --agent pi
```

See which profiles exist and what each one overrides:

```sh title="List profiles"
ap list
```

## Next

[Persist state with a session](sessions.md) — keep a profile's work across
runs. To *define* your own profiles, see the
[how-to guide](../guides/config.md) and the
[profile recipes](../guides/recipes.md).
