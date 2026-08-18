#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the dependency-free Watchdog telemetry client."""

from __future__ import annotations

import unittest

from benchmarks import watchdog_client


class WatchdogClientTests(unittest.TestCase):
    def test_history_batch_decodes_required_metrics(self) -> None:
        gpu = b"".join(
            (
                watchdog_client._uint(1, 95),
                watchdog_client._uint(4, 740 << 1),
                watchdog_client._uint(6, 2100),
                watchdog_client._uint(7, 0xFFFFFFFF),
            )
        )
        telemetry = b"".join(
            (
                watchdog_client._uint(1, 7),
                watchdog_client._uint(2, 1_800_000_000_000),
                watchdog_client._uint(5, 67),
                watchdog_client._uint(8, 72),
                watchdog_client._message(9, gpu),
                watchdog_client._uint(10, 690 << 1),
                watchdog_client._uint(11, 485 << 1),
                watchdog_client._uint(19, 1024),
                watchdog_client._uint(20, 512),
                watchdog_client._uint(23, 3800),
                watchdog_client._uint(24, 0xFFFFFFFF),
            )
        )
        batch = watchdog_client._message(1, telemetry)
        envelope = watchdog_client._uint(1, 1) + watchdog_client._message(11, batch)

        kind, samples = watchdog_client.decode_server_envelope(envelope)

        self.assertEqual(kind, "samples")
        self.assertEqual(
            samples,
            [
                {
                    "sequence": 7,
                    "unix_ms": 1_800_000_000_000,
                    "cpu_percent": 67,
                    "gpu_percent": 95,
                    "disk_percent": 72,
                    "system_temp_deci_c": 690,
                    "gpu_temp_deci_c": 740,
                    "nvme_temp_deci_c": 485,
                    "disk_read_kib_s": 1024,
                    "disk_write_kib_s": 512,
                    "cpu_clock_mhz": 3800,
                    "gpu_clock_mhz": 2100,
                    "vram_clock_mhz": -1,
                    "system_ram_clock_mhz": -1,
                }
            ],
        )

    def test_history_complete_decodes(self) -> None:
        complete = watchdog_client._uint(1, 7)
        envelope = watchdog_client._uint(1, 1) + watchdog_client._message(12, complete)
        self.assertEqual(
            watchdog_client.decode_server_envelope(envelope), ("complete", None)
        )


if __name__ == "__main__":
    unittest.main()
