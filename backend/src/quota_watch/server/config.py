from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerConfig:
    database_path: Path
    device_keys: dict[str, str]
    widget_keys: frozenset[str]
    device_stale_seconds: int = 180
    limit_stale_seconds: int = 900
    active_state_ttl_seconds: int = 0
    signature_max_age_seconds: int = 300
    max_body_bytes: int = 64 * 1024
    ingest_requests_per_minute: int = 30
    ingest_requests_per_ip_minute: int = 90
    global_ingest_requests_per_minute: int = 600
    widget_requests_per_ip_minute: int = 120
    limit_source_devices: frozenset[str] = frozenset()

    @classmethod
    def from_env(cls) -> "ServerConfig":
        device_keys_raw = os.environ.get("QWB_DEVICE_KEYS_JSON", "{}")
        device_keys = json.loads(device_keys_raw)
        if not isinstance(device_keys, dict):
            raise ValueError("QWB_DEVICE_KEYS_JSON must be a JSON object")

        widget_keys = frozenset(
            value.strip()
            for value in os.environ.get("QWB_WIDGET_KEYS", "").split(",")
            if value.strip()
        )

        config = cls(
            database_path=Path(
                os.environ.get("QWB_DATABASE_PATH", "./runtime/quota-watch.sqlite3")
            ),
            device_keys={str(key): str(value) for key, value in device_keys.items()},
            widget_keys=widget_keys,
            device_stale_seconds=int(os.environ.get("QWB_DEVICE_STALE_SECONDS", "180")),
            limit_stale_seconds=int(os.environ.get("QWB_LIMIT_STALE_SECONDS", "900")),
            active_state_ttl_seconds=int(
                os.environ.get("QWB_ACTIVE_STATE_TTL_SECONDS", "0")
            ),
            signature_max_age_seconds=int(
                os.environ.get("QWB_SIGNATURE_MAX_AGE_SECONDS", "300")
            ),
            max_body_bytes=int(os.environ.get("QWB_MAX_BODY_BYTES", str(64 * 1024))),
            ingest_requests_per_minute=int(
                os.environ.get("QWB_INGEST_REQUESTS_PER_MINUTE", "30")
            ),
            ingest_requests_per_ip_minute=int(
                os.environ.get("QWB_INGEST_REQUESTS_PER_IP_MINUTE", "90")
            ),
            global_ingest_requests_per_minute=int(
                os.environ.get("QWB_GLOBAL_INGEST_REQUESTS_PER_MINUTE", "600")
            ),
            widget_requests_per_ip_minute=int(
                os.environ.get("QWB_WIDGET_REQUESTS_PER_IP_MINUTE", "120")
            ),
            limit_source_devices=frozenset(
                value.strip()
                for value in os.environ.get("QWB_LIMIT_SOURCE_DEVICES", "").split(",")
                if value.strip()
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.device_keys:
            raise ValueError("At least one device key is required")
        if not self.widget_keys:
            raise ValueError("At least one widget key is required")
        for device_id, secret in self.device_keys.items():
            if len(secret) < 32:
                raise ValueError(f"Device key for {device_id!r} must be at least 32 characters")
        for secret in self.widget_keys:
            if len(secret) < 32:
                raise ValueError("Widget keys must be at least 32 characters")
        if self.active_state_ttl_seconds < 0:
            raise ValueError("QWB_ACTIVE_STATE_TTL_SECONDS must be zero or greater")
        rate_limits = {
            "QWB_INGEST_REQUESTS_PER_MINUTE": self.ingest_requests_per_minute,
            "QWB_INGEST_REQUESTS_PER_IP_MINUTE": self.ingest_requests_per_ip_minute,
            "QWB_GLOBAL_INGEST_REQUESTS_PER_MINUTE": (
                self.global_ingest_requests_per_minute
            ),
            "QWB_WIDGET_REQUESTS_PER_IP_MINUTE": self.widget_requests_per_ip_minute,
        }
        for name, value in rate_limits.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
