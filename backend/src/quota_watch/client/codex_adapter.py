from __future__ import annotations

import json
import selectors
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from quota_watch.common.models import LimitWindow, ProviderLimits


class CodexAdapterError(RuntimeError):
    pass


def read_codex_limits(
    binary: str = "codex", *, account_id: str = "default", timeout: float = 10
) -> ProviderLimits:
    process = subprocess.Popen(
        [binary, "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    if process.stdin is None or process.stdout is None:
        raise CodexAdapterError("failed to open Codex app-server pipes")
    requests = [
        {
            "method": "initialize",
            "id": 1,
            "params": {
                "clientInfo": {
                    "name": "quota_watch_bridge",
                    "title": "Quota Watch Bridge",
                    "version": "0.1.0",
                }
            },
        },
        {"method": "initialized", "params": {}},
        {"method": "account/rateLimits/read", "id": 2, "params": {}},
    ]
    try:
        for request in requests:
            process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        process.stdin.flush()

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            events = selector.select(timeout=max(0.0, deadline - time.monotonic()))
            if not events:
                break
            line = process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == 2:
                if "error" in message:
                    raise CodexAdapterError(str(message["error"]))
                return parse_codex_limits(message["result"], account_id=account_id)
        raise CodexAdapterError("Codex app-server timed out")
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def parse_codex_limits(result: dict[str, Any], *, account_id: str) -> ProviderLimits:
    limits = result.get("rateLimits")
    if not isinstance(limits, dict) or not limits:
        by_id = result.get("rateLimitsByLimitId") or {}
        limits = by_id.get("codex") if isinstance(by_id, dict) else None
    limits = limits if isinstance(limits, dict) else {}
    windows = [
        window
        for window in (_parse_window(limits.get("primary")), _parse_window(limits.get("secondary")))
        if window is not None
    ]
    return ProviderLimits(
        account_id=account_id,
        observed_at=datetime.now(timezone.utc),
        five_hour=next((window for window in windows if window.duration_minutes == 300), None),
        weekly=next((window for window in windows if window.duration_minutes == 10080), None),
        source="codex-app-server",
    )


def _parse_window(value: dict[str, Any] | None) -> LimitWindow | None:
    if not value:
        return None
    resets_at = value.get("resetsAt")
    return LimitWindow(
        duration_minutes=int(value["windowDurationMins"]),
        used_percent=float(value["usedPercent"]),
        resets_at=(
            datetime.fromtimestamp(float(resets_at), tz=timezone.utc)
            if resets_at is not None
            else None
        ),
    )
