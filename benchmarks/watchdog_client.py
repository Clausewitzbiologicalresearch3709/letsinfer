#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Minimal dependency-free client for Let's Infer Watchdog telemetry ranges."""

from __future__ import annotations

import pathlib
import socket
import ssl
from collections.abc import Iterator
from typing import Any


MAX_FRAME_BYTES = 65_536
REQUEST_ID = 1


class WatchdogClientError(RuntimeError):
    """A Watchdog telemetry query failed or returned invalid protobuf."""


def _varint(value: int) -> bytes:
    if value < 0:
        raise WatchdogClientError("cannot encode a negative protobuf varint")
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _uint(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _message(field: int, value: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(value)) + value


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 64, 7):
        if offset >= len(data):
            raise WatchdogClientError("truncated protobuf varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return value, offset
    raise WatchdogClientError("oversized protobuf varint")


def _fields(data: bytes) -> Iterator[tuple[int, int | bytes]]:
    offset = 0
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        field = key >> 3
        wire = key & 7
        if field == 0:
            raise WatchdogClientError("protobuf field zero is invalid")
        if wire == 0:
            value, offset = _read_varint(data, offset)
            yield field, value
        elif wire == 2:
            length, offset = _read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise WatchdogClientError("truncated protobuf message")
            yield field, data[offset:end]
            offset = end
        else:
            raise WatchdogClientError(f"unsupported protobuf wire type: {wire}")


def _zigzag32(value: int) -> int:
    decoded = (value >> 1) ^ -(value & 1)
    if not -(2**31) <= decoded < 2**31:
        raise WatchdogClientError("protobuf sint32 is out of range")
    return decoded


def _telemetry(payload: bytes) -> dict[str, int]:
    values: dict[int, int | bytes] = dict(_fields(payload))
    gpu_raw = values.get(9)
    if not isinstance(gpu_raw, bytes):
        raise WatchdogClientError("Watchdog sample has no GPU metrics")
    gpu: dict[int, int | bytes] = dict(_fields(gpu_raw))
    required = {
        "sequence": values.get(1),
        "unix_ms": values.get(2),
        "cpu_percent": values.get(5),
        "disk_percent": values.get(8),
        "gpu_percent": gpu.get(1),
        "system_temp_deci_c": (
            _zigzag32(values[10]) if isinstance(values.get(10), int) else None
        ),
        "gpu_temp_deci_c": (
            _zigzag32(gpu[4]) if isinstance(gpu.get(4), int) else None
        ),
        "nvme_temp_deci_c": (
            _zigzag32(values[11]) if isinstance(values.get(11), int) else None
        ),
        "disk_read_kib_s": values.get(19),
        "disk_write_kib_s": values.get(20),
        "cpu_clock_mhz": values.get(23),
        "gpu_clock_mhz": gpu.get(6),
        "vram_clock_mhz": gpu.get(7),
        "system_ram_clock_mhz": values.get(24),
    }
    if any(
        not isinstance(value, int) or isinstance(value, bool)
        for value in required.values()
    ):
        raise WatchdogClientError("Watchdog sample is missing a required metric")
    decoded = {key: int(value) for key, value in required.items()}
    if decoded["disk_percent"] == 255:
        decoded["disk_percent"] = -1
    if decoded["nvme_temp_deci_c"] == -32768:
        decoded["nvme_temp_deci_c"] = -1
    for field in (
        "cpu_clock_mhz",
        "gpu_clock_mhz",
        "vram_clock_mhz",
        "system_ram_clock_mhz",
    ):
        if decoded[field] == 0xFFFFFFFF:
            decoded[field] = -1
    return decoded


def decode_server_envelope(payload: bytes) -> tuple[str, Any]:
    values = list(_fields(payload))
    request_ids = [value for field, value in values if field == 1]
    if request_ids != [REQUEST_ID]:
        raise WatchdogClientError("Watchdog response request ID is invalid")
    bodies = [(field, value) for field, value in values if field != 1]
    if len(bodies) != 1 or not isinstance(bodies[0][1], bytes):
        raise WatchdogClientError("Watchdog response envelope is invalid")
    field, body = bodies[0]
    if field == 11:
        samples = [
            _telemetry(value)
            for nested_field, value in _fields(body)
            if nested_field == 1 and isinstance(value, bytes)
        ]
        if not samples:
            raise WatchdogClientError("Watchdog returned an empty telemetry batch")
        return "samples", samples
    if field == 12:
        return "complete", None
    if field == 15:
        raise WatchdogClientError("Watchdog reported a telemetry gap")
    if field == 16:
        message = next(
            (
                value.decode("utf-8", errors="replace")
                for nested_field, value in _fields(body)
                if nested_field == 2 and isinstance(value, bytes)
            ),
            "unknown Watchdog error",
        )
        raise WatchdogClientError(message)
    raise WatchdogClientError(f"unexpected Watchdog response field: {field}")


def _read_exact(stream: ssl.SSLSocket, length: int) -> bytes:
    output = bytearray()
    while len(output) < length:
        chunk = stream.recv(length - len(output))
        if not chunk:
            raise WatchdogClientError("Watchdog closed the telemetry connection")
        output.extend(chunk)
    return bytes(output)


def query_range(
    *,
    start_unix_ms: int,
    end_unix_ms: int,
    port: int,
    ca_file: pathlib.Path,
    controller_cert_file: pathlib.Path,
    controller_key_file: pathlib.Path,
    timeout: int = 30,
) -> list[dict[str, int]]:
    """Query one-second Watchdog samples over authenticated local mTLS."""
    if start_unix_ms <= 0 or end_unix_ms < start_unix_ms:
        raise WatchdogClientError("invalid Watchdog telemetry range")
    if not 1 <= port <= 65_535:
        raise WatchdogClientError("invalid Watchdog port")
    for path, label in (
        (ca_file, "CA"),
        (controller_cert_file, "controller certificate"),
        (controller_key_file, "controller key"),
    ):
        if path.is_symlink() or not path.is_file():
            raise WatchdogClientError(f"Watchdog {label} is not a regular file")

    query = b"".join(
        (
            _uint(1, start_unix_ms),
            _uint(2, end_unix_ms),
            _uint(3, 1),
        )
    )
    request = _uint(1, REQUEST_ID) + _message(12, query)
    frame = len(request).to_bytes(4, "big") + request
    context = ssl.create_default_context(cafile=str(ca_file))
    context.load_cert_chain(str(controller_cert_file), str(controller_key_file))
    samples: list[dict[str, int]] = []
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname="localhost") as stream:
                stream.settimeout(timeout)
                stream.sendall(frame)
                while True:
                    length = int.from_bytes(_read_exact(stream, 4), "big")
                    if not 1 <= length <= MAX_FRAME_BYTES:
                        raise WatchdogClientError("Watchdog frame length is invalid")
                    kind, value = decode_server_envelope(_read_exact(stream, length))
                    if kind == "complete":
                        break
                    samples.extend(value)
    except (OSError, ssl.SSLError) as error:
        raise WatchdogClientError(f"Watchdog telemetry query failed: {error}") from error

    samples.sort(key=lambda row: (row["unix_ms"], row["sequence"]))
    if not samples:
        raise WatchdogClientError("Watchdog returned no samples for the workload")
    if len({row["sequence"] for row in samples}) != len(samples):
        raise WatchdogClientError("Watchdog returned duplicate telemetry samples")
    if any(
        not start_unix_ms <= row["unix_ms"] <= end_unix_ms for row in samples
    ):
        raise WatchdogClientError("Watchdog returned telemetry outside the workload")
    return samples
