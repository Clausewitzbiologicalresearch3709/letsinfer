#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Determinism and evidence tests for the standard prompt generator."""

from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest

from benchmarks import prompt_generator


def contract() -> dict[str, object]:
    return {
        "schema_version": 1,
        "suite": "letsinfer-standard-context-v1",
        "generator": {"id": "letsinfer-synthetic-document", "version": 1},
        "tokenizer": {
            "capability": "engine-rendered-chat-count-v1",
            "model_sha256": "1" * 64,
            "engine_image_sha256": "2" * 64,
            "render_contract": "openai-chat-user-v1",
        },
        "request": {
            "output_tokens": 32,
            "min_completion_tokens": 1,
            "require_natural_stop": True,
            "temperature": 0,
            "seed": 42,
        },
        "sample_interval_seconds": 5,
        "cases": [
            {
                "id": "fixture",
                "workload": "context-summary-v1",
                "prompt_tokens": 2048,
                "concurrencies": [1],
                "seed": 7,
            }
        ],
    }


class PromptGeneratorTests(unittest.TestCase):
    def test_materialization_is_deterministic_and_hash_bound(self) -> None:
        # Character count is a deliberately simple exact adapter double.
        counter = len
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            first = root / "first"
            second = root / "second"
            first_plan = prompt_generator.materialize(
                contract(),
                first,
                counter,
                model_id="fixture-model",
                model_revision="a" * 40,
            )
            second_plan = prompt_generator.materialize(
                contract(),
                second,
                counter,
                model_id="fixture-model",
                model_revision="a" * 40,
            )
            self.assertEqual(first_plan.read_bytes(), second_plan.read_bytes())
            first_prompt = next((first / "prompts").iterdir())
            second_prompt = next((second / "prompts").iterdir())
            self.assertEqual(first_prompt.read_bytes(), second_prompt.read_bytes())
            self.assertEqual(len(first_prompt.read_text(encoding="utf-8")), 2048)

            plan = json.loads(first_plan.read_text(encoding="utf-8"))
            row = plan["fixtures"][0]
            self.assertEqual(
                row["sha256"], hashlib.sha256(first_prompt.read_bytes()).hexdigest()
            )
            materialization = json.loads(
                (first / "materialization.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                materialization["prompt_set_sha256"], plan["prompt_set_sha256"]
            )
            self.assertEqual(
                materialization["plan_sha256"],
                hashlib.sha256(first_plan.read_bytes()).hexdigest(),
            )

    def test_materialization_fails_closed_without_exact_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                prompt_generator.PromptGenerationError,
                "cannot reach|cannot calibrate",
            ):
                prompt_generator.materialize(
                    contract(),
                    pathlib.Path(directory) / "out",
                    lambda _text: 1,
                    model_id="fixture-model",
                    model_revision="a" * 40,
                )

    def test_materialization_writes_only_selected_cells(self) -> None:
        value = contract()
        value["cases"][0]["concurrencies"] = [1, 4]  # type: ignore[index]
        with tempfile.TemporaryDirectory() as directory:
            plan_path = prompt_generator.materialize(
                value,
                pathlib.Path(directory) / "out",
                len,
                model_id="fixture-model",
                model_revision="a" * 40,
                selected_cells=["fixture-c1"],
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(len(plan["fixtures"]), 1)
        self.assertEqual(plan["contexts"][0]["cells"], {"c1": ["fixture-c1-s00"]})


if __name__ == "__main__":
    unittest.main()
