# Upgrades and rollback

[Back to documentation](../README.md)

Upgrade follows the policy recorded at installation:

- `recommended` follows the catalog's current recommended engine;
- `engine:NAME` stays on that engine's release line;
- `pinned`, `local`, and `derived` do not move without `--to`.

Preview an upgrade:

```bash
letsinfer upgrade example-model --dry-run
```

Apply it:

```bash
letsinfer upgrade example-model
```

Select an explicit immutable artifact instead of the recorded policy:

```bash
letsinfer upgrade example-model \
  --to ghcr.io/example/runtime@sha256:...
```

Let's Infer verifies and stages the new runtime before stopping the old service.
It then performs the same transactional service replacement as installation:
exact artifacts, model, image, target, memory, Watchdog, health, authentication,
and model identity must pass. A failed activation restores the prior config,
units, immutable control bundle, and running service.

Successful selections retain the previous runtime object and receipt:

```bash
letsinfer rollback example-model --dry-run
letsinfer rollback example-model
```

Rollback reuses the retained immutable object; it does not resolve a mutable
tag or reinterpret the prior catalog. Derived candidates do not automatically
rebase when their parent is upgraded. Create a new derivation and inspect its
resolved diff instead.
