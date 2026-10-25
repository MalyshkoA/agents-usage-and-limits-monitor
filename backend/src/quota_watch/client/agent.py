from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quota_watch import __version__
from quota_watch.client.codex_adapter import CodexAdapterError, read_codex_limits
from quota_watch.client.config import ClientConfig
from quota_watch.client.state import locked_json, read_json
from quota_watch.common.models import (
    AgentActivity,
    AgentState,
    DeviceSnapshot,
    LimitWindow,
    Provider,
    ProviderLimits,
)
from quota_watch.common.signing import sign_request


def build_snapshot(
    config: ClientConfig, *, refresh_codex: bool = False
) -> DeviceSnapshot:
    now = datetime.now(timezone.utc)
    limits: dict[Provider, ProviderLimits] = {}
    if config.codex_enabled:
        codex_path = config.state_dir / "codex-limits.json"
        if refresh_codex:
            try:
                current_limits = read_codex_limits(
                    config.codex_binary, account_id=config.account_id
                )
                _write_limits(codex_path, current_limits)
            except (CodexAdapterError, FileNotFoundError, OSError):
                pass
        codex_limits = _read_cached_limits(
            codex_path, account_id=config.account_id, default_source="codex-app-server"
        )
        if codex_limits:
            limits[Provider.CODEX] = codex_limits
    if config.claude_enabled:
        claude_limits = _read_cached_limits(
            config.state_dir / "claude-limits.json",
            account_id=config.account_id,
            default_source="claude-statusline",
        )
        if claude_limits:
            limits[Provider.CLAUDE] = claude_limits

    activity = _read_activity(
        config.state_dir / "activity.json",
        now=now,
        active_state_ttl_seconds=config.active_state_ttl_seconds,
    )
    return DeviceSnapshot(
        device_id=config.device_id,
        display_name=config.display_name,
        sent_at=now,
        agent_version=__version__,
        delivery_mode="change_only",
        limits=limits,
        activity=activity,
    )


def _read_cached_limits(
    path: Path, *, account_id: str, default_source: str
) -> ProviderLimits | None:
    data = read_json(path)
    if not data:
        return None
    try:
        return ProviderLimits(
            account_id=account_id,
            observed_at=data["observed_at"],
            source=str(data.get("source", default_source)),
            five_hour=LimitWindow.model_validate(data["five_hour"])
            if data.get("five_hour")
            else None,
            weekly=LimitWindow.model_validate(data["weekly"])
            if data.get("weekly")
            else None,
        )
    except (KeyError, ValueError):
        return None


def _write_limits(path: Path, limits: ProviderLimits) -> None:
    with locked_json(path) as state:
        state.clear()
        state.update(limits.model_dump(mode="json"))


def _read_activity(
    path: Path, *, now: datetime, active_state_ttl_seconds: int = 0
) -> dict[Provider, AgentActivity]:
    data = read_json(path)
    sessions = data.get("sessions", {})
    grouped: dict[Provider, list[dict[str, Any]]] = {provider: [] for provider in Provider}
    for record in sessions.values():
        try:
            provider = Provider(record["provider"])
            observed_at = datetime.fromisoformat(record["observed_at"])
            AgentState(record["state"])
            if observed_at.tzinfo is None:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        state = AgentState(record["state"])
        age_seconds = (now - observed_at).total_seconds()
        if (
            active_state_ttl_seconds == 0
            or state in {AgentState.IDLE, AgentState.ERROR}
            or age_seconds <= active_state_ttl_seconds
        ):
            grouped[provider].append(record)

    result: dict[Provider, AgentActivity] = {}
    priority = {
        AgentState.ERROR: 5,
        AgentState.WAITING_APPROVAL: 4,
        AgentState.WAITING_INPUT: 3,
        AgentState.WORKING: 2,
        AgentState.IDLE: 1,
        AgentState.UNKNOWN: 0,
    }
    for provider, records in grouped.items():
        if not records:
            continue
        selected = max(records, key=lambda item: priority[AgentState(item["state"])])
        active_sessions = sum(
            1
            for item in records
            if AgentState(item["state"])
            in {AgentState.WORKING, AgentState.WAITING_APPROVAL, AgentState.WAITING_INPUT}
        )
        counts = {
            state: sum(1 for item in records if AgentState(item["state"]) == state)
            for state in AgentState
        }
        result[provider] = AgentActivity(
            provider=provider,
            state=AgentState(selected["state"]),
            session_id_hash=selected.get("session_id_hash"),
            active_sessions=active_sessions,
            working_sessions=counts[AgentState.WORKING],
            waiting_approval_sessions=counts[AgentState.WAITING_APPROVAL],
            waiting_input_sessions=counts[AgentState.WAITING_INPUT],
            error_sessions=counts[AgentState.ERROR],
            observed_at=selected["observed_at"],
            error_code=selected.get("error_code"),
        )
    return result


