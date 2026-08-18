#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import copy
import unittest

from core.orchestration import (
    OrchestrationError,
    build_group_plan,
    validate_orchestration_contract,
    validate_target_binding,
)


class OrchestrationContractTests(unittest.TestCase):
    def replicated(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "strategy": "replicated",
            "member_count": 2,
            "engine_strategy": "replica-pool",
            "failure_policy": "replica-independent",
            "minimum_healthy_members": 1,
            "startup_order": ["replica"],
            "roles": {
                "replica": {
                    "assignment": "all",
                    "launcher": "manifest",
                    "port_count": 1,
                    "environment": {},
                    "inference_endpoint": True,
                    "readiness": {"kind": "manifest"},
                }
            },
        }

    def distributed(self) -> dict[str, object]:
        readiness = {
            "kind": "exec",
            "command": ["/opt/runtime/ready"],
            "interval_seconds": 2,
            "timeout_seconds": 3,
            "retries": 90,
        }
        return {
            "schema_version": 1,
            "strategy": "distributed",
            "member_count": 3,
            "engine_strategy": "tensor-parallel",
            "failure_policy": "whole-group",
            "minimum_healthy_members": 3,
            "startup_order": ["engine-member", "engine-coordinator"],
            "roles": {
                "engine-member": {
                    "assignment": "members",
                    "launcher": "runtime-command",
                    "port_count": 4,
                    "command": ["/opt/runtime/launch", "member"],
                    "environment": {"ENGINE_LOG_LEVEL": "info"},
                    "inference_endpoint": False,
                    "readiness": copy.deepcopy(readiness),
                },
                "engine-coordinator": {
                    "assignment": "engine-coordinator",
                    "launcher": "runtime-command",
                    "port_count": 4,
                    "command": ["/opt/runtime/launch", "coordinator"],
                    "environment": {},
                    "inference_endpoint": True,
                    "readiness": copy.deepcopy(readiness),
                },
            },
        }

    def test_replica_contract_reuses_sealed_manifest_launcher(self) -> None:
        value = self.replicated()
        self.assertIs(validate_orchestration_contract(value), value)
        self.assertIs(
            validate_target_binding(
                value,
                {
                    "strategy": "replicated",
                    "member_count": 2,
                    "engine_strategy": "replica-pool",
                },
            ),
            value,
        )

    def test_boolean_schema_and_numeric_role_fields_are_rejected(self) -> None:
        invalid = self.replicated()
        invalid["schema_version"] = True
        with self.assertRaisesRegex(OrchestrationError, "schema_version"):
            validate_orchestration_contract(invalid)

        invalid = self.replicated()
        invalid["roles"]["replica"]["port_count"] = True
        with self.assertRaisesRegex(OrchestrationError, "port_count"):
            validate_orchestration_contract(invalid)

    def test_distributed_contract_is_runtime_owned_and_whole_group(self) -> None:
        value = self.distributed()
        self.assertIs(validate_orchestration_contract(value), value)
        self.assertEqual(value["startup_order"], ["engine-member", "engine-coordinator"])

    def test_target_binding_rejects_missing_mismatched_and_single_contracts(self) -> None:
        placement = {
            "strategy": "distributed",
            "member_count": 3,
            "engine_strategy": "tensor-parallel",
        }
        with self.assertRaisesRegex(OrchestrationError, "must contain exactly"):
            validate_target_binding(None, placement)
        changed = self.distributed()
        changed["member_count"] = 2
        changed["minimum_healthy_members"] = 2
        with self.assertRaisesRegex(OrchestrationError, "does not match"):
            validate_target_binding(changed, placement)
        with self.assertRaisesRegex(OrchestrationError, "cannot declare"):
            validate_target_binding(self.replicated(), {"strategy": "single"})

    def test_contract_rejects_shells_and_protected_environment(self) -> None:
        shell = self.distributed()
        shell["roles"]["engine-member"]["command"] = ["/bin/sh", "-c", "engine"]
        with self.assertRaisesRegex(OrchestrationError, "cannot invoke"):
            validate_orchestration_contract(shell)
        protected = self.distributed()
        protected["roles"]["engine-member"]["environment"] = {
            "LETSINFER_GROUP_ID": "forged"
        }
        with self.assertRaisesRegex(OrchestrationError, "reserved for core"):
            validate_orchestration_contract(protected)

    def test_distributed_group_plan_is_deterministic_and_ranked(self) -> None:
        members = ("1" * 32, "2" * 32, "3" * 32)
        arguments = {
            "member_ids": members,
            "member_addresses": {
                "1" * 32: "member-a.local:9770",
                "2" * 32: "member-b.local:9770",
                "3" * 32: "member-c.local:9770",
            },
            "engine_coordinator_id": "2" * 32,
            "topology_sha256": "4" * 64,
            "manifest_sha256": "5" * 64,
            "runtime_digest": "6" * 64,
            "member_port_bases": {
                "1" * 32: 18000,
                "2" * 32: 18000,
                "3" * 32: 18000,
            },
        }
        first = build_group_plan(self.distributed(), **arguments)
        second = build_group_plan(self.distributed(), **arguments)
        self.assertEqual(first, second)
        self.assertEqual(first.assignments[0].member_id, "2" * 32)
        self.assertEqual(first.assignments[0].role, "engine-coordinator")
        self.assertEqual(
            [item.role for item in first.assignments],
            ["engine-coordinator", "engine-member", "engine-member"],
        )
        self.assertEqual([item.rank for item in first.assignments], [0, 1, 2])
        self.assertRegex(first.group_id, r"^[0-9a-f]{32}$")
        self.assertEqual(first.document()["members"][0]["address"], "member-b.local:9770")

    def test_group_plan_rejects_incomplete_member_addresses(self) -> None:
        with self.assertRaisesRegex(OrchestrationError, "addresses"):
            build_group_plan(
                self.replicated(),
                member_ids=("1" * 32, "2" * 32),
                member_addresses={"1" * 32: "a.local:9770"},
                engine_coordinator_id="1" * 32,
                topology_sha256="3" * 64,
                manifest_sha256="4" * 64,
                runtime_digest="5" * 64,
                member_port_bases={"1" * 32: 18000, "2" * 32: 18000},
            )


if __name__ == "__main__":
    unittest.main()
