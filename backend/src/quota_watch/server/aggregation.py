from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from quota_watch.common.models import AgentState, DeviceSnapshot, Provider


STATE_LABELS = {
    AgentState.WORKING: "working",
    AgentState.WAITING_APPROVAL: "approval",
    AgentState.WAITING_INPUT: "input",
    AgentState.IDLE: "idle",
    AgentState.ERROR: "error",
    AgentState.UNKNOWN: "unknown",
}


def _seconds_old(now: datetime, value: datetime) -> float:
    return max(0.0, (now - value).total_seconds())


def _choose_limit(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    newest_time = max(item["observed_at"] for item in candidates)
    near_newest = [
        item
        for item in candidates
        if abs((newest_time - item["observed_at"]).total_seconds()) <= 30
    ]
    return max(near_newest, key=lambda item: item["used_percent"])


def aggregate_snapshots(
    snapshots: list[tuple[DeviceSnapshot, datetime]],
    *,
    now: datetime,
    device_stale_seconds: int,
    limit_stale_seconds: int,
    active_state_ttl_seconds: int = 0,
    limit_source_devices: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """limit_source_devices supply limits only (e.g. the server poller): they are
    not computers, so they stay out of the laptops list and counts."""
    laptops: list[dict[str, Any]] = []
    limit_candidates: dict[Provider, dict[str, list[dict[str, Any]]]] = {
        provider: defaultdict(list) for provider in Provider
    }
    state_counts: dict[Provider, dict[AgentState, int]] = {
        provider: defaultdict(int) for provider in Provider
    }

    for snapshot, received_at in snapshots:
        change_only = snapshot.delivery_mode == "change_only"
        online: bool | None = (
            None if change_only else _seconds_old(now, received_at) <= device_stale_seconds
        )
        laptop_activity: dict[str, Any] = {}
        laptop_limits: dict[str, Any] = {}

        for provider in Provider:
            activity = snapshot.activity.get(provider)
            state = AgentState.UNKNOWN
            active_sessions = 0
            if activity and change_only:
                activity_age = _seconds_old(now, activity.observed_at)
                activity_fresh = (
                    active_state_ttl_seconds == 0
                    or activity.state in {AgentState.IDLE, AgentState.ERROR}
                    or activity_age <= active_state_ttl_seconds
                )
            else:
                activity_fresh = bool(
                    activity
                    and online
                    and _seconds_old(now, activity.observed_at) <= device_stale_seconds
                )
            if activity and activity_fresh:
                state = activity.state
                active_sessions = activity.active_sessions
                explicit_counts = {
                    AgentState.WORKING: activity.working_sessions,
                    AgentState.WAITING_APPROVAL: activity.waiting_approval_sessions,
                    AgentState.WAITING_INPUT: activity.waiting_input_sessions,
                    AgentState.ERROR: activity.error_sessions,
                }
                if sum(explicit_counts.values()):
                    for counted_state, count in explicit_counts.items():
                        state_counts[provider][counted_state] += count
                else:
                    # Backward-compatible fallback for older local agents.
                    state_counts[provider][state] += max(1, active_sessions)
            laptop_activity[provider.value] = {
                "state": state.value if online is not False else "offline",
                "active_sessions": active_sessions if online is not False else 0,
                "working_sessions": activity.working_sessions if activity and activity_fresh else 0,
                "waiting_approval_sessions": (
                    activity.waiting_approval_sessions if activity and activity_fresh else 0
                ),
                "waiting_input_sessions": (
                    activity.waiting_input_sessions if activity and activity_fresh else 0
                ),
                "error_sessions": activity.error_sessions if activity and activity_fresh else 0,
                "observed_at": activity.observed_at.isoformat() if activity else None,
            }

            limits = snapshot.limits.get(provider)
            if limits:
                laptop_limits[provider.value] = limits.model_dump(mode="json")
                provider_fresh = change_only or (
                    bool(online)
                    and _seconds_old(now, limits.observed_at) <= limit_stale_seconds
                )
                if provider_fresh:
                    for name in ("five_hour", "weekly"):
                        window = getattr(limits, name)
                        window_fresh = bool(
                            window
                            and (
                                not change_only
                                or window.resets_at is None
                                or now < window.resets_at
                            )
                        )
                        if window and window_fresh:
                            limit_candidates[provider][name].append(
                                {
                                    "account_id": limits.account_id,
                                    "device_id": snapshot.device_id,
                                    "observed_at": limits.observed_at,
                                    "duration_minutes": window.duration_minutes,
                                    "used_percent": float(window.used_percent),
                                    "remaining_percent": window.remaining_percent,
                                    "resets_at": window.resets_at,
                                    "source": limits.source,
                                }
                            )

        if snapshot.device_id in limit_source_devices:
            continue
        laptops.append(
            {
                "id": snapshot.device_id,
                "name": snapshot.display_name,
                "online": online,
                "availability": "last_known" if change_only else ("online" if online else "offline"),
                "delivery_mode": snapshot.delivery_mode,
                "last_seen_at": received_at.isoformat(),
                "age_seconds": int(_seconds_old(now, received_at)),
                "agent_version": snapshot.agent_version,
                "activity": laptop_activity,
                "limits": laptop_limits,
            }
        )

    providers: dict[str, Any] = {}
    flat: dict[str, Any] = {}
    active_total = 0
    waiting_total = 0
    error_total = 0
    idle_observations = 0

    for provider in Provider:
        five_hour = _choose_limit(limit_candidates[provider]["five_hour"])
        weekly = _choose_limit(limit_candidates[provider]["weekly"])
        working = state_counts[provider][AgentState.WORKING]
        waiting = (
            state_counts[provider][AgentState.WAITING_APPROVAL]
            + state_counts[provider][AgentState.WAITING_INPUT]
        )
        errors = state_counts[provider][AgentState.ERROR]
        idle = state_counts[provider][AgentState.IDLE]
        active_total += working
        waiting_total += waiting
        error_total += errors
        idle_observations += idle

        if errors:
            status = "error"
        elif waiting:
            status = "waiting"
        elif working:
            status = "working"
        elif idle:
            status = "idle"
        else:
            status = "unknown"

        providers[provider.value] = {
            "status": status,
            "working_agents": working,
            "waiting_agents": waiting,
            "errors": errors,
            "five_hour": _serialize_limit(five_hour),
            "weekly": _serialize_limit(weekly),
        }
        prefix = provider.value
        flat[f"{prefix}_status"] = status
        flat[f"{prefix}_working_agents"] = working
        flat[f"{prefix}_waiting_agents"] = waiting
        flat[f"{prefix}_5h_available"] = five_hour is not None
        flat[f"{prefix}_5h_used_pct"] = five_hour["used_percent"] if five_hour else None
        flat[f"{prefix}_5h_remaining_pct"] = (
            five_hour["remaining_percent"] if five_hour else None
        )
        flat[f"{prefix}_5h_remaining_ratio"] = (
            round(five_hour["remaining_percent"] / 100, 3) if five_hour else None
        )
        flat[f"{prefix}_5h_resets_at"] = (
            five_hour["resets_at"].isoformat() if five_hour and five_hour["resets_at"] else None
        )

    online_count = sum(1 for laptop in laptops if laptop["online"] is True)
    availability_unknown = sum(1 for laptop in laptops if laptop["online"] is None)
    availability_known = len(laptops) - availability_unknown
    total_count = len(laptops)
    if availability_unknown:
        status_text = f"{active_total} active · {total_count} tracked"
    else:
        status_text = f"{active_total} active · {online_count}/{total_count} online"
    codex_remaining = flat.get("codex_5h_remaining_pct")
    claude_remaining = flat.get("claude_5h_remaining_pct")
    available_quotas = [
        ("Codex", codex_remaining),
        ("Claude", claude_remaining),
    ]
    available_quotas = [item for item in available_quotas if item[1] is not None]
    lowest_quota = min(available_quotas, key=lambda item: item[1]) if available_quotas else None

    quota_parts = []
    if codex_remaining is not None:
        quota_parts.append(f"Cdx {codex_remaining:.0f}%")
    if claude_remaining is not None:
        quota_parts.append(f"Cl {claude_remaining:.0f}%")
    widget_title = " · ".join(quota_parts) if quota_parts else "Limits unavailable"
    if error_total:
        widget_value = f"{error_total} error"
    elif waiting_total:
        widget_value = f"{waiting_total} waiting"
    elif active_total:
        widget_value = f"{active_total} active"
    elif idle_observations:
        widget_value = "Idle"
    else:
        widget_value = "Unknown"
    widget_subtitle = (
        f"{total_count} computers · last known"
        if availability_unknown
        else f"{online_count}/{total_count} computers online"
    )
    widget_compact = f"{widget_title} · {widget_value}"

    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "status_text": status_text,
        "active_agents_total": active_total,
        "waiting_agents_total": waiting_total,
        "laptops_online": online_count if availability_known else None,
        "laptops_availability_unknown": availability_unknown,
        "laptops_total": total_count,
        # Flat, short fields are deliberate: Complicator can map each visual slot
        # directly without having to transform arrays on the watch.
        "widget_title": widget_title,
        "widget_value": widget_value,
        "widget_subtitle": widget_subtitle,
        "widget_compact": widget_compact,
        "widget_gauge": round(lowest_quota[1] / 100, 3) if lowest_quota else None,
        "widget_gauge_pct": lowest_quota[1] if lowest_quota else None,
        "widget_gauge_provider": lowest_quota[0].lower() if lowest_quota else None,
        **flat,
        "providers": providers,
        "laptops": laptops,
    }


def _serialize_limit(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        **value,
        "observed_at": value["observed_at"].isoformat(),
        "resets_at": value["resets_at"].isoformat() if value["resets_at"] else None,
    }
