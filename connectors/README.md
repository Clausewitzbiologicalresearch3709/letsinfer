# Engine connectors

`connectors/` contains optional, engine-facing integrations for capabilities
owned by Let's Infer core. A connector is a narrow adapter; it is not a runtime
recipe, model implementation, benchmark record, or place to carry an engine
fork.

The current prefix connector maps an engine's cache lifecycle to the shared
Rust store under [`cache/`](../cache/). The store owns durable record format,
integrity, atomic commit, lookup, and eviction. The connector owns only the
engine callbacks needed to capture, restore, and release that engine's state.

## Boundary

- Core and the shared cache define engine-neutral policy and durable formats.
- A connector must bind the exact model, tokenizer, engine ABI, cache layout,
  parallelism, dtype, and state format into compatibility checks.
- Exact token comparison is authoritative; hashes are indexes, not proof.
- Incomplete, corrupt, stale, or incompatible records are cache misses.
- A connector must never silently recompute only part of a hybrid state and
  report a hit.
- Runtime-specific patches, kernels, images, and target recipes belong in the
  independent runtime pack that qualifies them.

Connectors are optional. An engine without one still serves normally through
its runtime adapter; it simply does not receive that connector's capability.
Runtime packs declare and pin any connector they require.

## Validation

Changes must cover record round trips, exact-token authority, compatibility
mismatch, corruption and incomplete-record misses, bounded concurrency, and
restart restore. Any performance claim belongs to the runtime's immutable
benchmark evidence, not this directory.
