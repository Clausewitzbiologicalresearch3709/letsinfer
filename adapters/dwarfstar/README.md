# DwarfStar adapter sources

Let's Infer registers DwarfStar as an inference-engine adapter. It acquires and
verifies the exact base and DSpark drafter GGUFs, launches one manifest-owned
native recipe, persists exact DwarfStar bank payloads on NVMe, and places the
plaintext native server behind Let's Infer's TLS/API-key gateway.

Registration is not qualification. Each runtime manifest pins its exact
platform image and DwarfStar source by immutable identity. Let's Infer builds
and mounts the separately pinned core bridge; publication requires independent
target qualification.

The DwarfStar runtime owns its engine modifications and
`ds4_letsinfer_cache.*` shim. This core directory owns only
`letsinfer-bridge/`, the native binding to Let's Infer's engine-neutral store.
The runtime repository pins its exact engine source and integration. Let's
Infer treats the runtime-pack digest, digest-pinned image, and source closure
as the implementation identity; core does not interpret an engine-specific
source-revision field. Bridge ABI v2 exposes a
CRC-verified pinned region view so a multi-GiB restored payload is not copied
into a second host allocation. Large records are CRC-checked through bounded
aligned direct-I/O buffers before that lazy immutable view is exposed, so
validation does not leave the whole record resident in unified-memory page
cache; the v1 on-disk record format is unchanged.

## Architecture

```text
ds4_server.c
  -> ds4_letsinfer_cache.c
  -> libletsinfer_prefix_capi.so
  -> letsinfer-bridge/vendor/letsinfer_prefix_store
     (Let's Infer-core build snapshot)
```

- The C adapter is optional and fail-open. Disabled operation adds only
  null-pointer checks to the request path.
- The Rust bridge is loaded at runtime with `dlopen`; normal DwarfStar builds
  do not require Rust.
- Let's Infer's shared store provides checksummed page-aligned records, atomic commits,
  exact-byte LRU, sliding TTL, bounded asynchronous writes, optional RAM
  residency, and direct NVMe reads.
- Capture happens only at settled bank lifecycle points. Restore passes
  through DwarfStar's native payload validation and warm-prefix matcher. The
  record remains pinned while DwarfStar consumes its payload, then is released.

## Runtime configuration

All settings are inert unless `DS4_LETSINFER_CACHE=1`.

| Setting | Default | Purpose |
|---|---:|---|
| `DS4_LETSINFER_CACHE` | off | Enable the adapter |
| `DS4_LETSINFER_CACHE_DIR` | required | Persistent store directory |
| `DS4_LETSINFER_CACHE_LIB` | beside `ds4-server` | Bridge library path |
| `DS4_LETSINFER_CACHE_MB` | 65536 | Durable capacity in MiB |
| `DS4_LETSINFER_CACHE_TTL_S` | 604800 | Sliding expiry in seconds |
| `DS4_LETSINFER_CACHE_MIN_TOKENS` | 512 | Minimum prompt size |
| `DS4_LETSINFER_CACHE_RESIDENT_MB` | 0 | Optional host-RAM tier |
| `DS4_LETSINFER_CACHE_DIRECT` | 1 | Direct bulk reads |
| `DS4_LETSINFER_CACHE_CAPTURE` | 1 | Set to 0 for restore-only |
| `DS4_LETSINFER_CACHE_PREFIX` | 0 | Experimental prefix lookup |

Let's Infer enables the active runtime interface with `DS4_LETSINFER_CACHE=1` and
stores records below the private prefix-store mount. The runtime image
provides `/opt/dwarfstar/ds4-server`. Let's Infer builds and mounts
`/plugins/libletsinfer_prefix_capi.so` from its own pinned source, while the
manifest-pinned `adapters/dwarfstar/gateway.py` supplies the public TLS/auth
boundary. The runtime repository owns its image recipe and engine source;
Let's Infer core does not carry a parallel DwarfStar build.

## Record compatibility

The public symbols, filenames, logs, configuration variables, and directory
names use Let's Infer. The current on-disk format is v1. Records are treated as
misses unless model identity, routed quantization, serving context, payload
ABI, and token key all match exactly.

Each record contains:

1. adapter metadata and compatibility fingerprint;
2. rendered warm-prefix text;
3. exact `ds4_cont_bank_save_payload()` bytes.

## Validation

The core gate covers the Rust store, C ABI capture/read/zero-copy/reopen path,
record corruption, exact compatibility matching, and gateway behavior.
Runtime qualification must additionally prove cache cold/warm/restart
correctness, output equality, memory safety, pressure/crash recovery, and its
declared performance contract from one clean measured commit.

## Operational limits

- Capture buffers can be GB-scale at deep context. Check unified-memory
  headroom before enabling capture.
- Restore is synchronous at admission and can briefly stall other decode. It
  holds one validated record allocation while the engine rebuilds its bank;
  it does not allocate a second payload-sized copy.
- A runtime that depends on `DS4_SERVER_FORK_PARTIAL=1` must declare it in
  `engine.environment` and qualify that exact recipe; core does not set engine
  performance defaults.
- Growing conversations produce distinct records and are bounded by LRU.
- Generated `.letsinfer_prefix` records are runtime data and are not release artifacts.

## Licensing

The DwarfStar C adapter, Rust bridge, and vendored prefix store are
`AGPL-3.0-only`; the complete corresponding license is in the repository-root
`LICENSE` file. DwarfStar itself and other upstream components retain their
respective licenses. The combined runtime image therefore declares
`AGPL-3.0-only AND MIT`: AGPL applies to the Let's Infer bridge, while the
unmodified DwarfStar binary retains MIT.
