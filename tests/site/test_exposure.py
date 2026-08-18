# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import json
import pathlib
import subprocess
import unittest

from core import exposure


class _Tailscale:
    def __init__(self, status: dict | None = None) -> None:
        self.status = status or {}
        self.commands: list[list[str]] = []

    def __call__(self, command):
        value = list(command)
        self.commands.append(value)
        arguments = value[1:]
        if arguments == ["funnel", "status", "--json"]:
            payload = self.status
        elif arguments == ["status", "--json"]:
            payload = {"Self": {"DNSName": "inference.example.ts.net."}}
        elif arguments[:2] == ["funnel", "reset"]:
            self.status = {}
            payload = None
        elif arguments[:3] == ["funnel", "--bg", "--yes"]:
            self.status = {
                "TCP": {"443": {"HTTPS": True}},
                "Web": {
                    "inference.example.ts.net:443": {
                        "Handlers": {
                            "/": {"Proxy": exposure.INFERENCE_TARGET}
                        }
                    }
                },
                "AllowFunnel": {"inference.example.ts.net:443": True},
            }
            payload = None
        else:
            return subprocess.CompletedProcess(value, 1, "", "unexpected")
        return subprocess.CompletedProcess(
            value, 0, "" if payload is None else json.dumps(payload), ""
        )


class ExposureProviderTests(unittest.TestCase):
    def test_funnel_owns_only_inference_and_reset_is_hash_bound(self) -> None:
        runner = _Tailscale()
        result = exposure.enable_tailscale(
            runner=runner, executable=pathlib.Path("/usr/bin/tailscale")
        )
        self.assertEqual(result.public_url, "https://inference.example.ts.net")
        self.assertEqual(result.inference_target, exposure.INFERENCE_TARGET)
        verified = exposure.verify_tailscale(
            result.configuration_sha256,
            runner=runner,
            executable=pathlib.Path("/usr/bin/tailscale"),
        )
        self.assertEqual(verified, result)
        exposure.disable_tailscale(
            result.configuration_sha256,
            runner=runner,
            executable=pathlib.Path("/usr/bin/tailscale"),
        )
        self.assertEqual(runner.status, {})

    def test_existing_or_control_plane_funnel_configuration_fails_closed(self) -> None:
        existing = _Tailscale({"Web": {"other": {"Proxy": "http://127.0.0.1:9000"}}})
        with self.assertRaisesRegex(exposure.ExposureError, "already has"):
            exposure.enable_tailscale(
                runner=existing, executable=pathlib.Path("/usr/bin/tailscale")
            )

        unsafe = _Tailscale({
            "TCP": {"443": {"HTTPS": True}},
            "Web": {
                "site:443": {
                    "Handlers": {
                        "/": {"Proxy": exposure.INFERENCE_TARGET},
                        "/private": {"Proxy": "http://127.0.0.1:9771"},
                    },
                }
            },
            "AllowFunnel": {"site:443": True},
        })
        digest = "0" * 64
        with self.assertRaisesRegex(exposure.ExposureError, "proxy only"):
            exposure.disable_tailscale(
                digest, runner=unsafe, executable=pathlib.Path("/usr/bin/tailscale")
            )

    def test_extra_listener_or_configuration_is_rejected(self) -> None:
        extra_listener = _Tailscale({
            "TCP": {
                "443": {"HTTPS": True},
                "22": {"TCPForward": "127.0.0.1:22"},
            },
            "Web": {
                "site:443": {
                    "Handlers": {"/": {"Proxy": exposure.INFERENCE_TARGET}}
                }
            },
            "AllowFunnel": {"site:443": True},
        })
        with self.assertRaisesRegex(exposure.ExposureError, "exactly one HTTPS"):
            exposure.verify_tailscale(
                "0" * 64,
                runner=extra_listener,
                executable=pathlib.Path("/usr/bin/tailscale"),
            )

        extra_state = _Tailscale({
            "TCP": {"443": {"HTTPS": True}},
            "Web": {
                "site:443": {
                    "Handlers": {"/": {"Proxy": exposure.INFERENCE_TARGET}}
                }
            },
            "AllowFunnel": {"site:443": True},
            "Foreground": {"unexpected": {}},
        })
        with self.assertRaisesRegex(exposure.ExposureError, "exclusively inference-owned"):
            exposure.verify_tailscale(
                "0" * 64,
                runner=extra_state,
                executable=pathlib.Path("/usr/bin/tailscale"),
            )


if __name__ == "__main__":
    unittest.main()
