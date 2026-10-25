from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quota_watch.common.models import DeviceSnapshot


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS device_snapshots (
                    device_id TEXT PRIMARY KEY,
                    received_at TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS request_nonces (
                    device_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    seen_at TEXT NOT NULL,
                    PRIMARY KEY (device_id, nonce)
                );
                CREATE INDEX IF NOT EXISTS idx_request_nonces_seen_at
                    ON request_nonces(seen_at);
                """
            )

    def save_snapshot(self, snapshot: DeviceSnapshot, received_at: datetime) -> None:
        payload_json = snapshot.model_dump_json()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO device_snapshots(device_id, received_at, sent_at, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    received_at=excluded.received_at,
                    sent_at=excluded.sent_at,
                    payload_json=excluded.payload_json
                WHERE excluded.sent_at >= device_snapshots.sent_at
                """,
                (
                    snapshot.device_id,
                    received_at.isoformat(),
                    snapshot.sent_at.isoformat(),
                    payload_json,
                ),
            )

    def list_snapshots(self) -> list[tuple[DeviceSnapshot, datetime]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT received_at, payload_json FROM device_snapshots ORDER BY device_id"
            ).fetchall()
        return [
            (
                DeviceSnapshot.model_validate_json(row["payload_json"]),
                datetime.fromisoformat(row["received_at"]),
            )
            for row in rows
        ]

    def claim_nonce(
        self, *, device_id: str, nonce: str, now: datetime, ttl_seconds: int
    ) -> bool:
        cutoff = now - timedelta(seconds=ttl_seconds)
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM request_nonces WHERE seen_at < ?", (cutoff.isoformat(),)
            )
            try:
                connection.execute(
                    "INSERT INTO request_nonces(device_id, nonce, seen_at) VALUES (?, ?, ?)",
                    (device_id, nonce, now.isoformat()),
                )
            except sqlite3.IntegrityError:
                return False
        return True
