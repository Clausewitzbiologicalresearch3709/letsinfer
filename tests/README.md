# Core tests

These tests exercise Let's Infer's control-plane contracts without importing a
real model runtime. `cli/` covers manifests, adapters, lifecycle, packaging,
and installation; `benchmarks/` covers the engine-neutral runners.

`fixtures/manifests/` uses synthetic model, image, and target identities while
retaining one schema fixture per registered adapter. `fixtures/runtime-source/`
is a tiny runtime-owned source root used to prove that immutable control
bundles can combine runtime-owned artifacts with generic Let's Infer files. None
of these fixtures is discoverable as a production runtime.

Model checkpoints, engine forks, kernels, target tuning, benchmark plans,
materialized prompts, and qualification evidence do not belong here.
Runtime-specific implementation and concise public results stay in runtime
repositories; materialized benchmark inputs live only in ignored evidence.
