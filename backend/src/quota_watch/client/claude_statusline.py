from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quota_watch.client.state import locked_json


def _first(mapping: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def extract_rate_limits(payload: dict[str, Any]) -> dict[str, Any] | None:
    rate_limits = payload.get("rate_limits") or payload.get("rateLimits")
    if not isinstance(rate_limits, dict):
        return None
    result: dict[str, Any] = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source": "claude-statusline",
    }
    mapping = {
        "five_hour": ("five_hour", "fiveHour", "primary"),
        "weekly": ("seven_day", "sevenDay", "weekly", "secondary"),
    }
    for output_name, input_names in mapping.items():
        window = next(
            (rate_limits[name] for name in input_names if isinstance(rate_limits.get(name), dict)),
            None,
        )
        if not window:
            continue
        used = _first(window, "used_percentage", "usedPercent", "utilization")
        reset = _first(window, "resets_at", "resetsAt")
        if used is None:
            continue
        used_value = float(used)
        if 0 <= used_value <= 1:
            used_value *= 100
        result[output_name] = {
            "duration_minutes": 300 if output_name == "five_hour" else 10080,
            "used_percent": round(used_value, 2),
            "resets_at": reset,
        }
    return result if "five_hour" in result or "weekly" in result else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("~/.local/state/quota-watch/claude-limits.json").expanduser(),
    )
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    limits = extract_rate_limits(payload)
    if limits:
        with locked_json(args.state_file) as state:
            state.clear()
            state.update(limits)
    if args.show:
        model = payload.get("model", {})
        model_name = model.get("display_name", "Claude") if isinstance(model, dict) else "Claude"
        five_hour = (limits or {}).get("five_hour", {}).get("used_percent")
        weekly = (limits or {}).get("weekly", {}).get("used_percent")
        parts = []
        if five_hour is not None:
            parts.append(f"5h {five_hour:.0f}%")
        if weekly is not None:
            parts.append(f"wk {weekly:.0f}%")
        print(model_name + ((" · " + " · ".join(parts)) if parts else ""))
