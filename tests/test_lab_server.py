import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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


if __name__ == "__main__":
    unittest.main()
