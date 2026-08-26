import http.client
import json
import os
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mgba import lab_server
from mgba.lab import LAB_REQUEST_SCHEMA
from mgba.lab_server import LabRequestHandler


class LabServerBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.previous_token = os.environ.get("MGBA_RUNNER_TOKEN")
        os.environ["MGBA_RUNNER_TOKEN"] = "test-runner-token"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), LabRequestHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        if cls.previous_token is None:
            os.environ.pop("MGBA_RUNNER_TOKEN", None)
        else:
            os.environ["MGBA_RUNNER_TOKEN"] = cls.previous_token

    def _post(self, payload: dict, *, token: str | None = "test-runner-token", content_type: str = "application/json") -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": content_type}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(f"{self.base_url}/v1/experiments", data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def _valid_request(self) -> dict:
        return {
            "schema_version": LAB_REQUEST_SCHEMA,
            "scenario_id": "carm_high_immune_her2",
            "protocol_id": "state_conditioned_signal_expression",
            "dose": 0.7,
            "onset": "late",
            "exposure": "short",
        }
    def setUp(self) -> None:
        self._reset_lab_state()
        self.addCleanup(self._reset_lab_state)

    @staticmethod
    def _reset_lab_state() -> None:
        # The suite shares one process: never leak module-level runner state.
        lab_server._rate_windows.clear()
        lab_server._cache.clear()
        lab_server._active_runs = 0

    def _raw_post(self, path: str, body: bytes, headers: dict) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_health_is_public_and_contains_model_boundary(self) -> None:
        with urlopen(f"{self.base_url}/healthz", timeout=3) as response:
            payload = json.loads(response.read())
        self.assertEqual(200, response.status)
        self.assertEqual("reference-model execution boundary", payload["model_status"])

    def test_missing_service_token_is_rejected(self) -> None:
        status, payload = self._post(self._valid_request(), token=None)
        self.assertEqual(401, status)
        self.assertEqual("unauthorized", payload["error"])

    def test_non_json_body_is_rejected(self) -> None:
        status, payload = self._post(self._valid_request(), content_type="text/plain")
        self.assertEqual(415, status)
        self.assertEqual("content_type_must_be_json", payload["error"])

    def test_unknown_request_field_fails_closed_without_running(self) -> None:
        status, payload = self._post({**self._valid_request(), "target_cells": ["tumor-001"]})
        self.assertEqual(400, status)
        self.assertEqual("invalid_request", payload["error"])
    def test_run_slot_claim_and_release(self) -> None:
        self.assertTrue(lab_server._claim_run_slot())
        self.assertTrue(lab_server._claim_run_slot())
        self.assertFalse(lab_server._claim_run_slot())
        lab_server._release_run_slot()
        self.assertTrue(lab_server._claim_run_slot())

    def test_get_to_unknown_path_is_not_found(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            urlopen(f"{self.base_url}/v1/experiments", timeout=3)
        self.assertEqual(404, caught.exception.code)
        self.assertEqual("not_found", json.loads(caught.exception.read())["error"])

    def test_post_to_unknown_path_is_not_found_before_auth(self) -> None:
        body = json.dumps(self._valid_request()).encode("utf-8")
        status, payload = self._raw_post("/v1/unknown", body, {"Content-Type": "application/json"})
        self.assertEqual(404, status)
        self.assertEqual("not_found", payload["error"])

    def test_non_numeric_content_length_is_rejected(self) -> None:
        status, payload = self._raw_post(
            "/v1/experiments",
            b"{}",
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer test-runner-token",
                "Content-Length": "not-a-number",
            },
        )
        self.assertEqual(411, status)
        self.assertEqual("content_length_required", payload["error"])

    def test_empty_body_is_rejected_as_too_large(self) -> None:
        status, payload = self._raw_post(
            "/v1/experiments",
            b"",
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer test-runner-token",
            },
        )
        self.assertEqual(413, status)
        self.assertEqual("request_too_large", payload["error"])

    def test_oversized_body_is_rejected(self) -> None:
        status, payload = self._raw_post(
            "/v1/experiments",
            b"x" * 3000,
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer test-runner-token",
            },
        )
        self.assertEqual(413, status)
        self.assertEqual("request_too_large", payload["error"])

    @mock.patch("mgba.lab_server.run_lab_experiment")
    def test_successful_run_is_cached_by_run_id(self, fake_run: mock.MagicMock) -> None:
        fake_run.return_value = {"bundle_id": "b1"}
        status, payload = self._post(self._valid_request())
        self.assertEqual(200, status)
        self.assertFalse(payload["cached"])
        self.assertEqual({"bundle_id": "b1"}, payload["bundle"])
        status, payload = self._post(self._valid_request())
        self.assertEqual(200, status)
        self.assertTrue(payload["cached"])
        self.assertEqual({"bundle_id": "b1"}, payload["bundle"])
        self.assertEqual(1, fake_run.call_count)

    @mock.patch("mgba.lab_server.run_lab_experiment")
    def test_rate_limit_rejects_burst(self, fake_run: mock.MagicMock) -> None:
        lab_server._rate_windows["unknown"] = [time.time()] * lab_server.MAX_RUNS_PER_HOUR
        status, payload = self._post(self._valid_request())
        self.assertEqual(429, status)
        self.assertEqual("rate_limited", payload["error"])
        self.assertEqual(3600, payload["retry_after_seconds"])
        fake_run.assert_not_called()

    @mock.patch("mgba.lab_server.run_lab_experiment")
    def test_runner_busy_when_slots_exhausted(self, fake_run: mock.MagicMock) -> None:
        self.assertTrue(lab_server._claim_run_slot())
        self.assertTrue(lab_server._claim_run_slot())
        status, payload = self._post(self._valid_request())
        self.assertEqual(429, status)
        self.assertEqual("runner_busy", payload["error"])
        self.assertEqual(10, payload["retry_after_seconds"])
        fake_run.assert_not_called()

    @mock.patch("mgba.lab_server.run_lab_experiment")
    def test_runner_failure_leaks_only_exception_type(self, fake_run: mock.MagicMock) -> None:
        fake_run.side_effect = RuntimeError("internal path D:/models/secret")
        status, payload = self._post(self._valid_request())
        self.assertEqual(500, status)
        self.assertEqual("runner_failed", payload["error"])
        self.assertEqual("RuntimeError", payload["detail"])

    @mock.patch("mgba.lab_server.RUN_TIMEOUT_SECONDS", 0.05)
    @mock.patch("mgba.lab_server.run_lab_experiment")
    def test_runner_timeout_returns_fallback_bundle(self, fake_run: mock.MagicMock) -> None:
        fake_run.side_effect = lambda *args, **kwargs: time.sleep(1)
        status, payload = self._post(self._valid_request())
        self.assertEqual(504, status)
        self.assertEqual("runner_timeout", payload["error"])
        self.assertEqual("state-intervention", payload["fallback_bundle_id"])

class LabServerMainTests(unittest.TestCase):
    def test_main_requires_runner_token(self) -> None:
        with mock.patch.dict(os.environ, {"MGBA_RUNNER_TOKEN": ""}):
            with self.assertRaises(SystemExit):
                lab_server.main()

    def test_main_shuts_down_cleanly_on_keyboard_interrupt(self) -> None:
        server = mock.MagicMock()
        server.serve_forever.side_effect = KeyboardInterrupt
        executor = mock.MagicMock()
        with (
            mock.patch.dict(os.environ, {"MGBA_RUNNER_TOKEN": "test-runner-token"}),
            mock.patch("mgba.lab_server.ThreadingHTTPServer", return_value=server),
            mock.patch("mgba.lab_server._executor", executor),
        ):
            lab_server.main()
        server.serve_forever.assert_called_once_with()
        server.server_close.assert_called_once_with()
        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()

