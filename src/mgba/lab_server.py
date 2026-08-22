"""Small provider-neutral HTTP boundary for the competition lab.

Only a trusted Cloudflare Worker should call this service.  The public browser
never receives the runner token and cannot submit paths, model names, Cell ids,
or arbitrary perturbations.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .lab import LabExperimentRequest, run_lab_experiment


MAX_BODY_BYTES = 2048
MAX_RUNS_PER_HOUR = 5
MAX_CONCURRENT_RUNS = 2
RUN_TIMEOUT_SECONDS = 45

_executor = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_RUNS,
    thread_name_prefix="mgba-lab-run",
)
_state_lock = threading.Lock()
_active_runs = 0
_rate_windows: dict[str, list[float]] = {}
_cache: dict[str, dict[str, Any]] = {}


def _claim_run_slot() -> bool:
    global _active_runs
    with _state_lock:
        if _active_runs >= MAX_CONCURRENT_RUNS:
            return False
        _active_runs += 1
        return True


def _release_run_slot(_: object | None = None) -> None:
    global _active_runs
    with _state_lock:
        _active_runs = max(0, _active_runs - 1)


def _allow_client(client_id: str, *, now: float | None = None) -> bool:
    current = time.time() if now is None else now
    cutoff = current - 3600.0
    with _state_lock:
        recent = [stamp for stamp in _rate_windows.get(client_id, []) if stamp >= cutoff]
        if len(recent) >= MAX_RUNS_PER_HOUR:
            _rate_windows[client_id] = recent
            return False
        recent.append(current)
        _rate_windows[client_id] = recent
        return True


class LabRequestHandler(BaseHTTPRequestHandler):
    server_version = "MGBA-Lab/0.1"

    def log_message(self, format: str, *args: object) -> None:
        # Keep the standard access log but never include request bodies or tokens.
        super().log_message(format, *args)

    def _json_response(self, status: HTTPStatus, payload: MappingLike) -> None:
        body = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = os.environ.get("MGBA_RUNNER_TOKEN", "")
        supplied = self.headers.get("Authorization", "")
        if not expected or not supplied.startswith("Bearer "):
            return False
        return hmac.compare_digest(supplied[7:], expected)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path == "/healthz":
            self._json_response(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "mgba-lab-runner",
                    "model_status": "reference-model execution boundary",
                },
            )
            return
        self._json_response(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path != "/v1/experiments":
            self._json_response(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._json_response(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if self.headers.get_content_type() != "application/json":
            self._json_response(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"error": "content_type_must_be_json"},
            )
            return
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdigit():
            self._json_response(HTTPStatus.LENGTH_REQUIRED, {"error": "content_length_required"})
            return
        length = int(raw_length)
        if length < 2 or length > MAX_BODY_BYTES:
            self._json_response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request_too_large"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            request = LabExperimentRequest.from_mapping(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_request", "detail": str(error)},
            )
            return
        with _state_lock:
            cached = _cache.get(request.run_id)
        if cached is not None:
            self._json_response(
                HTTPStatus.OK,
                {"run_id": request.run_id, "cached": True, "bundle": cached},
            )
            return
        client_id = self.headers.get("X-MGBA-Client-IP", "unknown")[:128]
        if not _allow_client(client_id):
            self._json_response(
                HTTPStatus.TOO_MANY_REQUESTS,
                {"error": "rate_limited", "retry_after_seconds": 3600},
            )
            return
        if not _claim_run_slot():
            self._json_response(
                HTTPStatus.TOO_MANY_REQUESTS,
                {"error": "runner_busy", "retry_after_seconds": 10},
            )
            return
        project_root = Path(os.environ.get("MGBA_PROJECT_ROOT", Path.cwd())).resolve()
        future = _executor.submit(run_lab_experiment, request, project_root=project_root)
        future.add_done_callback(_release_run_slot)
        try:
            bundle = future.result(timeout=RUN_TIMEOUT_SECONDS)
        except FutureTimeout:
            self._json_response(
                HTTPStatus.GATEWAY_TIMEOUT,
                {"error": "runner_timeout", "fallback_bundle_id": "state-intervention"},
            )
            return
        except Exception as error:  # fail closed at the service boundary
            self._json_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "runner_failed", "detail": type(error).__name__},
            )
            return
        with _state_lock:
            _cache[request.run_id] = bundle
        self._json_response(
            HTTPStatus.OK,
            {"run_id": request.run_id, "cached": False, "bundle": bundle},
        )


MappingLike = dict[str, Any]


def main() -> None:
    host = os.environ.get("MGBA_LAB_HOST", "0.0.0.0")
    port = int(os.environ.get("MGBA_LAB_PORT", "8080"))
    if not os.environ.get("MGBA_RUNNER_TOKEN"):
        raise SystemExit("MGBA_RUNNER_TOKEN must be configured")
    server = ThreadingHTTPServer((host, port), LabRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