def snapshot_fingerprint(snapshot: DeviceSnapshot) -> str:
    """Hash only information that is meaningful to the remote widget."""
    canonical = snapshot.model_dump(mode="json")
    canonical.pop("sent_at", None)
    for limits in canonical.get("limits", {}).values():
        limits.pop("observed_at", None)
    for activity in canonical.get("activity", {}).values():
        activity.pop("observed_at", None)
        activity.pop("session_id_hash", None)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def snapshot_needs_upload(
    snapshot: DeviceSnapshot, last_sent_fingerprint: str | None, *, force: bool = False
) -> bool:
    if force:
        return True
    if not snapshot.limits and not snapshot.activity:
        return False
    return snapshot_fingerprint(snapshot) != last_sent_fingerprint


def _codex_semantic_activity(path: Path) -> AgentActivity | None:
    return _read_activity(
        path,
        now=datetime.now(timezone.utc),
        # The token represents semantic hook state, not time-based expiry.
        active_state_ttl_seconds=60 * 60 * 24 * 365 * 100,
    ).get(Provider.CODEX)


def _codex_activity_token(path: Path) -> str:
    activity = _codex_semantic_activity(path)
    canonical = activity.model_dump(mode="json") if activity else {}
    canonical.pop("observed_at", None)
    canonical.pop("session_id_hash", None)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def should_refresh_codex_limits(
    *,
    activity_changed: bool,
    activity: AgentActivity | None,
    cache_missing: bool,
    explicitly_requested: bool,
) -> bool:
    if explicitly_requested:
        return True
    if not activity_changed:
        return False
    if cache_missing:
        return True
    return bool(activity and activity.state in {AgentState.IDLE, AgentState.ERROR})


def should_poll_codex_limits(
    *,
    activity: AgentActivity | None,
    cache_missing: bool,
    activity_changed: bool,
    explicitly_requested: bool,
    now_monotonic: float,
    last_poll_monotonic: float,
    poll_seconds: float,
    poll_when_idle: bool = False,
) -> bool:
    """Return true only when a local Codex query is useful.

    Active tasks are sampled on the configured cadence. Inactive tasks trigger
    one final read on a semantic state transition so the completed turn's
    usage is not missed. This decision never implies a network upload: the
    snapshot fingerprint still gates the callback separately.
    With poll_when_idle every state is sampled on the cadence, so window resets
    reach the server while Codex is idle too.
    """
    if explicitly_requested:
        return True
    if poll_when_idle:
        return now_monotonic - last_poll_monotonic >= poll_seconds
    if cache_missing and activity_changed:
        return True
    if activity_changed and activity and activity.state in {
        AgentState.IDLE,
        AgentState.ERROR,
    }:
        return True
    active = bool(
        activity
        and activity.state
        in {
            AgentState.WORKING,
            AgentState.WAITING_APPROVAL,
            AgentState.WAITING_INPUT,
        }
    )
    return active and now_monotonic - last_poll_monotonic >= poll_seconds


def _load_last_sent_fingerprint(path: Path) -> str | None:
    value = read_json(path).get("last_sent_fingerprint")
    return str(value) if value else None


def _save_last_sent_fingerprint(path: Path, fingerprint: str) -> None:
    with locked_json(path) as state:
        state["last_sent_fingerprint"] = fingerprint
        state["sent_at"] = datetime.now(timezone.utc).isoformat()


def _save_codex_activity_token(path: Path, token: str) -> None:
    with locked_json(path) as state:
        state["last_codex_activity_token"] = token


