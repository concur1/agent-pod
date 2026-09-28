---
title: Pi settings
---

# Pi settings

Pi settings (including its `packages` list) are baked into the sandbox image
at build time:

```sh title="Settings file"
ap run fixes --settings-file ./settings.json
```

Defaults to `~/.pi/settings.json` if the flag is omitted.

You can also set a default path in your config:

```yaml title=".agent-pod.yaml"
settings_file: ~/.pi/settings.json
```

## Next

- [**Git work**](git.md) — keep the agent on its own private branch.
