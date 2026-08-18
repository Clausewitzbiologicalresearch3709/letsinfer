#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Fail-closed public inference exposure providers."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import subprocess
from collections.abc import Callable, Mapping, Sequence
from typing import Any


PUBLIC_HTTPS_PORT = 443
INFERENCE_TARGET = "http://127.0.0.1:8000"
MAX_PROVIDER_OUTPUT_BYTES = 1024 * 1024
TAILSCALE_CANDIDATES = (
    pathlib.Path("/usr/bin/tailscale"),
    pathlib.Path("/usr/local/bin/tailscale"),
    pathlib.Path("/opt/homebrew/bin/tailscale"),
)


class ExposureError(RuntimeError):
    """Public exposure could not be proven safe."""


@dataclasses.dataclass(frozen=True)
class ProviderResult:
    provider: str
    public_url: str
    inference_target: str
    configuration_sha256: str


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ExposureError(
            f"exposure provider command failed: {type(error).__name__}"
        ) from error
    for value in (result.stdout, result.stderr):
        if len(value.encode("utf-8", errors="replace")) > MAX_PROVIDER_OUTPUT_BYTES:
            raise ExposureError("exposure provider output exceeds the bounded limit")
    return result


def tailscale_executable() -> pathlib.Path:
    for candidate in TAILSCALE_CANDIDATES:
        try:
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
        except OSError:
            continue
    raise ExposureError("Tailscale is not installed at a trusted system path")


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _json_result(result: subprocess.CompletedProcess[str], label: str) -> dict[str, Any]:
    if result.returncode != 0:
        raise ExposureError(f"Tailscale {label} failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ExposureError(f"Tailscale {label} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ExposureError(f"Tailscale {label} returned an invalid object")
    return value


def _status(executable: pathlib.Path, runner: Runner) -> dict[str, Any]:
    return _json_result(
        runner([str(executable), "funnel", "status", "--json"]),
        "Funnel status",
    )


def _public_url(executable: pathlib.Path, runner: Runner) -> str:
    value = _json_result(
        runner([str(executable), "status", "--json"]), "status"
    )
    self_value = value.get("Self")
    dns_name = self_value.get("DNSName") if isinstance(self_value, dict) else None
    if (
        not isinstance(dns_name, str)
        or not dns_name.endswith(".")
        or len(dns_name) > 254
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-." for character in dns_name)
    ):
        raise ExposureError("Tailscale did not report a valid public DNS name")
    return "https://" + dns_name.rstrip(".")


def _validate_owned_status(value: Mapping[str, Any]) -> str:
    if set(value) != {"TCP", "Web", "AllowFunnel"}:
        raise ExposureError("Funnel configuration is not exclusively inference-owned")
    tcp = value.get("TCP")
    web = value.get("Web")
    allowed = value.get("AllowFunnel")
    if tcp != {str(PUBLIC_HTTPS_PORT): {"HTTPS": True}}:
        raise ExposureError("Funnel does not expose exactly one HTTPS listener")
    if not isinstance(web, Mapping) or len(web) != 1:
        raise ExposureError("Funnel must contain exactly one inference web listener")
    authority, website = next(iter(web.items()))
    if (
        not isinstance(authority, str)
        or not authority.endswith(f":{PUBLIC_HTTPS_PORT}")
        or not isinstance(website, Mapping)
        or set(website) != {"Handlers"}
        or website.get("Handlers") != {"/": {"Proxy": INFERENCE_TARGET}}
    ):
        raise ExposureError("Funnel must proxy only / to the local inference gateway")
    if allowed != {authority: True}:
        raise ExposureError("Funnel public authorization is not bound to its inference listener")
    payload = _canonical(value)
    return hashlib.sha256(payload).hexdigest()


def enable_tailscale(
    *,
    runner: Runner = _run,
    executable: pathlib.Path | None = None,
) -> ProviderResult:
    binary = executable or tailscale_executable()
    before = _status(binary, runner)
    if before:
        raise ExposureError(
            "Tailscale Funnel already has configuration; refusing to replace it"
        )
    result = runner(
        [
            str(binary),
            "funnel",
            "--bg",
            "--yes",
            "--https",
            str(PUBLIC_HTTPS_PORT),
            INFERENCE_TARGET,
        ]
    )
    if result.returncode != 0:
        raise ExposureError("Tailscale Funnel activation failed")
    try:
        after = _status(binary, runner)
        configuration_sha256 = _validate_owned_status(after)
        public_url = _public_url(binary, runner)
    except BaseException:
        runner([str(binary), "funnel", "reset"])
        raise
    return ProviderResult(
        provider="tailscale-funnel",
        public_url=public_url,
        inference_target=INFERENCE_TARGET,
        configuration_sha256=configuration_sha256,
    )


def disable_tailscale(
    expected_configuration_sha256: str,
    *,
    runner: Runner = _run,
    executable: pathlib.Path | None = None,
) -> None:
    binary = executable or tailscale_executable()
    before = _status(binary, runner)
    actual = _validate_owned_status(before)
    if actual != expected_configuration_sha256:
        raise ExposureError(
            "Tailscale Funnel configuration changed; refusing a broad reset"
        )
    result = runner([str(binary), "funnel", "reset"])
    if result.returncode != 0:
        raise ExposureError("Tailscale Funnel reset failed")
    if _status(binary, runner):
        raise ExposureError("Tailscale Funnel remained configured after reset")


def verify_tailscale(
    expected_configuration_sha256: str,
    *,
    runner: Runner = _run,
    executable: pathlib.Path | None = None,
) -> ProviderResult:
    binary = executable or tailscale_executable()
    value = _status(binary, runner)
    actual = _validate_owned_status(value)
    if actual != expected_configuration_sha256:
        raise ExposureError("Tailscale Funnel configuration identity changed")
    return ProviderResult(
        provider="tailscale-funnel",
        public_url=_public_url(binary, runner),
        inference_target=INFERENCE_TARGET,
        configuration_sha256=actual,
    )
