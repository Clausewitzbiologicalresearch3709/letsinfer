---
name: cli
description: Use and troubleshoot the Let's Infer command-line interface for runtime discovery, packaging, derivation, inspection, installation, qualification serving, upgrades, verification, service operations, credentials, and removal. Use whenever an agent needs to choose or execute a letsinfer CLI command or explain its options.
---

# Use the Let's Infer CLI

Read [`references/commands.md`](references/commands.md) for the complete public command and option surface before constructing a command. Prefer the installed `letsinfer`; use repository `bin/letsinfer` only for source-tree development.

## Work safely

1. Read the applicable public documentation and any locally supplied repository
   policy, then inspect live state before changing it.
2. Use `hardware --json`, `inspect --json`, `status --json`, `doctor --json`, and available `--dry-run` paths before activation, upgrade, rollback, or service changes.
3. Let automatic target selection match capabilities. Multiple matches mean the catalog is ambiguous and must be corrected; do not delegate ordinary target selection to the user. An explicit development `--target` never bypasses compatibility.
4. Treat local/derived runtimes as unqualified candidates. Only `serve --qualification-mode --evidence-dir NEW_PATH` may launch one, and it does not install, promote, or make it boot-persistent.
5. Keep API keys, TLS keys, and Watchdog credentials in private files. Never print or embed their contents in commands, manifests, logs, or evidence.
6. Preserve model weights, runtime objects, cache data, and credentials unless the user explicitly requests the corresponding purge option.
7. Before installing boot-persistent user services, require systemd user
   lingering. Installation must fail before mutation when lingering is not
   available.

## Choose the operation

- Configure the logical site: `setup`, `site status`, `member`, `topology`.
- Discover: `engines`, `releases`, `hardware`, `runtimes`.
- Create/distribute: `pack`, `derive`, `inspect`.
- Resolve lifecycle: `install`, `upgrade`, `rollback`, `acquire`, `verify`.
- Run/diagnose: `serve`, `status`, `doctor`, `logs`, `start`, `restart`,
  `recover`, `stop`.
- Policy and trust: `pair`, `controllers`, `key`, `alias`, `audit`, `exposure`.
- Remove: `uninstall`.
- Do not invoke `service-start` or `service-stop` directly; they are systemd internals.

Use `stop --name <container>` to remove only a named qualification container
while keeping the resident Watchdog active. Use `stop` without `--name` for
the configured service lifecycle.

Treat a protection trip as an operator decision. `start` and `restart` never
clear one; use `recover` only after inspecting the cause and intentionally
acknowledging the durable trip.

For derivation, put Let's Infer options before `--` and raw upstream engine arguments after it. Matching option names replace inherited clauses, unknown clauses append, and repeatable clauses replace as a group. Use repeatable `--without=--flag` to remove inherited flags. Let's Infer passes argv directly and does not maintain upstream flag schemas. Core-owned model, listener, TLS, authentication, and safety arguments cannot be changed.

After any mutation, run `status --json`, `verify`, and `doctor --json` as applicable and verify the exact runtime, image, model, container lifecycle, Watchdog state, and service enablement.

Respect the scope label on every command. Coordinator-only commands never run
from or proxy through a member. API-key create/rotate output is secret material
shown once; do not copy it into a command, log, source file, or evidence.

For planned member maintenance, use coordinator-only `member drain MEMBER_ID`
before taking the node out of service and `member resume MEMBER_ID` afterward.
Drain affects only new admission: it does not stop the engine or cancel active
requests. Confirm the resulting member state and the placement behavior before
continuing.

Watchdog is the always-running process; the inference engine may legitimately
be stopped, qualification-held, or recovery-latched. Do not interpret an
inactive engine as zero Let's Infer runtime memory or silently start another model.
The Watchdog user unit must stay in the host user namespace so its exact-process
pidfd containment works; do not add systemd filesystem namespace directives as
generic hardening.
