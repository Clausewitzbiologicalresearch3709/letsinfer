# Source release

[Back to documentation](../README.md)

Let's Infer source releases are built from an explicit public allowlist. Local
agent policy, handoff state, context, scratchpads, credentials, evidence,
caches, nested Git metadata, and generated output are never publication
inputs.

Build twice and require byte equality:

```bash
bin/letsinfer-source-archive build --source . --output /tmp/letsinfer-a.tar.gz
bin/letsinfer-source-archive build --source . --output /tmp/letsinfer-b.tar.gz
cmp /tmp/letsinfer-a.tar.gz /tmp/letsinfer-b.tar.gz
bin/letsinfer-source-archive verify /tmp/letsinfer-a.tar.gz
```

Each archive has one `letsinfer/` root and an embedded
`SOURCE-MANIFEST.json`. The manifest records every file's normalized mode,
byte length, and SHA-256. The verifier rejects duplicate or unsafe paths,
links, special members, metadata drift, unmanifested files, missing files, and
content mismatches.

Before publication, scan the complete working tree and the unpacked public
tree for every retired namespace or prohibited release term. Repeat
`--forbid` for each term; the tool reports only term hashes so release logs do
not reintroduce retired names:

```bash
bin/letsinfer-release-audit --forbid RETIRED_TERM . --json
bin/letsinfer-release-audit --forbid RETIRED_TERM /tmp/unpacked/letsinfer --json
```

Create the public repository from the verified unpacked tree. Initialize it as
a new repository and make its first commit there; never push or graft the
private experimental repository's history. Publication additionally requires
the normal test, license/privacy, runtime OCI, signed-catalog, and portable
evidence gates.
