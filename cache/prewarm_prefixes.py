#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Promote compatible durable Let's Infer prefixes before launcher readiness."""

from __future__ import annotations

import argparse
import json
import pathlib
import ssl
import time
import urllib.error
import urllib.request

import letsinfer_prefix_store


def post_completion(
    base_url: str,
    model: str,
    token_ids: list[int],
    request_id: str,
    timeout: int,
    api_key: str,
    ssl_context: ssl.SSLContext,
) -> None:
    payload = {
        "model": model,
        "prompt": token_ids,
        "max_tokens": 1,
        "temperature": 0.0,
        "seed": 0,
        "ignore_eos": True,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout, context=ssl_context
        ) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(
            f"prewarm request failed with HTTP {error.code}: {detail}"
        ) from error
    if not isinstance(result.get("choices"), list):
        raise RuntimeError("prewarm completion returned no choices")


def parse_fingerprint(path: pathlib.Path) -> bytes:
    try:
        fingerprint = bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError) as error:
        raise RuntimeError(f"cannot read active fingerprint {path}: {error}") from error
    if len(fingerprint) != 32:
        raise RuntimeError(f"active fingerprint {path} is not 32 bytes")
    return fingerprint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", required=True)
    parser.add_argument("--store-root", type=pathlib.Path, required=True)
    parser.add_argument("--capacity-bytes", type=int, required=True)
    parser.add_argument("--native-capacity-bytes", type=int, required=True)
    parser.add_argument("--ttl-seconds", type=int, default=7 * 24 * 3600)
    parser.add_argument("--min-tokens", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--api-key-file", type=pathlib.Path, required=True)
    parser.add_argument("--ca-cert-file", type=pathlib.Path, required=True)
    arguments = parser.parse_args()

    api_key = arguments.api_key_file.read_text(encoding="ascii").strip()
    if len(api_key) < 32:
        raise RuntimeError("API key file is unexpectedly short")
    ssl_context = ssl.create_default_context(cafile=str(arguments.ca_cert_file))

    fingerprint = parse_fingerprint(
        arguments.store_root / ".active-fingerprint"
    )
    store = letsinfer_prefix_store.PrefixStore(
        arguments.store_root,
        arguments.capacity_bytes,
        arguments.ttl_seconds,
        arguments.min_tokens,
        0,
        False,
    )
    candidates = store.prewarm_candidates(
        fingerprint, arguments.native_capacity_bytes
    )
    started = time.perf_counter()
    warmed_bytes = 0
    warmed_tokens = 0
    capsules = 0
    for index, (tokens, has_hidden, file_bytes) in enumerate(candidates):
        # A non-capsule record must be a strict prefix so vLLM schedules one
        # real token. Exact capsules instead use their hidden row directly.
        prompt = list(tokens) if has_hidden else [*tokens, 0]
        post_completion(
            arguments.base_url,
            arguments.model,
            prompt,
            f"letsinfer-prewarm-{index:04d}",
            arguments.timeout,
            api_key,
            ssl_context,
        )
        warmed_bytes += file_bytes
        warmed_tokens += len(tokens)
        capsules += int(has_hidden)
    print(
        json.dumps(
            {
                "prewarm_records": len(candidates),
                "prewarm_capsules": capsules,
                "prewarm_tokens": warmed_tokens,
                "prewarm_bytes": warmed_bytes,
                "prewarm_elapsed_ms": (time.perf_counter() - started) * 1000.0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
