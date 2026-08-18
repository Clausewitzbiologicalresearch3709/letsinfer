# Sites, members, and trust

[Back to documentation](../README.md)

A Let's Infer site is the stable identity presented to users and API clients.
It may contain one machine, independent model placements, replicas, or a
runtime-qualified distributed engine group. Physical machines are members.
The first `letsinfer setup` creates the site and makes that member its
coordinator.

## Coordinator authority

The coordinator owns the site key, SQLite authority, membership, controller
roles, inference API-key policy, audit chain, topology, placements, aggregate
telemetry, and the OpenAI-compatible LAN gateway. It is also available for
inference work. The initial release has one explicit coordinator and no
automatic election or mutation forwarding.

Every CLI leaf declares one execution scope:

- `coordinator` commands run only on the coordinator;
- `member` commands run only on a non-coordinator member; and
- `all` commands run in either role.

Scope is checked before a handler or side effect runs. A rejected command says
where the coordinator is but is never proxied. Site mutations and sensitive
reads are coordinator-only. Mutation and denial events are written to the
tamper-evident SQLite audit chain without secrets, prompts, or responses.

## Discovery is not authorization

The site service advertises `_letsinfer._tcp` with only public identity and
pairing hints. It does not disclose credentials, models, telemetry, or
administrative state. Trust is established separately:

- A fresh Spark on a verified direct ConnectX route can be added from the Mac
  app with **Add to Home**. The explicit click authorizes one key-bound invite.
  Both sides verify the exact direct interface, peer route, certificate, site
  key, signed adoption document, lifetime, and one-use nonce. No code is used.
- A LAN or remote member uses a short-lived eight-digit invite and a separate
  six-digit human comparison. Attempts, payload size, workers, and per-peer
  rate are bounded.
- An already configured site is never adopted silently. The app offers
  **Connect to this site** or an explicit **Move into Home** transaction. A
  move preserves physical installation, model, runtime, and cache data but
  replaces site authority, controllers, API credentials, and service state.
  Active work or other source-site members block the move.

The Mac app holds its own non-exportable P-256 controller key. Pairing issues a
site-scoped certificate after setup-code and human-comparison checks. Viewer,
operator, and administrator roles control telemetry, lifecycle, and sensitive
administration respectively. Revocation is registry-backed and immediately
removes the controller from Watchdog's derived allowlist.

Viewers are read-only. Operators can start, stop, restart, and explicitly
recover placements. Administrators can also install a runtime, create an
immutable pending topology plan, manage membership and public exposure, and
create, edit, rotate, or revoke inference keys. These are fixed typed API
operations; the controller protocol has no arbitrary shell or command route.
Every mutation and denial is attributed to the controller and correlated in
the site audit chain.

## Topology and placement

Each member signs bounded hardware, capacity, health, and link facts. The
coordinator verifies the member certificate, freshness, and physical link
proof before building the topology graph. Catalog targets declare whether a
model runs on one member, as replicas, or as one distributed engine group.
Target resolution must yield exactly one qualified placement; it never silently
changes the model, engine, quantization, topology, or recipe.

The same authenticated member facts carry bounded private inventory for paired
controllers: machine, board, firmware, CPU, GPU, NVMe, operating-system, and
network identity. This replaces SSH as the normal Mac app inventory path. The
controller's operational view returns one current placement per model while
retaining predecessor rows in SQLite for audit and recovery history.

For replicas, the coordinator gateway chooses among healthy placements using
safe concurrency, queue depth, pressure, temperature, and prefix-cache
locality. For a distributed target it sends the request only to the declared
engine coordinator. The runtime owns engine-specific worker communication.
Group failure is whole-group for distributed targets and independent for
replicas.

Routing health comes from fresh, signed member facts rather than the static
installation record. Memory pressure uses the same available-memory warning
floor as Watchdog. ConnectX proofs are renewed continuously; if either
direction expires or fails its runtime interconnect contract, new distributed
requests stop until the authenticated topology is healthy again. Prefix
affinity is a bounded, expiring gateway hint learned only from completed
requests, never a correctness requirement.

An administrator may drain a member for maintenance. Draining changes request
admission only: new requests avoid that member, in-flight requests finish, and
the engine is not implicitly stopped. Replica pools continue on active
members. A distributed placement fails closed for new work until every member
required by its qualified topology is active again. Resuming the member
restores admission without changing its runtime configuration.

## Network planes

The control and inference planes remain separate:

- The private control plane carries pairing, membership, topology, Watchdog
  telemetry, administration, and orchestration over provisioned mutual TLS. It
  is never public.
- The inference plane advertises `http://<coordinator>.local:8000/v1` through
  mDNS and exposes only that stable OpenAI-compatible surface plus health.
  Scoped bearer keys may limit models, expiry, request and token
  rates, concurrent requests, context, tenant, and application.

Local clients connect to the coordinator gateway. `letsinfer expose` may
explicitly publish that fixed gateway through Tailscale Funnel on HTTPS 443.
It fails if provider state is pre-existing or ambiguous and records the exact
configuration hash for rollback. Site, controller, Watchdog, and engine ports
are never forwarded.

LAN inference HTTP is intentionally certificate-free for compatibility with
standard OpenAI clients. It belongs on a trusted local network because prompts
and bearer keys are not encrypted on that hop. Control-plane credentials and
routes are never accepted by the inference listener.

The private controller exposes bounded telemetry schema 2. It retains complete
per-member logical counters and five minutes of aggregate history, excludes
stale members from live gauges/rates, and compensates a member counter reset
without losing the prior logical total. Aggregate output TPS is the sum of
member wall-clock deltas; decode/prefill rates and TTFT are derived only from
exact token and gateway timing windows. Unavailable values remain explicit.

## Core commands

```text
letsinfer setup --name Home
letsinfer site status
letsinfer member list
letsinfer member invite --mode lan
letsinfer member invite --mode connectx --candidate-endpoint URL \
  --candidate-fingerprint SHA256 --interface NAME
letsinfer member approve MEMBER_ID COMPARISON_CODE
letsinfer member sync
letsinfer member drain MEMBER_ID
letsinfer member resume MEMBER_ID
letsinfer topology show
letsinfer topology probe LEFT_MEMBER RIGHT_MEMBER --kind connectx
letsinfer topology plan MODEL --catalog LOCATION
letsinfer pair --role administrator
letsinfer key create NAME --model MODEL --concurrency N
letsinfer audit verify
letsinfer exposure
letsinfer start MODEL
letsinfer restart MODEL
letsinfer recover MODEL
```

The Mac app normally drives discovery, fresh ConnectX adoption, pairing, and
connect-versus-move. The CLI exposes the same strict primitives for automation
and diagnostics.
