# Let's Infer CLI commands

This is the public surface of the source parser. Confirm it against
`letsinfer COMMAND --help` when the CLI changes.

## Site and coordinator authority

- `letsinfer setup [--name NAME] [--address ADDRESS] [--json]`
- `letsinfer site status [--json]`
- `letsinfer site move [--apply ...]`
- `letsinfer member list|prepare|join|invite|approve|sync|drain|resume|remove`
- `letsinfer topology show|probe|plan`
- `letsinfer alias list|set|remove`
- `letsinfer pair [--timeout SECONDS] [--role viewer|operator|administrator]`
- `letsinfer controllers list [--json]`
- `letsinfer controllers forget NAME_OR_ID`
- `letsinfer key create|list|show|rotate|revoke|policy`
- `letsinfer audit list|show|verify|export`
- `letsinfer exposure [--json]`
- `letsinfer expose [--json]`
- `letsinfer unexpose [--json]`

The first setup creates the coordinator. Every command leaf has an enforced
`coordinator`, `member`, or `all` scope. Site mutations, key policy, sensitive
audit/controller reads, and exposure are coordinator-only and audited. They do
not proxy through a member.

`member drain` stops new gateway admission to one member while preserving
in-flight requests and the running engine. `member resume` restores admission.
For distributed placements, any required drained member blocks new group work;
replicas continue on active members.

## Discovery and artifacts

- `letsinfer releases`
- `letsinfer engines`
- `letsinfer hardware [--json] [--catalog LOCATION]`
- `letsinfer runtimes`
- `letsinfer pack SOURCE --output OUTPUT`
- `letsinfer derive RUNTIME --name NAME [--engine ENGINE] [--target TARGET] [--without FLAG]... [--port PORT] -- [ENGINE_ARGS...]`
- `letsinfer inspect RUNTIME [--engine ENGINE] [--target TARGET] [--port PORT] [--command] [--diff] [--json]`

Engines currently registered by the parser are `dwarfstar`, `llama.cpp`,
`sglang`, and `vllm`. `pack` writes the deterministic artifact at the exact
output path. `inspect --command` renders shell-quoted text for display only;
Let's Infer stores and runs argv.

## Runtime selection and verification

- `letsinfer upgrade RUNTIME [--engine ENGINE] [--target TARGET] [--catalog LOCATION] [--to SOURCE] [--dry-run]`
- `letsinfer rollback RUNTIME [--engine ENGINE] [--target TARGET] [--dry-run]`
- `letsinfer verify MODEL [--engine ENGINE] [--target TARGET] [--model-cache PATH] [--plugin-root PATH] [--source-only]`
- `letsinfer acquire MODEL [--engine ENGINE] [--target TARGET] [--model-cache PATH]`
- `letsinfer benchmark RUNTIME [--c1] [--c2] [--c4] [--c8] [--c16] [--32k] [--64k] [--128k] [--256k] [--list]`

`--source-only` skips target model, installed plugin, and image checks; it is
not runtime qualification. `--to` is the explicit movement path for pinned,
local, or derived selection policies.
`benchmark` delegates to the generic isolated matrix and never accepts engine
configuration or runtime-provided code. Its concurrency and context selectors
form a cross product. The runtime declares the standard workload in
`runtime.json`; Let's Infer materializes exact prompts through the adapter's
tokenizer-count capability into evidence.

## Install

```text
letsinfer install MODEL_OR_RUNTIME
  [--engine ENGINE] [--target TARGET] [--catalog LOCATION]
  [--port PORT] [--name NAME]
  [--model-cache PATH] [--plugin-root PATH]
  [--store-root PATH] [--runtime-cache-root PATH]
  [--api-key-file PATH] [--tls-cert-file PATH] [--tls-key-file PATH]
  [--watchdog-data-root PATH] [--watchdog-listen ADDRESS]
  [--watchdog-port PORT]
  [--watchdog-cert-file PATH] [--watchdog-key-file PATH]
  [--watchdog-controller-ca-file PATH] [--watchdog-controller-ca-key-file PATH]
  [--watchdog-local-controller-cert-file PATH]
  [--watchdog-local-controller-key-file PATH]
  [--wheel PATH] [--config PATH]
  [--no-download] [--no-build-image] [--no-service] [--no-start]
```

`MODEL_OR_RUNTIME` may be an installed model/runtime identity, catalog model,
runtime source directory, `.letsinfer` archive, or supported digest-pinned OCI
reference. Let's Infer core has no built-in model registry.
Catalog model installation automatically resolves the compatible hardware
target. `--target` is retained for explicit development and diagnostics, not
ordinary installation; multiple automatic matches are a catalog error.
Missing exact model artifacts and registry image layers download by default
into their native shared content stores. `--no-download` requires them to
exist already. `--no-build-image` requires the exact image to exist.
`--no-service` skips user-systemd installation;
`--no-start` installs and enables without starting.

Normal service installation requires systemd user lingering and checks it
before mutation. `--no-service` is appropriate for an activation-blocked
artifact inspection or explicit qualification workflow; it does not create a
boot-persistent service.

## Serve and inspect service state

```text
letsinfer serve MODEL
  [--engine ENGINE] [--target TARGET] [--port PORT] [--name NAME]
  [--model-cache PATH] [--plugin-root PATH]
  [--store-root PATH] [--runtime-cache-root PATH]
  [--api-key-file PATH] [--tls-cert-file PATH] [--tls-key-file PATH]
  [--evidence-dir PATH] [--qualification-mode] [--dry-run]
```

Normal `serve` requires a qualified recipe. `--qualification-mode` is the
only candidate launch path and requires a new explicit evidence directory.

- `letsinfer status [--name NAME] [--config PATH] [--json]`
- `letsinfer doctor [--config PATH] [--json] [--require-stable]`
- `letsinfer logs [--config PATH] [--tail N] [--follow]`
- `letsinfer start [MODEL] [--config PATH]`
- `letsinfer restart [MODEL] [--config PATH]`
- `letsinfer recover [MODEL] [--config PATH]`
- `letsinfer stop [--name NAME] [--config PATH]`

`doctor --require-stable` treats candidate/publication state as failure.
`start` and `restart` refuse a durable protection trip. `recover` is the sole
command that acknowledges the trip before starting the engine.

## Removal

- `letsinfer uninstall [--config PATH] [--purge-runtime-plugins] [--purge-credentials] [--purge-control-bundle] [--purge-watchdog-runtime]`

Without purge flags, uninstall preserves model and cache data. Resolve and
confirm every purge target before using a purge option.

## Systemd internals

- `letsinfer service-start --config PATH`
- `letsinfer service-stop --config PATH`

These commands are unit entry points. Operate the service with `install`,
`serve`, `restart`, `stop`, and `uninstall`, not by calling them manually.
`letsinfer.service` owns the resident Watchdog, `letsinfer-engine.service` owns the
guarded engine lifecycle, and `letsinfer-recovery.timer` evaluates ordinary
recovery. A valid protection/OOM latch prevents automatic engine relaunch
until explicit acknowledgement with `letsinfer recover`.
