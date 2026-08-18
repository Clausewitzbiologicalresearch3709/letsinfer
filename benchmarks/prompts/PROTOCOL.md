# Let's Infer standard prompt protocol

These templates define Let's Infer's versioned, engine-neutral benchmark workload.
They are source templates, not requests. The core generator replaces every
placeholder and calibrates each complete rendered chat request through the
selected runtime's exact tokenizer-count capability. It writes the resulting
Markdown only into immutable benchmark evidence.

Use [`context.md`](context.md) for single-stream context, cold/hot cache, and
restart cells. Use [`concurrency.md`](concurrency.md) for each distinct client
in a connection cell. Use [`retrieval.md`](retrieval.md) at the largest safe
context to verify information near both boundaries survives prefill and cache
restore.

The runtime's `runtime.json.benchmark` contract selects supported standard
cases, context counts, concurrency, output size, and deterministic seeds. The
prompt plus output must remain inside the runtime's qualified maximum context.

Materialization rules:

1. Use the generator version named by the runtime contract.
2. Replace `{{FIXTURE_ID}}`, `{{MARKER}}`, `{{SLOT}}`, and `{{BODY}}`.
3. Derive each synthetic body deterministically from the fixture identity;
   never use
   entropy, timestamps, hostnames, or private text.
4. Calibrate the complete rendered chat request to the target count with the
   exact tokenizer/template. The prompt plus output must remain inside the
   runtime's qualified maximum context.
5. Record the file SHA-256, observed prompt count, request settings, generator
   and template hashes, runtime contract hash, tokenizer identity, and plan
   hash in the evidence materialization record.
6. Give every cell globally disjoint fixture files so a cold claim cannot
   inherit a prior prefix.

Never commit or package materialized prompts. Generated prompt bytes belong
only in ignored, immutable evidence.
