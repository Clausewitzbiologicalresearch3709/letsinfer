#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Small TLS/auth boundary for DwarfStar's loopback OpenAI HTTP server."""

from __future__ import annotations

import argparse
import http.client
import http.server
import ipaddress
import json
import os
import secrets
import signal
import socket
import ssl
import subprocess
import sys
import threading
from typing import Any, Sequence


BACKEND_PORT_MARKER = "@LETSINFER_BACKEND_PORT@"
CONTROL_CONNECTION_RESERVE = 2
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class GatewayServer(http.server.ThreadingHTTPServer):
    """A bounded HTTPS frontend for one loopback DwarfStar server."""

    # A managed restart can follow an active request closely enough that the
    # prior listener still has connections in TIME_WAIT.  Reuse only the same
    # local address so the replacement process can bind immediately; this does
    # not permit two live listeners to own the port.
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        api_key: str,
        backend_host: str,
        backend_port: int,
        expected_model: str,
        max_connections: int,
        max_active_requests: int,
        max_request_bytes: int,
    ) -> None:
        self.api_key = api_key
        self.backend_host = backend_host
        self.backend_port = backend_port
        self.expected_model = expected_model
        self.connection_slots = threading.BoundedSemaphore(max_connections)
        self.worker_slots = threading.BoundedSemaphore(
            max_connections + CONTROL_CONNECTION_RESERVE
        )
        self.active_slots = threading.BoundedSemaphore(max_active_requests)
        self.max_request_bytes = max_request_bytes
        self.request_queue_size = max_connections + CONTROL_CONNECTION_RESERVE
        self.tls_context: ssl.SSLContext | None = None
        super().__init__(address, GatewayHandler)

    def get_request(self) -> tuple[socket.socket, Any]:
        request, address = self.socket.accept()
        request.settimeout(10)
        if self.tls_context is not None:
            try:
                request = self.tls_context.wrap_socket(request, server_side=True)
            except BaseException:
                request.close()
                raise
        request.settimeout(30)
        return request, address

    def process_request(self, request: Any, client_address: Any) -> None:
        self.worker_slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.worker_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.worker_slots.release()


class GatewayHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Let's Infer"
    sys_version = ""

    @property
    def gateway(self) -> GatewayServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, _format: str, *_arguments: Any) -> None:
        # DwarfStar owns request logging. Avoid duplicating paths or headers at
        # the credential boundary.
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _authorized(self) -> bool:
        authorization = self.headers.get("Authorization", "")
        scheme, separator, value = authorization.partition(" ")
        return bool(
            separator
            and scheme.lower() == "bearer"
            and secrets.compare_digest(value, self.gateway.api_key)
        )

    def _safe_path(self) -> bool:
        return self.path.startswith("/") and "://" not in self.path

    def _health(self) -> None:
        connection = http.client.HTTPConnection(
            self.gateway.backend_host, self.gateway.backend_port, timeout=3
        )
        try:
            connection.request("GET", "/v1/models", headers={"Connection": "close"})
            response = connection.getresponse()
            body = response.read(1024 * 1024)
            if response.status != 200:
                raise RuntimeError(f"backend returned {response.status}")
            payload = json.loads(body)
            entries = payload.get("data", payload.get("models", []))
            model_ids = {
                entry.get("id")
                for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            }
            if self.gateway.expected_model not in model_ids:
                raise RuntimeError("backend model identity does not match")
        except (OSError, ValueError, RuntimeError, http.client.HTTPException):
            self._send_json(503, {"status": "starting"})
            return
        finally:
            connection.close()
        self._send_json(200, {"status": "ok"})

    def _request_body(self) -> bytes | None:
        if self.headers.get("Transfer-Encoding"):
            self._send_json(501, {"error": {"message": "chunked requests unsupported"}})
            return None
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            self._send_json(400, {"error": {"message": "invalid content length"}})
            return None
        if length < 0 or length > self.gateway.max_request_bytes:
            self._send_json(413, {"error": {"message": "request body too large"}})
            return None
        try:
            return self.rfile.read(length)
        except OSError:
            self.close_connection = True
            return None

    def _proxy(self) -> None:
        if not self._safe_path():
            self._send_json(400, {"error": {"message": "invalid request target"}})
            return
        if not self._authorized():
            self._send_json(401, {"error": {"message": "unauthorized"}})
            return
        body = self._request_body()
        if body is None:
            return
        if not self.gateway.connection_slots.acquire(blocking=False):
            self._send_json(
                503, {"error": {"message": "inference connection capacity reached"}}
            )
            return
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower()
            not in HOP_BY_HOP_HEADERS | {"authorization", "content-length", "host"}
        }
        headers["Host"] = f"{self.gateway.backend_host}:{self.gateway.backend_port}"
        headers["Connection"] = "close"
        if body:
            headers["Content-Length"] = str(len(body))

        try:
            self.gateway.active_slots.acquire()
            connection = http.client.HTTPConnection(
                self.gateway.backend_host, self.gateway.backend_port, timeout=None
            )
            headers_sent = False
            try:
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                self.send_response(response.status, response.reason)
                for key, value in response.getheaders():
                    lowered = key.lower()
                    if lowered in HOP_BY_HOP_HEADERS | {"date", "server"}:
                        continue
                    self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                headers_sent = True
                while True:
                    chunk = response.read1(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                self.close_connection = True
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except (OSError, http.client.HTTPException):
                if not headers_sent:
                    self._send_json(502, {"error": {"message": "backend unavailable"}})
                else:
                    self.close_connection = True
            finally:
                connection.close()
                self.gateway.active_slots.release()
        finally:
            self.gateway.connection_slots.release()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/health":
            self._health()
        else:
            self._proxy()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._proxy()

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._proxy()

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._proxy()


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--listen-host", required=True)
    result.add_argument("--listen-port", required=True, type=_positive)
    result.add_argument("--backend-host", required=True)
    result.add_argument("--backend-port", required=True, type=int)
    result.add_argument("--api-key-file", required=True)
    result.add_argument("--tls-cert-file", required=True)
    result.add_argument("--tls-key-file", required=True)
    result.add_argument("--expected-model", required=True)
    result.add_argument("--max-connections", required=True, type=_positive)
    result.add_argument("--max-active-requests", required=True, type=_positive)
    result.add_argument("--max-request-bytes", type=_positive, default=64 << 20)
    result.add_argument("--shutdown-timeout-seconds", type=_positive, default=110)
    result.add_argument("child", nargs=argparse.REMAINDER)
    return result


def _unused_loopback_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


def _terminate_child(child: subprocess.Popen[bytes], timeout: int) -> None:
    if child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=timeout)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


