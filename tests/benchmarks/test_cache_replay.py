#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit checks for restart-persistent cache evidence comparison."""

from __future__ import annotations

import copy
import importlib.util
import pathlib
import tempfile
import unittest


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY_ROOT / "benchmarks/cache_replay.py"
SPEC = importlib.util.spec_from_file_location("cache_replay", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
REPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPLAY)


class CacheReplayTests(unittest.TestCase):
    def result(self, container_id: str) -> dict:
        return {
            "release": "release",
            "engine": "vllm",
            "model_id": "example/model",
            "model_revision": "a" * 40,
            "measured_commit": "b" * 40,
            "release_manifest_sha256": "c" * 64,
            "fixture_manifest_sha256": "d" * 64,
            "server_command_sha256": "e" * 64,
            "runner_sha256": "f" * 64,
            "source_identity": {"commit": "b" * 40, "clean": True},
            "workload_capacity": {
                "max_connections": 8,
                "max_active_requests": 1,
                "max_context_tokens": 1024,
            },
            "container_identity": {
                "id": container_id,
                "image": "sha256:" + "1" * 64,
                "started_at": container_id,
                "restart_count": 0,
            },
            "tasks": [
                {
                    "name": "context",
                    "cell": "single",
                    "warmup_waves": 1,
                    "measured_waves": 1,
                }
            ],
            "_results_sha256": "2" * 64,
        }

    def wave(self, output: str, cached: int) -> dict:
        return {
            "result": {
                "requests": [
                    {
                        "fixture": "prompt",
                        "prompt_tokens": 100,
                        "completion_tokens": 2,
                        "cached_prompt_tokens": cached,
                        "cache_write_tokens": 100 - cached,
                        "ttft_ms": 10.0,
                        "wall_ms": 20.0,
                        "decode_tokens_per_second": 100.0,
                        "output": output,
                        "output_sha256": REPLAY.common.sha256_text(output),
                        "finish_reasons": ["length"],
                    }
                ]
            }
        }

    def write_waves(
        self,
        population: pathlib.Path,
        restored: pathlib.Path,
        *,
        cold: str = "same",
        hot: str = "same",
        restored_output: str = "same",
    ) -> None:
        REPLAY.common.write_json_atomic(
            population / "waves/context/warmup-0001.json", self.wave(cold, 0)
        )
        REPLAY.common.write_json_atomic(
            population / "waves/context/measured-0001.json", self.wave(hot, 99)
        )
        for index in (1, 2):
            REPLAY.common.write_json_atomic(
                restored / f"waves/context/measured-{index:04d}.json",
                self.wave(restored_output, 99),
            )

    def test_all_phases_policy_requires_cold_hot_and_restored_equality(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            population = root / "population"
            restored = root / "restored"
            self.write_waves(population, restored)
            population_result = self.result("population")
            restored_result = self.result("restored")
            restored_result["tasks"][0].update(
                {"warmup_waves": 0, "measured_waves": 2}
            )
            report = REPLAY.compare_runs(
                population,
                population_result,
                restored,
                restored_result,
                "synthetic-provider",
                "all-phases-exact",
            )
            self.assertTrue(report["qualification_passed"])
            self.assertTrue(report["cells"][0]["cold_restored_outputs_equal"])

            self.write_waves(
                population, restored, cold="cold", hot="hot", restored_output="hot"
            )
            with self.assertRaisesRegex(REPLAY.CacheReplayError, "exact-capsule"):
                REPLAY.compare_runs(
                    population,
                    population_result,
                    restored,
                    restored_result,
                    "synthetic-provider",
                    "all-phases-exact",
                )

    def test_restored_repeat_policy_allows_cross_mode_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            population = root / "population"
            restored = root / "restored"
            self.write_waves(
                population,
                restored,
                cold="cold",
                hot="hot",
                restored_output="restored",
            )
            population_result = self.result("population")
            population_result["engine"] = "synthetic-engine"
            restored_result = copy.deepcopy(population_result)
            restored_result["container_identity"].update(
                {"id": "restored", "started_at": "restored"}
            )
            restored_result["tasks"][0].update(
                {"warmup_waves": 0, "measured_waves": 2}
            )
            report = REPLAY.compare_runs(
                population,
                population_result,
                restored,
                restored_result,
                "synthetic-provider",
                "restored-repeat-exact",
            )
            self.assertFalse(report["cells"][0]["cold_hot_outputs_equal"])
            self.assertTrue(report["cells"][0]["restored_outputs_equal"])

            second = self.wave("different restored", 99)
            REPLAY.common.write_json_atomic(
                restored / "waves/context/measured-0002.json", second
            )
            with self.assertRaisesRegex(REPLAY.CacheReplayError, "restart-restored"):
                REPLAY.compare_runs(
                    population,
                    population_result,
                    restored,
                    restored_result,
                    "synthetic-provider",
                    "restored-repeat-exact",
                )

    def test_replay_requires_a_new_container_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            population = root / "population"
            restored = root / "restored"
            self.write_waves(population, restored)
            population_result = self.result("same")
            restored_result = copy.deepcopy(population_result)
            restored_result["tasks"][0].update(
                {"warmup_waves": 0, "measured_waves": 2}
            )
            with self.assertRaisesRegex(REPLAY.CacheReplayError, "did not cross"):
                REPLAY.compare_runs(
                    population,
                    population_result,
                    restored,
                    restored_result,
                    "synthetic-provider",
                    "all-phases-exact",
                )


if __name__ == "__main__":
    unittest.main()
