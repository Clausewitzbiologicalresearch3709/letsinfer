#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Materialize Let's Infer's deterministic, model-neutral benchmark prompts.

Runtime packs declare only a versioned workload contract.  The selected engine
adapter supplies an exact rendered-chat token counter backed by the runtime's
actual model/tokenizer.  Generated prompts and their complete identity record
live in benchmark evidence, never in the runtime pack.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from collections.abc import Callable, Iterable
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.runtime_packs import (  # noqa: E402
    BENCHMARK_GENERATOR,
    BENCHMARK_GENERATOR_VERSION,
    BENCHMARK_RENDER_CONTRACT,
    BENCHMARK_SUITE,
    BENCHMARK_TOKENIZER_CAPABILITY,
    canonical_bytes,
    sha256_file,
    validate_benchmark_contract,
)


PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"
TEMPLATES = {
    1: PROMPTS / "context.md",
    2: PROMPTS / "concurrency.md",
    4: PROMPTS / "concurrency.md",
    8: PROMPTS / "concurrency.md",
    16: PROMPTS / "concurrency.md",
}
SOURCE_WORDS = (
    "analysis",
    "archive",
    "boundary",
    "context",
    "detail",
    "evidence",
    "inference",
    "marker",
    "observation",
    "record",
    "reference",
    "sequence",
    "signal",
    "summary",
    "verification",
    "window",
)


class PromptGenerationError(ValueError):
    """A benchmark contract could not be materialized exactly."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_text(seed: int, minimum_chars: int) -> str:
    """Return a stable synthetic document with no model-specific content."""
    state = (seed & 0xFFFFFFFF) or 0x9E3779B9
    parts: list[str] = []
    length = 0
    sentence = 0
    while length < minimum_chars:
        words: list[str] = []
        for _ in range(18):
            state ^= (state << 13) & 0xFFFFFFFF
            state ^= state >> 17
            state ^= (state << 5) & 0xFFFFFFFF
            words.append(SOURCE_WORDS[state % len(SOURCE_WORDS)])
        line = " ".join(words).capitalize() + f" ({sentence:06d}).\n"
        parts.append(line)
        length += len(line)
        sentence += 1
    return "".join(parts)


def _render(
    template: str,
    *,
    fixture_id: str,
    marker: str,
    slot: int,
    body: str,
) -> str:
    rendered = (
        template.replace("{{FIXTURE_ID}}", fixture_id)
        .replace("{{MARKER}}", marker)
        .replace("{{SLOT}}", str(slot))
        .replace("{{BODY}}", body)
    )
    if "{{" in rendered or "}}" in rendered:
        raise PromptGenerationError("benchmark template has an unresolved placeholder")
    return rendered


def _calibrate(
    *,
    template: str,
    fixture_id: str,
    marker: str,
    slot: int,
    target: int,
    seed: int,
    count_tokens: Callable[[str], int],
) -> tuple[str, int]:
    """Calibrate one prompt to an exact rendered-chat count or fail closed."""
    if target <= 0:
        raise PromptGenerationError("target prompt tokens must be positive")
    source = _source_text(seed, max(4096, target * 12))

    def candidate(characters: int, filler: str = "") -> str:
        return _render(
            template,
            fixture_id=fixture_id,
            marker=marker,
            slot=slot,
            body=source[:characters] + filler,
        )

    low = 0
    high = min(len(source), max(4096, target * 6))
    high_count = count_tokens(candidate(high))
    while high_count < target and high < len(source):
        high = min(len(source), high * 2)
        high_count = count_tokens(candidate(high))
    if high_count < target:
        raise PromptGenerationError(
            f"synthetic source cannot reach {target} rendered tokens"
        )

    closest_text = candidate(high)
    closest_count = high_count
    while low <= high:
        middle = (low + high) // 2
        text = candidate(middle)
        observed = count_tokens(text)
        if abs(observed - target) < abs(closest_count - target):
            closest_text, closest_count = text, observed
        if observed == target:
            return text, observed
        if observed < target:
            low = middle + 1
        else:
            high = middle - 1

    # Boundary merges can skip the target at a raw character boundary.  Try a
    # small deterministic suffix vocabulary; this is still exact calibration,
    # and failure never falls back to an approximate count.
    base_chars = max(0, high)
    base_text = candidate(base_chars)
    base_count = count_tokens(base_text)
    if base_count == target:
        return base_text, base_count
    if base_count < target:
        missing = target - base_count
        for atom in (" x", " 0", " .", "\nrecord"):
            left, right = 0, missing * 4 + 16
            while left <= right:
                amount = (left + right) // 2
                text = candidate(base_chars, atom * amount)
                observed = count_tokens(text)
                if observed == target:
                    return text, observed
                if observed < target:
                    left = amount + 1
                else:
                    right = amount - 1

    raise PromptGenerationError(
        f"cannot calibrate {fixture_id} to exactly {target} rendered tokens; "
        f"closest observation was {closest_count}"
    )


def contract_cells(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return cell metadata without materializing prompt bytes."""
    validate_benchmark_contract(contract)
    request = contract["request"]
    cells: dict[str, dict[str, Any]] = {}
    for case in contract["cases"]:
        for concurrency in case["concurrencies"]:
            name = f"{case['id']}-c{concurrency}"
            cells[name] = {
                "name": name,
                "context": case["id"],
                "concurrency": concurrency,
                "prompt_tokens": case["prompt_tokens"],
                "max_tokens": request["output_tokens"],
            }
    return cells