def _ssl_context() -> ssl.SSLContext:
    # python.org builds on macOS ship without system roots; hooks run without the
    # SSL_CERT_FILE the launchd agent used to set, so fall back to certifi.
    if not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi
        except ImportError:
            pass
        else:
            return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def send_snapshot(config: ClientConfig, snapshot: DeviceSnapshot, *, timeout: float = 15) -> None:
    path = f"/v1/ingest/{config.device_id}"
    url = config.server_url + path
    body = snapshot.model_dump_json().encode("utf-8")
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    signature = sign_request(
        secret=config.device_secret,
        method="POST",
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-QWB-Timestamp": timestamp,
            "X-QWB-Nonce": nonce,
            "X-QWB-Signature": signature,
            "User-Agent": f"quota-watch-agent/{__version__}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        if response.status != 204:
            raise RuntimeError(f"server returned HTTP {response.status}")


def push_if_changed(config: ClientConfig, *, timeout: float = 15) -> bool:
    """Build the current snapshot and send it only if its meaning changed.

    Used by IDE hooks to deliver activity without a background agent. The
    fingerprint is stored only after a successful upload, so a failed send is
    retried by the next hook event. Returns True when something was sent.
    """
    sync_state_path = config.state_dir / "sync-state.json"
    snapshot = build_snapshot(config)
    fingerprint = snapshot_fingerprint(snapshot)
    with locked_json(sync_state_path) as state:
        if not snapshot_needs_upload(snapshot, state.get("last_sent_fingerprint")):
            return False
        send_snapshot(config, snapshot, timeout=timeout)
        state["last_sent_fingerprint"] = fingerprint
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Send local Claude/Codex state to Quota Watch")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_snapshot")
    parser.add_argument(
        "--refresh-codex",
        action="store_true",
        help="explicitly refresh Codex limits once before comparing the snapshot",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="send even when the meaningful snapshot has not changed",
    )
    args = parser.parse_args()
    config = ClientConfig.load(args.config)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    sync_state_path = config.state_dir / "sync-state.json"
    activity_path = config.state_dir / "activity.json"
    sync_state = read_json(sync_state_path)
    last_sent_fingerprint = _load_last_sent_fingerprint(sync_state_path)
    last_codex_activity_token = str(
        sync_state.get("last_codex_activity_token")
        or hashlib.sha256(b"{}").hexdigest()
    )
    retry_delay_seconds = 0.0
    next_retry_at = 0.0
    last_codex_poll_at = 0.0
    first_iteration = True

    while True:
        codex_activity_token = _codex_activity_token(activity_path)
        codex_activity_changed = codex_activity_token != last_codex_activity_token
        last_codex_activity_token = codex_activity_token
        codex_activity = _codex_semantic_activity(activity_path)
        codex_cache_missing = not bool(read_json(config.state_dir / "codex-limits.json"))
        loop_now = time.monotonic()
        refresh_codex = should_poll_codex_limits(
            activity_changed=codex_activity_changed,
            activity=codex_activity,
            cache_missing=codex_cache_missing,
            explicitly_requested=args.refresh_codex and first_iteration,
            now_monotonic=loop_now,
            last_poll_monotonic=last_codex_poll_at,
            poll_seconds=config.limit_poll_seconds,
            poll_when_idle=config.codex_poll_when_idle,
        )
        if refresh_codex:
            # Count attempts as polls as well as successful reads, otherwise a
            # broken local app-server would be spawned on every scan tick.
            last_codex_poll_at = loop_now
        snapshot = build_snapshot(config, refresh_codex=refresh_codex)
        if codex_activity_changed:
            _save_codex_activity_token(sync_state_path, codex_activity_token)
        fingerprint = snapshot_fingerprint(snapshot)
        if args.print_snapshot:
            print(snapshot.model_dump_json(indent=2))
        should_send = snapshot_needs_upload(
            snapshot,
            last_sent_fingerprint,
            force=args.force and first_iteration,
        )
        if should_send and time.monotonic() >= next_retry_at:
            try:
                send_snapshot(config, snapshot)
                _save_last_sent_fingerprint(sync_state_path, fingerprint)
                last_sent_fingerprint = fingerprint
                retry_delay_seconds = 0.0
                next_retry_at = 0.0
            except (urllib.error.URLError, TimeoutError, RuntimeError, socket.timeout) as exc:
                retry_delay_seconds = min(
                    300.0, 15.0 if retry_delay_seconds == 0 else retry_delay_seconds * 2
                )
                next_retry_at = time.monotonic() + retry_delay_seconds
                print(
                    f"quota-watch-agent: {exc}; retry in {retry_delay_seconds:.0f}s",
                    flush=True,
                )
                if args.once:
                    raise SystemExit(1) from exc
        if args.once:
            return
        first_iteration = False
        time.sleep(config.check_seconds)
