from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from quota_watch.common.models import DeviceSnapshot
from quota_watch.common.signing import sign_request
from quota_watch.server.app import create_app
from quota_watch.server.config import ServerConfig


DEVICE_SECRET = "d" * 64
WIDGET_SECRET = "w" * 64


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        config = ServerConfig(
            database_path=Path(self.temp_dir.name) / "test.sqlite3",
            device_keys={"macbook-pro": DEVICE_SECRET},
            widget_keys=frozenset({WIDGET_SECRET}),
        )
        self.client = TestClient(create_app(config))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _signed_headers(self, body: bytes, *, nonce: str = "unique-nonce") -> dict[str, str]:
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        path = "/v1/ingest/macbook-pro"
        return {
            "X-QWB-Timestamp": timestamp,
            "X-QWB-Nonce": nonce,
            "X-QWB-Signature": sign_request(
                secret=DEVICE_SECRET,
                method="POST",
                path=path,
                timestamp=timestamp,
                nonce=nonce,
                body=body,
            ),
            "Content-Type": "application/json",
        }

    def test_signed_ingest_and_authenticated_widget(self) -> None:
        snapshot = DeviceSnapshot(
            device_id="macbook-pro",
            display_name="MacBook Pro",
            sent_at=datetime.now(timezone.utc),
        )
        body = snapshot.model_dump_json().encode()
        response = self.client.post(
            "/v1/ingest/macbook-pro",
            content=body,
            headers=self._signed_headers(body),
        )
        self.assertEqual(response.status_code, 204)

        denied = self.client.get("/v1/widget")
        self.assertEqual(denied.status_code, 401)

        widget = self.client.get(
            "/v1/widget", headers={"X-Widget-Key": WIDGET_SECRET}
        )
        self.assertEqual(widget.status_code, 200)
        self.assertEqual(widget.json()["laptops"][0]["id"], "macbook-pro")
        self.assertEqual(widget.headers["cache-control"], "private, no-store")

    def test_replay_is_rejected(self) -> None:
        body = json.dumps(
            {
                "schema_version": 1,
                "device_id": "macbook-pro",
                "display_name": "MacBook Pro",
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "agent_version": "test",
                "limits": {},
                "activity": {},
            },
            separators=(",", ":"),
        ).encode()
        headers = self._signed_headers(body, nonce="same-nonce")
        self.assertEqual(
            self.client.post("/v1/ingest/macbook-pro", content=body, headers=headers).status_code,
            204,
        )
        self.assertEqual(
            self.client.post("/v1/ingest/macbook-pro", content=body, headers=headers).status_code,
            409,
        )

    def test_invalid_signature_does_not_consume_device_allowance(self) -> None:
        config = ServerConfig(
            database_path=Path(self.temp_dir.name) / "auth-limit.sqlite3",
            device_keys={"macbook-pro": DEVICE_SECRET},
            widget_keys=frozenset({WIDGET_SECRET}),
            ingest_requests_per_minute=1,
        )
        client = TestClient(create_app(config))
        snapshot = DeviceSnapshot(
            device_id="macbook-pro",
            display_name="MacBook Pro",
            sent_at=datetime.now(timezone.utc),
        )
        body = snapshot.model_dump_json().encode()
        invalid = self._signed_headers(body, nonce="invalid-first")
        invalid["X-QWB-Signature"] = "0" * 64
        self.assertEqual(
            client.post("/v1/ingest/macbook-pro", content=body, headers=invalid).status_code,
            401,
        )
        valid = self._signed_headers(body, nonce="valid-second")
        self.assertEqual(
            client.post("/v1/ingest/macbook-pro", content=body, headers=valid).status_code,
            204,
        )

    def test_ingest_ip_limit_applies_before_authentication(self) -> None:
        config = ServerConfig(
            database_path=Path(self.temp_dir.name) / "ip-limit.sqlite3",
            device_keys={"macbook-pro": DEVICE_SECRET},
            widget_keys=frozenset({WIDGET_SECRET}),
            ingest_requests_per_ip_minute=1,
        )
        client = TestClient(create_app(config))
        self.assertEqual(client.post("/v1/ingest/unknown", content=b"{}").status_code, 401)
        limited = client.post("/v1/ingest/unknown", content=b"{}")
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["retry-after"], "60")

    def test_widget_ip_limit(self) -> None:
        config = ServerConfig(
            database_path=Path(self.temp_dir.name) / "widget-limit.sqlite3",
            device_keys={"macbook-pro": DEVICE_SECRET},
            widget_keys=frozenset({WIDGET_SECRET}),
            widget_requests_per_ip_minute=1,
        )
        client = TestClient(create_app(config))
        headers = {"X-Widget-Key": WIDGET_SECRET}
        self.assertEqual(client.get("/v1/widget", headers=headers).status_code, 200)
        self.assertEqual(client.get("/v1/widget", headers=headers).status_code, 429)


if __name__ == "__main__":
    unittest.main()
