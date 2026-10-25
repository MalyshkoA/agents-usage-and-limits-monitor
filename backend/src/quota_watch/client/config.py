from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class ClientConfig:
    server_url: str
    device_id: str
    display_name: str
    device_secret: str
    state_dir: Path
    check_seconds: float = 5.0
    limit_poll_seconds: float = 5.0
    active_state_ttl_seconds: int = 0
    account_id: str = "default"
    codex_enabled: bool = True
    codex_binary: str = "codex"
    codex_poll_when_idle: bool = False
    claude_enabled: bool = True

    @classmethod
    def load(cls, path: Path) -> "ClientConfig":
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        secret_env = raw.get("device_secret_env", "QWB_DEVICE_SECRET")
        secret = os.environ.get(secret_env, "")
        secret_file = raw.get("device_secret_file")
        if not secret and secret_file:
            secret_path = Path(str(secret_file)).expanduser()
            if os.name == "posix" and stat.S_IMODE(secret_path.stat().st_mode) & 0o077:
                raise ValueError(f"Secret file {secret_path} must have mode 600")
            secret = secret_path.read_text(encoding="utf-8").strip()
        if len(secret) < 32:
            raise ValueError(
                f"Set {secret_env} or device_secret_file to a 32+ character secret"
            )
        providers = raw.get("providers", {})
        codex = providers.get("codex", {})
        claude = providers.get("claude", {})
        server_url = str(raw["server_url"]).rstrip("/")
        parsed_url = urlparse(server_url)
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if parsed_url.scheme != "https" and parsed_url.hostname not in local_hosts:
            raise ValueError("server_url must use HTTPS (HTTP is allowed only for localhost)")
        config = cls(
            server_url=server_url,
            device_id=str(raw["device_id"]),
            display_name=str(raw["display_name"]),
            device_secret=secret,
            state_dir=Path(raw.get("state_dir", "~/.local/state/quota-watch")).expanduser(),
            check_seconds=float(raw.get("check_seconds", raw.get("poll_seconds", 5))),
            limit_poll_seconds=float(raw.get("limit_poll_seconds", 5)),
            active_state_ttl_seconds=int(raw.get("active_state_ttl_seconds", 0)),
            account_id=str(raw.get("account_id", "default")),
            codex_enabled=bool(codex.get("enabled", True)),
            codex_binary=str(codex.get("binary", "codex")),
            codex_poll_when_idle=bool(codex.get("poll_when_idle", False)),
            claude_enabled=bool(claude.get("enabled", True)),
        )
        if config.check_seconds <= 0:
            raise ValueError("check_seconds must be greater than zero")
        if config.limit_poll_seconds <= 0:
            raise ValueError("limit_poll_seconds must be greater than zero")
        if config.active_state_ttl_seconds < 0:
            raise ValueError("active_state_ttl_seconds must be zero or greater")
        return config
