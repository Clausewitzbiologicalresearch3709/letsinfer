# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import http.server
import importlib.util
import json
import pathlib
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request


MODULE_PATH = pathlib.Path(__file__).resolve().parents[2] / "adapters/dwarfstar/gateway.py"
SPEC = importlib.util.spec_from_file_location("dwarfstar_gateway", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)


class BackendHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    hold_requests = threading.Event()
    held_requests_started = threading.Event()
    held_requests = 0
    held_requests_lock = threading.Lock()

    def log_message(self, _format: str, *_arguments: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/v1/models":
            self.send_error(404)
            return
        body = json.dumps(
            {"object": "list", "data": [{"id": "fixture-paired-model"}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        request = self.rfile.read(length)
        if self.path == "/v1/token-count":
            body = json.dumps(
                {
                    "object": "token_count",
                    "model": "fixture-paired-model",
                    "prompt_tokens": 32768,
                },
                separators=(",", ":"),
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/hold":
            with self.held_requests_lock:
                type(self).held_requests += 1
                if type(self).held_requests == 2:
                    self.held_requests_started.set()
            self.hold_requests.wait(timeout=5)
        body = b"data: " + request + b"\n\ndata: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
        cls.backend_thread = threading.Thread(
            target=cls.backend.serve_forever, daemon=True
        )
        cls.backend_thread.start()
        cls.tls_directory = tempfile.TemporaryDirectory()
        tls_root = pathlib.Path(cls.tls_directory.name)
        cls.cert = tls_root / "server.crt"
        key = tls_root / "server.key"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-sha256",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=127.0.0.1",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
                "-keyout",
                str(key),
                "-out",
                str(cls.cert),
            ],
            check=True,
            capture_output=True,
        )
        cls.frontend = gateway.GatewayServer(
            ("127.0.0.1", 0),
            api_key="test-secret",
            backend_host="127.0.0.1",
            backend_port=cls.backend.server_port,
            expected_model="fixture-paired-model",
            max_connections=4,
            max_active_requests=2,
            max_request_bytes=1024,
        )
        server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_tls.load_cert_chain(cls.cert, key)
        cls.frontend.tls_context = server_tls
        cls.client_tls = ssl.create_default_context(cafile=str(cls.cert))
        cls.frontend_thread = threading.Thread(
            target=cls.frontend.serve_forever, daemon=True
        )
        cls.frontend_thread.start()
        cls.base_url = f"https://127.0.0.1:{cls.frontend.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.frontend.shutdown()
        cls.frontend.server_close()
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.frontend_thread.join(timeout=2)
        cls.backend_thread.join(timeout=2)
        cls.tls_directory.cleanup()

    def test_health_is_public_but_checks_exact_backend_model(self) -> None:
        with urllib.request.urlopen(
            f"{self.base_url}/health", timeout=2, context=self.client_tls
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), {"status": "ok"})

    def test_listener_allows_immediate_managed_restart(self) -> None:
        self.assertNotEqual(
            self.frontend.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR),
            0,
        )

    def test_health_remains_available_at_inference_connection_capacity(self) -> None:
        BackendHandler.hold_requests.clear()
        BackendHandler.held_requests_started.clear()
        BackendHandler.held_requests = 0
        errors: list[BaseException] = []

        def request() -> None:
            payload = b'{"model":"fixture-paired-model"}'
            call = urllib.request.Request(
                f"{self.base_url}/hold", data=payload, method="POST"
            )
            call.add_header("Authorization", "Bearer test-secret")
            try:
                with urllib.request.urlopen(
                    call, timeout=5, context=self.client_tls
                ) as response:
                    response.read()
            except BaseException as error:  # surfaced after every worker joins
                errors.append(error)

        workers = [threading.Thread(target=request) for _ in range(4)]
        try:
            for worker in workers:
                worker.start()
            self.assertTrue(BackendHandler.held_requests_started.wait(timeout=2))
            deadline = time.monotonic() + 2
            while self.frontend.connection_slots._value != 0:  # type: ignore[attr-defined]
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)

            with urllib.request.urlopen(
                f"{self.base_url}/health", timeout=2, context=self.client_tls
            ) as response:
                self.assertEqual(response.status, 200)

            overflow = urllib.request.Request(
                f"{self.base_url}/hold", data=b"{}", method="POST"
            )
            overflow.add_header("Authorization", "Bearer test-secret")
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(overflow, timeout=2, context=self.client_tls)
            self.assertEqual(raised.exception.code, 503)
        finally:
            BackendHandler.hold_requests.set()
            for worker in workers:
                worker.join(timeout=2)
        self.assertEqual(errors, [])

    def test_openai_routes_require_the_exact_bearer_key(self) -> None:
        for key in (None, "wrong"):
            request = urllib.request.Request(f"{self.base_url}/v1/models")
            if key is not None:
                request.add_header("Authorization", f"Bearer {key}")
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=2, context=self.client_tls)
            self.assertEqual(raised.exception.code, 401)

        request = urllib.request.Request(f"{self.base_url}/v1/models")
        request.add_header("Authorization", "Bearer test-secret")
        with urllib.request.urlopen(
            request, timeout=2, context=self.client_tls
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(
                json.load(response)["data"][0]["id"], "fixture-paired-model"
            )

    def test_streaming_response_is_forwarded_without_backend_auth(self) -> None:
        payload = b'{"model":"fixture-paired-model"}'
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions", data=payload, method="POST"
        )
        request.add_header("Authorization", "Bearer test-secret")
        request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(
            request, timeout=2, context=self.client_tls
        ) as response:
            self.assertEqual(response.status, 200)
            body = response.read()
        self.assertIn(payload, body)
        self.assertTrue(body.endswith(b"data: [DONE]\n\n"))

    def test_token_count_uses_the_authenticated_boundary(self) -> None:
        payload = b'{"model":"fixture-paired-model","messages":[]}'
        anonymous = urllib.request.Request(
            f"{self.base_url}/v1/token-count", data=payload, method="POST"
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(anonymous, timeout=2, context=self.client_tls)
        self.assertEqual(raised.exception.code, 401)

        request = urllib.request.Request(
            f"{self.base_url}/v1/token-count", data=payload, method="POST"
        )
        request.add_header("Authorization", "Bearer test-secret")
        request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(
            request, timeout=2, context=self.client_tls
        ) as response:
            self.assertEqual(
                json.load(response),
                {
                    "object": "token_count",
                    "model": "fixture-paired-model",
                    "prompt_tokens": 32768,
                },
            )


if __name__ == "__main__":
    unittest.main()
