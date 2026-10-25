from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quota_watch.client.state import locked_json


STATE_BY_EVENT = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "PostToolUseFailure": "working",
    "PermissionRequest": "waiting_approval",
    "Notification": "waiting_input",
    "Stop": "idle",
    "StopFailure": "error",
    "Interrupt": "idle",
    "SessionEnd": "idle",
}


def event_to_record(provider: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    event_name = str(
        payload.get("hook_event_name")
        or payload.get("event_name")
        or payload.get("event")
        or "Unknown"
    )
    raw_session_id = str(
        payload.get("session_id")
        or payload.get("thread_id")
        or payload.get("conversation_id")
        or "default"
    )
    session_hash = hashlib.sha256(raw_session_id.encode("utf-8")).hexdigest()[:16]
    state = STATE_BY_EVENT.get(event_name, "working")
    notification_type = str(payload.get("notification_type") or payload.get("type") or "")
    if event_name == "Notification" and "permission" in notification_type.lower():
        state = "waiting_approval"
    error_code = None
    if event_name == "StopFailure":
        error_code = str(payload.get("error") or payload.get("error_type") or "unknown")[:64]
    return f"{provider}:{session_hash}", {
        "provider": provider,
        "session_id_hash": session_hash,
        "state": state,
        "event": event_name,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "error_code": error_code,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("claude", "codex"), required=True)
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("~/.local/state/quota-watch/activity.json").expanduser(),
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="send the snapshot to the server right away (no background agent needed)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("~/.config/quota-watch/client.toml").expanduser(),
    )
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    key, record = event_to_record(args.provider, payload)
    with locked_json(args.state_file) as state:
        sessions = state.setdefault("sessions", {})
        sessions[key] = record
    if args.push:
        _push(args.config)


def _push(config_path: Path) -> None:
    # Imported lazily so a plain state-writing hook stays as fast as before.
    from quota_watch.client.agent import push_if_changed
    from quota_watch.client.config import ClientConfig

    try:
        # Hooks have a 3 s budget; never block or fail the IDE on network trouble.
        push_if_changed(ClientConfig.load(config_path), timeout=2.5)
    except Exception as error:  # noqa: BLE001 - the next hook event retries
        print(f"quota-watch-hook: push failed: {error}", file=sys.stderr)
