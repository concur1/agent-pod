# agent-pod todo

## CLI / UX

- [ ] launch screen: `build_image` echoes the generated Dockerfile (`--- Generated Dockerfile ---` in `container/builder.py`) — instead show nothing, or the run plan (`ap plan`) for a built-in agent
- [x] ~~proper logging~~ — done: stdlib `logging` in `agent_pod/log.py`; warnings/errors go to stderr with the existing `Warning:`/`Error:` prefixes, `-v/--verbose` enables DEBUG (subprocess commands + tracebacks)
- [x] ~~error boundary in main()~~ — done: `main()` wraps dispatch, catches known failures (invalid config, build/podman failures surface as SystemExit) and prints one clean collapsed `Error:` line + non-zero exit instead of a raw traceback; full traceback only under `-v`
- [ ] `ap doctor` / preflight command: run the podman / rootless / git / network / nix-in-docker checks the build path already performs, with actionable messages — so the first `ap run` fails with "install podman" rather than a slow build dying at step 3; the checks exist scattered in the build path
- [] tidy up the cli — [decided] the positional IS the profile, not the harness (`ProfileConfig.agent` stays: the profile's `agent` is the default harness when that profile is active). `ap run <profile>` selects the profile (the `--profile` flag goes away), and the harness comes from the profile's `agent`, else the config's default `agent`, with `--agent <name>` to override explicitly. `ap run fixes` = fixes' own agent (or config default); `ap run fixes --agent pi` = pi under the fixes profile's overrides; `ap run` = config default agent under the config default profile. Bashing in is a real subcommand, not an alias: `ap shell <profile>` runs the same harness but replaces the entrypoint with an interactive bash shell, and the `run --bash` flag is removed
- [x] ~~remove the disposable-worktree feature~~ — actually removed for real: host-side worktrees are gone (no more `ap worktree keep|integrate`, no host `worktrees/` state, no auto-tidy). In a git repo the host mounts just the repo's `.git` at `/repo/.git` (`ephemeral: true` in config, default false) and the **container** creates its own per-session worktree at `/sandbox` on `agent/<profile>/<session>`, forked from the host HEAD; only committed files ever reach the host. On exit `git worktree prune` drops the now-container-owned metadata (the old broken-host-pointer problem: worktrees referencing host-only paths are gone). Reviewing a session is a plain host-side `git merge agent/<profile>/<session>`.
- [ ] shell into a live session: `ap exec <agent> <session> -- <cmd>` (attach only to a running container; dead sessions go via `sessions --rm`, re-entering a session's state is `run --session <name>` again)
- [ ] interactive session picker — [ui/ux needs thought] fuzzy list of profiles to shell into, with a live-session indicator per profile; once a profile is selected, choose re-enter a live session or start a new one under that profile
- [ ] config to choose the shell in a profile
- [ ] check for profile name conflicts (with agent names, subcommand names, session names)
- [x] ~~move hardcoded constants into config/types section~~ — done: `STATE_DIR` + `DEFAULT_PROFILE` live in `types.py`, replacing the `~/.config/container-agents` literal that was hardcoded in `cli.py`, `runner.py`, `loader.py`, and `prompts/loader.py`

## Config & profiles

- [ ] make the agent name and email for git configrable.
- [ ] research profile: create one (e.g. an example `research:` profile — agent + context files for web-research work, alongside `audit`/`daily` in the docs)
- [ ] allow configuring the agent's JSON settings inline in a profile (a `settings:` dict), not just via a `settings_file` host path
- [ ] per-profile flake overrides: profiles only allow run-level keys (agent, context_files, files, extra_args, settings_file) — add `allow_unfree`, `permitted_insecure`, `extra_packages` to ProfileConfig so a profile can build with unfree/insecure gates open
- [x] ~~config options for allow_unfree / allow_vulnerabilities~~ — done: `allow_unfree` + `permitted_insecure` (version-pinned, default-deny), see README
- [ ] ADR on how profile settings merge: should profiles be self-contained, or inherit settings from elsewhere?

## Features

- [ ] review/merge-conflict feature = a bundled profile, not new code — a `review` profile that uses profile→agent to pick the harness and mounts a review/merge-instructions context file (reuses builtin:git-workflow skill). Deliver: (a) review prompt file, (b) example `review:` profile in the docs/init, (c) test `ap run review` against a repo with conflicts
- [ ] analytics agent = a bundled profile, not new code — a profile that mounts session state read-only (`~/.config/container-agents/<agent>/<session>/` state dirs + `agent/<profile>/<session>` branches) and a prompt file to cluster recurring errors from transcripts. Deliver: (a) analyst prompt file, (b) example `analytics:` profile in docs/init, (c) session-log capture — today only pi's `sessions` state dir persists; `ap` never logs the agent's terminal output, so verify/capture transcripts across all agents before the analyst has anything to read
- [ ] pi extensions in a named volume to improve startup time? — open question; runtime extensions now bake into the image (ADR 003), so a volume likely only helps the nix/buildah cache instead

## Docs & maintenance

- [ ] ADR status update: ADR 004 is marked "spike + implementation pending" but all agents now build from named Nix flakes with no install_script — it's implemented; update the status so the repo docs aren't stale
- [ ] further simplify the code, needs manual review

## Tests

- [ ] prune redundant/duplicate tests (overlapping config, plan, and container suites) as part of the code-simplification pass
- [ ] integration test(s) that run podman and/or docker — should be runnable inside a sandbox (might need switching to docker for docker-in-docker)