def main(arguments: Sequence[str] | None = None) -> int:
    options = parser().parse_args(arguments)
    try:
        if not ipaddress.ip_address(options.backend_host).is_loopback:
            raise ValueError("backend host must be a loopback address")
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if options.backend_port < 0 or options.backend_port > 65535:
        raise SystemExit("backend port must be between 0 and 65535")
    if options.listen_port > 65535:
        raise SystemExit("listen port must be at most 65535")
    if options.max_active_requests > options.max_connections:
        raise SystemExit("max active requests cannot exceed max connections")
    child_command = list(options.child)
    if child_command[:1] == ["--"]:
        child_command.pop(0)
    if not child_command:
        raise SystemExit("a DwarfStar child command is required after --")
    if child_command.count(BACKEND_PORT_MARKER) != 1:
        raise SystemExit(f"child command must contain one {BACKEND_PORT_MARKER}")

    with open(options.api_key_file, encoding="ascii") as key_file:
        api_key = key_file.read().strip()
    if not api_key:
        raise SystemExit("API key file is empty")
    backend_port = options.backend_port or _unused_loopback_port(options.backend_host)
    child_command = [
        str(backend_port) if value == BACKEND_PORT_MARKER else value
        for value in child_command
    ]

    server = GatewayServer(
        (options.listen_host, options.listen_port),
        api_key=api_key,
        backend_host=options.backend_host,
        backend_port=backend_port,
        expected_model=options.expected_model,
        max_connections=options.max_connections,
        max_active_requests=options.max_active_requests,
        max_request_bytes=options.max_request_bytes,
    )
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(options.tls_cert_file, options.tls_key_file)
    server.tls_context = tls

    stopping = threading.Event()
    received_signal: list[int] = []

    def stop(signum: int, _frame: Any) -> None:
        received_signal.append(signum)
        stopping.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)

    child: subprocess.Popen[bytes] | None = None
    serving: threading.Thread | None = None
    try:
        child = subprocess.Popen(child_command, start_new_session=True)
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        while child.poll() is None and not stopping.wait(0.25):
            pass
        if received_signal:
            return 0
        code = child.poll()
        return code if code not in (None, 0) else 1
    finally:
        if serving is not None:
            server.shutdown()
        server.server_close()
        if serving is not None:
            serving.join(timeout=2)
        if child is not None:
            _terminate_child(child, options.shutdown_timeout_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ssl.SSLError) as error:
        print(f"dwarfstar gateway: {error}", file=sys.stderr)
        raise SystemExit(1) from error
