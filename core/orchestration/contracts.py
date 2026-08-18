#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Strict, engine-neutral contracts for one immutable runtime group.

Core assigns authenticated members and owns lifecycle ordering. Runtime packs
own every engine-specific executable and argument. No shell expansion or
engine option knowledge crosses that boundary.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = 1
ID_RE = re.compile(r"^[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
ENVIRONMENT_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
MAX_ARGUMENTS = 128
MAX_ARGUMENT_BYTES = 16 * 1024
MAX_ENVIRONMENT = 64
MAX_ENVIRONMENT_BYTES = 16 * 1024
PROTECTED_ENVIRONMENT_PREFIX = "LETSINFER_"
FORBIDDEN_EXECUTABLES = {
    "/bin/bash",
    "/bin/dash",
    "/bin/sh",
    "/usr/bin/bash",
    "/usr/bin/dash",
    "/usr/bin/env",
    "/usr/bin/sh",
}


class OrchestrationError(ValueError):
    """A runtime topology or group plan is incomplete or unsafe."""


@dataclasses.dataclass(frozen=True)
class RoleAssignment:
    member_id: str
    address: str
    rank: int
    role_rank: int
    role: str
    port_base: int
    port_count: int
    launcher: str
    command: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    inference_endpoint: bool
    readiness: Mapping[str, Any]


@dataclasses.dataclass(frozen=True)
class GroupPlan:
    group_id: str
    strategy: str
    engine_strategy: str
    failure_policy: str
    minimum_healthy_members: int
    topology_sha256: str
    manifest_sha256: str
    runtime_digest: str
    engine_coordinator_id: str
    startup_order: tuple[str, ...]
    assignments: tuple[RoleAssignment, ...]

    def document(self) -> dict[str, Any]:
        """Return the immutable, engine-consumable group document."""
        return {
            "schema_version": SCHEMA_VERSION,
            "group_id": self.group_id,
            "strategy": self.strategy,
            "engine_strategy": self.engine_strategy,
            "failure_policy": self.failure_policy,
            "minimum_healthy_members": self.minimum_healthy_members,
            "topology_sha256": self.topology_sha256,
            "manifest_sha256": self.manifest_sha256,
            "runtime_digest": self.runtime_digest,
            "engine_coordinator_id": self.engine_coordinator_id,
            "startup_order": list(self.startup_order),
            "members": [
                {
                    "member_id": assignment.member_id,
                    "address": assignment.address,
                    "rank": assignment.rank,
                    "role_rank": assignment.role_rank,
                    "role": assignment.role,
                    "port_base": assignment.port_base,
                    "port_count": assignment.port_count,
                    "inference_endpoint": assignment.inference_endpoint,
                }
                for assignment in self.assignments
            ],
        }


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def validate_group_document(value: Any) -> dict[str, Any]:
    """Validate the exact immutable group document sent to every member."""
    required = {
        "schema_version", "group_id", "strategy", "engine_strategy",
        "failure_policy", "minimum_healthy_members", "topology_sha256",
        "manifest_sha256", "runtime_digest", "engine_coordinator_id",
        "startup_order", "members",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != SCHEMA_VERSION
    ):
        raise OrchestrationError("engine-group document schema is invalid")
    if not isinstance(value.get("group_id"), str) or not ID_RE.fullmatch(value["group_id"]):
        raise OrchestrationError("engine-group document identity is invalid")
    if value.get("strategy") not in {"replicated", "distributed"}:
        raise OrchestrationError("engine-group document strategy is invalid")
    if not isinstance(value.get("engine_strategy"), str) or not SAFE_NAME_RE.fullmatch(value["engine_strategy"]):
        raise OrchestrationError("engine-group document engine strategy is invalid")
    for key in ("topology_sha256", "manifest_sha256", "runtime_digest"):
        if not isinstance(value.get(key), str) or not SHA256_RE.fullmatch(value[key]):
            raise OrchestrationError(f"engine-group document {key} is invalid")
    coordinator = value.get("engine_coordinator_id")
    if not isinstance(coordinator, str) or not ID_RE.fullmatch(coordinator):
        raise OrchestrationError("engine-group document coordinator is invalid")
    members = value.get("members")
    member_fields = {
        "member_id", "address", "rank", "role_rank", "role", "port_base",
        "port_count", "inference_endpoint",
    }
    if (
        not isinstance(members, list)
        or len(members) not in range(2, 65)
        or any(not isinstance(item, dict) or set(item) != member_fields for item in members)
    ):
        raise OrchestrationError("engine-group document members are invalid")
    ids: list[str] = []
    ranks: list[int] = []
    role_ranks: dict[str, list[int]] = {}
    for item in members:
        member_id = item.get("member_id")
        address = item.get("address")
        rank = item.get("rank")
        role_rank = item.get("role_rank")
        role = item.get("role")
        port_base = item.get("port_base")
        port_count = item.get("port_count")
        if not isinstance(member_id, str) or not ID_RE.fullmatch(member_id):
            raise OrchestrationError("engine-group document member identity is invalid")
        if not isinstance(address, str) or not address or len(address.encode("utf-8")) > 255:
            raise OrchestrationError("engine-group document member address is invalid")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 0:
            raise OrchestrationError("engine-group document member rank is invalid")
        if not isinstance(role_rank, int) or isinstance(role_rank, bool) or role_rank < 0:
            raise OrchestrationError("engine-group document role rank is invalid")
        if role not in {"replica", "engine-member", "engine-coordinator"}:
            raise OrchestrationError("engine-group document role is invalid")
        if (
            not isinstance(port_base, int)
            or isinstance(port_base, bool)
            or port_base not in range(1024, 65536)
            or not isinstance(port_count, int)
            or isinstance(port_count, bool)
            or port_count not in range(1, 33)
            or port_base + port_count > 65536
        ):
            raise OrchestrationError("engine-group document port range is invalid")
        if not isinstance(item.get("inference_endpoint"), bool):
            raise OrchestrationError("engine-group document endpoint flag is invalid")
        ids.append(member_id)
        ranks.append(rank)
        role_ranks.setdefault(role, []).append(role_rank)
    if len(set(ids)) != len(ids) or sorted(ranks) != list(range(len(members))):
        raise OrchestrationError("engine-group document members are duplicated or misranked")
    if coordinator not in ids or members[0]["member_id"] != coordinator or members[0]["rank"] != 0:
        raise OrchestrationError("engine-group document coordinator must have rank zero")
    if any(sorted(values) != list(range(len(values))) for values in role_ranks.values()):
        raise OrchestrationError("engine-group document role ranks are not contiguous")
    strategy = value["strategy"]
    if strategy == "replicated":
        if (
            value.get("failure_policy") != "replica-independent"
            or value.get("startup_order") != ["replica"]
            or set(role_ranks) != {"replica"}
            or not all(item["inference_endpoint"] for item in members)
        ):
            raise OrchestrationError("replicated engine-group document is inconsistent")
        minimum = value.get("minimum_healthy_members")
        if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum not in range(1, len(members) + 1):
            raise OrchestrationError("replicated engine-group health threshold is invalid")
    else:
        if (
            value.get("failure_policy") != "whole-group"
            or value.get("minimum_healthy_members") != len(members)
            or value.get("startup_order") != ["engine-member", "engine-coordinator"]
            or set(role_ranks) != {"engine-member", "engine-coordinator"}
            or len(role_ranks["engine-coordinator"]) != 1
        ):
            raise OrchestrationError("distributed engine-group document is inconsistent")
        for item in members:
            expected_endpoint = item["role"] == "engine-coordinator"
            if item["inference_endpoint"] is not expected_endpoint:
                raise OrchestrationError("distributed engine-group endpoint assignment is invalid")
    identity = {
        "contract": "letsinfer-engine-group-v1",
        "strategy": strategy,
        "engine_strategy": value["engine_strategy"],
        "topology_sha256": value["topology_sha256"],
        "manifest_sha256": value["manifest_sha256"],
        "runtime_digest": value["runtime_digest"],
        "engine_coordinator_id": coordinator,
        "members": [
            {
                "member_id": item["member_id"], "address": item["address"],
                "role": item["role"], "port_base": item["port_base"],
                "port_count": item["port_count"],
            }
            for item in members
        ],
    }
    if hashlib.sha256(_canonical_bytes(identity)).hexdigest()[:32] != value["group_id"]:
        raise OrchestrationError("engine-group document identity does not match its contents")
    return value


def _argv(value: Any, where: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAX_ARGUMENTS
        or any(
            not isinstance(item, str)
            or not item
            or "\0" in item
            or len(item.encode("utf-8")) > 4096
            for item in value
        )
        or sum(len(item.encode("utf-8")) for item in value) > MAX_ARGUMENT_BYTES
    ):
        raise OrchestrationError(f"{where} must be a bounded non-empty argv")
    executable = value[0]
    if not executable.startswith("/") or "/../" in executable or executable.endswith("/.."):
        raise OrchestrationError(f"{where}[0] must be an absolute contained executable")
    if executable in FORBIDDEN_EXECUTABLES:
        raise OrchestrationError(f"{where} cannot invoke a shell or environment dispatcher")
    return tuple(value)


def _environment(value: Any, where: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict) or len(value) > MAX_ENVIRONMENT:
        raise OrchestrationError(f"{where} must be a bounded object")
    total = 0
    result: list[tuple[str, str]] = []
    for key in sorted(value):
        item = value[key]
        if not isinstance(key, str) or not ENVIRONMENT_RE.fullmatch(key):
            raise OrchestrationError(f"{where} contains an invalid variable name")
        if key.startswith(PROTECTED_ENVIRONMENT_PREFIX):
            raise OrchestrationError(f"{where}.{key} is reserved for core")
        if not isinstance(item, str) or "\0" in item:
            raise OrchestrationError(f"{where}.{key} must be a string without NUL")
        total += len(key.encode("utf-8")) + len(item.encode("utf-8"))
        if total > MAX_ENVIRONMENT_BYTES:
            raise OrchestrationError(f"{where} exceeds its byte limit")
        result.append((key, item))
    return tuple(result)


def _readiness(value: Any, launcher: str, where: str) -> dict[str, Any]:
    if launcher == "manifest":
        if value != {"kind": "manifest"}:
            raise OrchestrationError(
                f"{where} must use the sealed manifest readiness contract"
            )
        return {"kind": "manifest"}
    required = {"kind", "command", "interval_seconds", "timeout_seconds", "retries"}
    if not isinstance(value, dict) or set(value) != required or value.get("kind") != "exec":
        raise OrchestrationError(f"{where} must be an exact exec readiness contract")
    command = _argv(value.get("command"), f"{where}.command")
    for key, lower, upper in (
        ("interval_seconds", 1, 60),
        ("timeout_seconds", 1, 30),
        ("retries", 1, 600),
    ):
        item = value.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item not in range(lower, upper + 1):
            raise OrchestrationError(f"{where}.{key} must be from {lower} through {upper}")
    return {
        "kind": "exec",
        "command": list(command),
        "interval_seconds": value["interval_seconds"],
        "timeout_seconds": value["timeout_seconds"],
        "retries": value["retries"],
    }


def validate_orchestration_contract(value: Any) -> dict[str, Any]:
    """Validate one runtime-owned, engine-specific group contract."""
    required = {
        "schema_version",
        "strategy",
        "member_count",
        "engine_strategy",
        "failure_policy",
        "minimum_healthy_members",
        "startup_order",
        "roles",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise OrchestrationError(
            "runtime.orchestration must contain exactly schema_version, strategy, "
            "member_count, engine_strategy, failure_policy, minimum_healthy_members, "
            "startup_order, and roles"
        )
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != SCHEMA_VERSION
    ):
        raise OrchestrationError("unsupported runtime.orchestration schema_version")
    strategy = value.get("strategy")
    if strategy not in {"replicated", "distributed"}:
        raise OrchestrationError("runtime.orchestration.strategy must be replicated or distributed")
    member_count = value.get("member_count")
    if (
        not isinstance(member_count, int)
        or isinstance(member_count, bool)
        or member_count not in range(2, 65)
    ):
        raise OrchestrationError("runtime.orchestration.member_count must be from 2 through 64")
    engine_strategy = value.get("engine_strategy")
    if not isinstance(engine_strategy, str) or not SAFE_NAME_RE.fullmatch(engine_strategy):
        raise OrchestrationError("runtime.orchestration.engine_strategy is invalid")

    expected_roles: dict[str, tuple[str, bool]]
    if strategy == "replicated":
        if value.get("failure_policy") != "replica-independent":
            raise OrchestrationError("replicated orchestration requires replica-independent failure policy")
        expected_roles = {"replica": ("all", True)}
        minimum_healthy = value.get("minimum_healthy_members")
        if (
            not isinstance(minimum_healthy, int)
            or isinstance(minimum_healthy, bool)
            or minimum_healthy not in range(1, member_count + 1)
        ):
            raise OrchestrationError(
                "replicated orchestration minimum_healthy_members must be from 1 through member_count"
            )
    else:
        if value.get("failure_policy") != "whole-group":
            raise OrchestrationError("distributed orchestration requires whole-group failure policy")
        expected_roles = {
            "engine-member": ("members", False),
            "engine-coordinator": ("engine-coordinator", True),
        }
        if value.get("minimum_healthy_members") != member_count:
            raise OrchestrationError(
                "distributed orchestration requires every member to remain healthy"
            )
    roles = value.get("roles")
    if not isinstance(roles, dict) or set(roles) != set(expected_roles):
        raise OrchestrationError(
            f"{strategy} orchestration roles must be exactly {', '.join(sorted(expected_roles))}"
        )
    expected_order = (
        ["replica"]
        if strategy == "replicated"
        else ["engine-member", "engine-coordinator"]
    )
    if value.get("startup_order") != expected_order:
        raise OrchestrationError(
            f"runtime.orchestration.startup_order must be {expected_order!r}"
        )

    for name, (assignment, inference_endpoint) in expected_roles.items():
        role = roles[name]
        common = {
            "assignment", "launcher", "environment", "port_count",
            "inference_endpoint", "readiness",
        }
        if not isinstance(role, dict) or not common.issubset(role):
            raise OrchestrationError(f"runtime.orchestration.roles.{name} is incomplete")
        launcher = role.get("launcher")
        expected_fields = common if launcher == "manifest" else common | {"command"}
        if launcher not in {"manifest", "runtime-command"} or set(role) != expected_fields:
            raise OrchestrationError(f"runtime.orchestration.roles.{name} has invalid fields")
        if role.get("assignment") != assignment:
            raise OrchestrationError(
                f"runtime.orchestration.roles.{name}.assignment must be {assignment}"
            )
        if role.get("inference_endpoint") is not inference_endpoint:
            raise OrchestrationError(
                f"runtime.orchestration.roles.{name}.inference_endpoint is invalid"
            )
        port_count = role.get("port_count")
        if (
            not isinstance(port_count, int)
            or isinstance(port_count, bool)
            or port_count not in range(1, 33)
        ):
            raise OrchestrationError(
                f"runtime.orchestration.roles.{name}.port_count must be from 1 through 32"
            )
        _environment(role.get("environment"), f"runtime.orchestration.roles.{name}.environment")
        if launcher == "runtime-command":
            _argv(role.get("command"), f"runtime.orchestration.roles.{name}.command")
        _readiness(role.get("readiness"), launcher, f"runtime.orchestration.roles.{name}.readiness")
    return value


def validate_target_binding(value: Any, placement: Mapping[str, Any]) -> dict[str, Any] | None:
    """Require the runtime group contract to exactly bind its target placement."""
    strategy = placement.get("strategy")
    if strategy == "single":
        if value is not None:
            raise OrchestrationError("single-member targets cannot declare runtime orchestration")
        return None
    contract = validate_orchestration_contract(value)
    for key in ("strategy", "member_count", "engine_strategy"):
        if contract[key] != placement.get(key):
            raise OrchestrationError(
                f"runtime.orchestration.{key} does not match target.placement.{key}"
            )
    return contract


def build_group_plan(
    value: Any,
    *,
    member_ids: Sequence[str],
    member_addresses: Mapping[str, str],
    engine_coordinator_id: str,
    topology_sha256: str,
    manifest_sha256: str,
    runtime_digest: str,
    member_port_bases: Mapping[str, int],
) -> GroupPlan:
    """Expand one validated runtime contract across an authenticated placement."""
    contract = validate_orchestration_contract(value)
    members = tuple(member_ids)
    if (
        len(members) != contract["member_count"]
        or len(set(members)) != len(members)
        or any(not isinstance(item, str) or not ID_RE.fullmatch(item) for item in members)
    ):
        raise OrchestrationError("group members do not match the runtime member count")
    if engine_coordinator_id not in members:
        raise OrchestrationError("engine coordinator is not a group member")
    for value_hash, label in (
        (topology_sha256, "topology"),
        (manifest_sha256, "manifest"),
        (runtime_digest, "runtime"),
    ):
        if not isinstance(value_hash, str) or not SHA256_RE.fullmatch(value_hash):
            raise OrchestrationError(f"group {label} identity must be a SHA-256")
    if set(member_addresses) != set(members) or any(
        not isinstance(member_addresses[item], str)
        or not member_addresses[item]
        or len(member_addresses[item].encode("utf-8")) > 255
        for item in members
    ):
        raise OrchestrationError("group member addresses are incomplete or invalid")
    if set(member_port_bases) != set(members):
        raise OrchestrationError("group member port assignments are incomplete")

    ordered = (engine_coordinator_id,) + tuple(
        member for member in members if member != engine_coordinator_id
    )
    assignments: list[RoleAssignment] = []
    role_ranks: dict[str, int] = {}
    for rank, member_id in enumerate(ordered):
        role_name = (
            "replica"
            if contract["strategy"] == "replicated"
            else "engine-coordinator"
            if member_id == engine_coordinator_id
            else "engine-member"
        )
        role = contract["roles"][role_name]
        port_base = member_port_bases[member_id]
        port_count = role["port_count"]
        if (
            not isinstance(port_base, int)
            or isinstance(port_base, bool)
            or port_base not in range(1024, 65536)
            or port_base + port_count > 65536
        ):
            raise OrchestrationError("group member port range is invalid")
        role_rank = role_ranks.get(role_name, 0)
        role_ranks[role_name] = role_rank + 1
        assignments.append(
            RoleAssignment(
                member_id=member_id,
                address=member_addresses[member_id],
                rank=rank,
                role_rank=role_rank,
                role=role_name,
                port_base=port_base,
                port_count=port_count,
                launcher=role["launcher"],
                command=tuple(role.get("command", ())),
                environment=_environment(
                    role["environment"],
                    f"runtime.orchestration.roles.{role_name}.environment",
                ),
                inference_endpoint=role["inference_endpoint"],
                readiness=_readiness(
                    role["readiness"],
                    role["launcher"],
                    f"runtime.orchestration.roles.{role_name}.readiness",
                ),
            )
        )
    identity = {
        "contract": "letsinfer-engine-group-v1",
        "strategy": contract["strategy"],
        "engine_strategy": contract["engine_strategy"],
        "topology_sha256": topology_sha256,
        "manifest_sha256": manifest_sha256,
        "runtime_digest": runtime_digest,
        "engine_coordinator_id": engine_coordinator_id,
        "members": [
            {
                "member_id": item.member_id, "address": item.address,
                "role": item.role, "port_base": item.port_base,
                "port_count": item.port_count,
            }
            for item in assignments
        ],
    }
    return GroupPlan(
        group_id=hashlib.sha256(_canonical_bytes(identity)).hexdigest()[:32],
        strategy=contract["strategy"],
        engine_strategy=contract["engine_strategy"],
        failure_policy=contract["failure_policy"],
        minimum_healthy_members=contract["minimum_healthy_members"],
        topology_sha256=topology_sha256,
        manifest_sha256=manifest_sha256,
        runtime_digest=runtime_digest,
        engine_coordinator_id=engine_coordinator_id,
        startup_order=tuple(contract["startup_order"]),
        assignments=tuple(assignments),
    )
