"""Server-side limits poller.

Runs next to the bridge in its own container, signed in to Codex and Claude
with separate server sessions, and reports both accounts' limits as one
limits-only device. Computers then only send activity from IDE hooks.

    quota-watch-poller login [codex|claude]   interactive, once per volume
    quota-watch-poller status                 which sessions are present
    quota-watch-poller run                    default container command
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from quota_watch.client.agent import (
    _read_cached_limits,
    send_snapshot,
    snapshot_fingerprint,
)
from quota_watch.client.codex_adapter import CodexAdapterError, read_codex_limits
from quota_watch.client.config import ClientConfig
from quota_watch.common.models import DeviceSnapshot, Provider, ProviderLimits

AGENT_VERSION = "poller-0.1.0"
# Re-send unchanged limits now and then so the server keeps a fresh observed_at.
HEARTBEAT_SECONDS = 300


@dataclass(frozen=True)
class PollerConfig:
    server_url: str
    device_id: str
    secret: str
    account_id: str
    data_dir: Path
    codex_binary: str
    codex_seconds: float
    claude_collector: Path
    claude_seconds: float

    @classmethod
    def from_env(cls) -> "PollerConfig":
        secret = os.environ.get("QWB_POLLER_SECRET", "")
        return cls(
            server_url=os.environ.get("QWB_POLLER_SERVER_URL", "http://quota-watch:8787").rstrip("/"),
            device_id=os.environ.get("QWB_POLLER_DEVICE_ID", "server-poller"),
            secret=secret,
            account_id=os.environ.get("QWB_POLLER_ACCOUNT_ID", "personal"),
            data_dir=Path(os.environ.get("QWB_POLLER_DATA_DIR", "/data")),
            codex_binary=os.environ.get("QWB_POLLER_CODEX_BINARY", "codex"),
            codex_seconds=float(os.environ.get("QWB_POLL_CODEX_SECONDS", "15")),
            claude_collector=Path(
                os.environ.get("QWB_POLLER_CLAUDE_COLLECTOR", "/opt/claude_usage/collect.mjs")
            ),
            claude_seconds=float(os.environ.get("QWB_POLL_CLAUDE_SECONDS", "15")),
        )

    @property
    def claude_token_file(self) -> Path:
        # Legacy `claude setup-token` token: inference scope only, so Claude
        # refuses to report plan limits with it. Kept as a fallback.
        return self.data_dir / "claude-oauth-token"

    @property
    def claude_credentials_file(self) -> Path:
        # Written by `claude auth login`; HOME points into the /data volume.
        return Path(os.environ.get("HOME", self.data_dir / "home")) / ".claude" / ".credentials.json"

    @property
    def claude_signed_in(self) -> Path:
        return self.claude_credentials_file if self.claude_credentials_file.exists() else self.claude_token_file

    @property
    def codex_auth_file(self) -> Path:
        return Path(os.environ.get("CODEX_HOME", self.data_dir / "codex")) / "auth.json"

    def client(self) -> ClientConfig:
        return ClientConfig(
            server_url=self.server_url,
            device_id=self.device_id,
            display_name="Server limits poller",
            device_secret=self.secret,
            state_dir=self.data_dir,
            account_id=self.account_id,
        )


def log(message: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}", flush=True)


def poll_codex(config: PollerConfig) -> ProviderLimits:
    return read_codex_limits(config.codex_binary, account_id=config.account_id, timeout=30)


def poll_claude(config: PollerConfig) -> ProviderLimits:
    env = dict(os.environ)
    if not config.claude_credentials_file.exists():
        env["CLAUDE_CODE_OAUTH_TOKEN"] = config.claude_token_file.read_text(encoding="utf-8").strip()
    with tempfile.TemporaryDirectory(dir=config.data_dir) as tmp:
        state_file = Path(tmp) / "claude-limits.json"
        result = subprocess.run(
            ["node", str(config.claude_collector), str(state_file)],
            env=env,
            cwd=config.claude_collector.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip()[-300:] or "collector failed")
        limits = _read_cached_limits(
            state_file, account_id=config.account_id, default_source="claude-agent-sdk-usage"
        )
    if limits is None:
        raise RuntimeError("collector wrote no limits")
    return limits


def build_snapshot(config: PollerConfig, limits: dict[Provider, ProviderLimits]) -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id=config.device_id,
        display_name="Server limits poller",
        sent_at=datetime.now(timezone.utc),
        agent_version=AGENT_VERSION,
        delivery_mode="change_only",
        limits=dict(limits),
    )


def run(config: PollerConfig) -> None:
    if len(config.secret) < 32:
        raise SystemExit("QWB_POLLER_SECRET must be set to this poller's 32+ character device key")
    log(f"polling Codex every {config.codex_seconds:g}s, Claude every {config.claude_seconds:g}s")
    pollers = {
        Provider.CODEX: (poll_codex, config.codex_seconds, config.codex_auth_file),
        Provider.CLAUDE: (poll_claude, config.claude_seconds, None),
    }
    limits: dict[Provider, ProviderLimits] = {}
    next_due = {provider: 0.0 for provider in pollers}
    warned_missing: set[Provider] = set()
    last_fingerprint = None
    last_sent = 0.0
    while True:
        now = time.monotonic()
        for provider, (poll, interval, credential) in pollers.items():
            if now < next_due[provider]:
                continue
            next_due[provider] = now + interval
            if not (credential or config.claude_signed_in).exists():
                if provider not in warned_missing:
                    log(f"{provider.value}: not signed in; run `quota-watch-poller login {provider.value}`")
                    warned_missing.add(provider)
                continue
            warned_missing.discard(provider)
            try:
                limits[provider] = poll(config)
            except (CodexAdapterError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                log(f"{provider.value}: poll failed: {error}")

        if limits:
            snapshot = build_snapshot(config, limits)
            fingerprint = snapshot_fingerprint(snapshot)
            if fingerprint != last_fingerprint or now - last_sent >= HEARTBEAT_SECONDS:
                try:
                    send_snapshot(config.client(), snapshot)
                    last_fingerprint, last_sent = fingerprint, now
                except Exception as error:  # noqa: BLE001 - keep polling, retry next tick
                    log(f"send failed: {error}")
        time.sleep(1)


def login(config: PollerConfig, target: str) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if target in ("all", "codex"):
        print("\n== Codex: open the link below, enter the code and approve this server session ==\n", flush=True)
        subprocess.run([config.codex_binary, "login", "--device-auth"], check=True)
    if target in ("all", "claude"):
        # A full Claude Code sign-in: `setup-token` only grants inference scope,
        # which cannot read plan limits.
        print("\n== Claude: open the link, approve, then paste the code back here ==\n", flush=True)
        subprocess.run(["claude", "auth", "login"], check=True)
        config.claude_token_file.unlink(missing_ok=True)
    status(config)


def status(config: PollerConfig) -> None:
    for name, path in (("codex", config.codex_auth_file), ("claude", config.claude_credentials_file)):
        print(f"{name}: {'signed in' if path.exists() else 'not signed in'}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="quota-watch-poller")
    sub = parser.add_subparsers(dest="command")
    login_parser = sub.add_parser("login")
    login_parser.add_argument("target", nargs="?", choices=("all", "codex", "claude"), default="all")
    sub.add_parser("status")
    sub.add_parser("run")
    args = parser.parse_args()
    config = PollerConfig.from_env()
    if args.command == "login":
        login(config, args.target)
    elif args.command == "status":
        status(config)
    else:
        run(config)


if __name__ == "__main__":
    sys.exit(main())