def materialize(
    contract: dict[str, Any],
    output: pathlib.Path,
    count_tokens: Callable[[str], int],
    *,
    model_id: str,
    model_revision: str,
    selected_cells: Iterable[str] | None = None,
) -> pathlib.Path:
    """Write an exact prompt plan and return its path."""
    validate_benchmark_contract(contract)
    output = output.resolve(strict=False)
    if output.exists():
        raise PromptGenerationError(f"refusing existing materialization: {output}")
    selected = set(selected_cells or contract_cells(contract))
    known = set(contract_cells(contract))
    unknown = sorted(selected - known)
    if unknown:
        raise PromptGenerationError(
            "unknown benchmark cell(s): " + ", ".join(unknown)
        )
    if not selected:
        raise PromptGenerationError("no benchmark cells selected")
    output.mkdir(parents=True)
    prompt_root = output / "prompts"
    prompt_root.mkdir()

    fixtures: list[dict[str, Any]] = []
    contexts: list[dict[str, Any]] = []
    request = contract["request"]
    for case in contract["cases"]:
        cell_map: dict[str, list[str]] = {}
        for concurrency in case["concurrencies"]:
            cell_name = f"{case['id']}-c{concurrency}"
            if cell_name not in selected:
                continue
            template_path = TEMPLATES.get(concurrency, PROMPTS / "concurrency.md")
            template = template_path.read_text(encoding="utf-8")
            names: list[str] = []
            for slot in range(concurrency):
                fixture_id = f"{cell_name}-s{slot:02d}"
                marker_digest = sha256_bytes(
                    f"{case['seed']}\0{fixture_id}".encode("utf-8")
                )[:24]
                marker = f"LETSINFER-{marker_digest.upper()}"
                text, observed = _calibrate(
                    template=template,
                    fixture_id=fixture_id,
                    marker=marker,
                    slot=slot,
                    target=case["prompt_tokens"],
                    seed=case["seed"] + slot + concurrency * 1009,
                    count_tokens=count_tokens,
                )
                path = prompt_root / f"{fixture_id}.md"
                path.write_text(text, encoding="utf-8")
                relative = path.relative_to(output).as_posix()
                fixtures.append(
                    {
                        "name": fixture_id,
                        "path": relative,
                        "sha256": sha256_file(path),
                        "expected_prompt_tokens": observed,
                    }
                )
                names.append(fixture_id)
            cell_map[f"c{concurrency}"] = names
        if cell_map:
            contexts.append(
                {"name": case["id"], "cells": cell_map, "sealed_c1": None}
            )

    public_rows = [
        {
            "relative_path": row["path"],
            "sha256": row["sha256"],
            "expected_prompt_tokens": row["expected_prompt_tokens"],
        }
        for row in fixtures
    ]
    digest = hashlib.sha256()
    for row in sorted(public_rows, key=lambda item: item["relative_path"]):
        digest.update(row["relative_path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(row["sha256"].encode("ascii"))
        digest.update(b"\n")
    prompt_set = digest.hexdigest()
    template_hashes = {
        path.name: sha256_file(path)
        for path in sorted(set(TEMPLATES.values()), key=lambda item: item.name)
    }
    identity = {
        "schema_version": 1,
        "suite": BENCHMARK_SUITE,
        "generator": {
            "id": BENCHMARK_GENERATOR,
            "version": BENCHMARK_GENERATOR_VERSION,
            "sha256": sha256_file(pathlib.Path(__file__).resolve()),
        },
        "templates": template_hashes,
        "benchmark_config_sha256": sha256_bytes(canonical_bytes(contract)),
        "tokenizer": contract["tokenizer"],
        "render_contract": BENCHMARK_RENDER_CONTRACT,
        "prompt_set_sha256": prompt_set,
    }
    plan = {
        "schema_version": 1,
        "model_id": model_id,
        "model_revision": model_revision,
        "tokenizer_identity": contract["tokenizer"],
        "sample_interval_seconds": contract["sample_interval_seconds"],
        "request": {
            "max_tokens": request["output_tokens"],
            "min_completion_tokens": request["min_completion_tokens"],
            "require_natural_stop": request["require_natural_stop"],
            "temperature": request["temperature"],
            "options": {"seed": request["seed"]},
        },
        "prompt_set_sha256": prompt_set,
        "fixtures": fixtures,
        "contexts": contexts,
        "materialization": identity,
    }
    plan_path = output / "runtime-matrix.json"
    plan_path.write_bytes(canonical_bytes(plan))
    identity["plan_sha256"] = sha256_file(plan_path)
    (output / "materialization.json").write_bytes(canonical_bytes(identity))
    return plan_path
