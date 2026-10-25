from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from quota_watch.common.models import (
    AgentActivity,
    AgentState,
    DeviceSnapshot,
    LimitWindow,
    Provider,
    ProviderLimits,
)
from quota_watch.server.aggregation import aggregate_snapshots


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def snapshot(
    device_id: str,
    *,
    codex_used: float | None = None,
    claude_used: float | None = None,
    codex_state: AgentState = AgentState.IDLE,
    claude_state: AgentState = AgentState.IDLE,
) -> DeviceSnapshot:
    limits = {}
    if codex_used is not None:
        limits[Provider.CODEX] = ProviderLimits(
            observed_at=NOW,
            five_hour=LimitWindow(duration_minutes=300, used_percent=codex_used),
            source="test",
        )
    if claude_used is not None:
        limits[Provider.CLAUDE] = ProviderLimits(
            observed_at=NOW,
            five_hour=LimitWindow(duration_minutes=300, used_percent=claude_used),
            source="test",
        )
    activity = {
        Provider.CODEX: AgentActivity(
            provider=Provider.CODEX,
            state=codex_state,
            active_sessions=1 if codex_state == AgentState.WORKING else 0,
            observed_at=NOW,
        ),
        Provider.CLAUDE: AgentActivity(
            provider=Provider.CLAUDE,
            state=claude_state,
            active_sessions=1 if claude_state == AgentState.WORKING else 0,
            observed_at=NOW,
        ),
    }
    return DeviceSnapshot(
        device_id=device_id,
        display_name=device_id,
        sent_at=NOW,
        delivery_mode="heartbeat",
        limits=limits,
        activity=activity,
    )


class AggregationTests(unittest.TestCase):
    def test_limit_source_device_supplies_limits_but_is_not_a_laptop(self) -> None:
        poller = snapshot("server-poller", codex_used=40, claude_used=70).model_copy(
            update={"activity": {}}
        )
        laptop = snapshot("macbook-pro", claude_state=AgentState.WORKING).model_copy(
            update={"limits": {}}
        )
        result = aggregate_snapshots(
            [(poller, NOW), (laptop, NOW)],
            now=NOW,
            device_stale_seconds=180,
            limit_stale_seconds=900,
            limit_source_devices=frozenset({"server-poller"}),
        )
        self.assertEqual([item["id"] for item in result["laptops"]], ["macbook-pro"])
        self.assertEqual(result["laptops_total"], 1)
        self.assertEqual(result["codex_5h_remaining_pct"], 60.0)
        self.assertEqual(result["claude_5h_remaining_pct"], 30.0)
        self.assertEqual(result["providers"]["claude"]["status"], "working")

    def test_multiple_laptops_and_flat_widget_fields(self) -> None:
        result = aggregate_snapshots(
            [
                (
                    snapshot(
                        "macbook-pro",
                        codex_used=20,
                        claude_used=40,
                        codex_state=AgentState.WORKING,
                    ),
                    NOW,
                ),
                (
                    snapshot(
                        "mac-mini",
                        codex_used=25,
                        claude_state=AgentState.WORKING,
                    ),
                    NOW - timedelta(seconds=10),
                ),
            ],
            now=NOW,
            device_stale_seconds=180,
            limit_stale_seconds=900,
        )

        self.assertEqual(len(result["laptops"]), 2)
        self.assertEqual(result["laptops_online"], 2)
        self.assertEqual(result["active_agents_total"], 2)
        self.assertEqual(result["codex_5h_remaining_pct"], 75.0)
        self.assertEqual(result["claude_5h_remaining_pct"], 60.0)
        self.assertEqual(result["widget_gauge"], 0.6)
        self.assertEqual(result["widget_gauge_provider"], "claude")
        self.assertEqual(result["widget_title"], "Cdx 75% · Cl 60%")
        self.assertEqual(result["widget_compact"], "Cdx 75% · Cl 60% · 2 active")

    def test_stale_laptop_is_offline_and_does_not_supply_limits(self) -> None:
        result = aggregate_snapshots(
            [(snapshot("old-mac", codex_used=99), NOW - timedelta(minutes=10))],
            now=NOW,
            device_stale_seconds=180,
            limit_stale_seconds=900,
        )
        self.assertFalse(result["laptops"][0]["online"])
        self.assertIsNone(result["codex_5h_remaining_pct"])
        self.assertEqual(result["widget_value"], "Unknown")

    def test_change_only_snapshot_keeps_idle_and_unexpired_limits(self) -> None:
        item = snapshot("event-mac", codex_used=25)
        item.delivery_mode = "change_only"
        result = aggregate_snapshots(
            [(item, NOW - timedelta(days=1))],
            now=NOW,
            device_stale_seconds=180,
            limit_stale_seconds=900,
            active_state_ttl_seconds=900,
        )
        self.assertIsNone(result["laptops_online"])
        self.assertEqual(result["laptops"][0]["availability"], "last_known")
        self.assertEqual(result["laptops"][0]["activity"]["codex"]["state"], "idle")
        self.assertEqual(result["codex_5h_remaining_pct"], 75.0)

    def test_change_only_working_state_expires_without_heartbeat(self) -> None:
        item = snapshot(
            "event-mac",
            codex_state=AgentState.WORKING,
        )
        item.delivery_mode = "change_only"
        item.activity[Provider.CODEX].observed_at = NOW - timedelta(minutes=20)
        result = aggregate_snapshots(
            [(item, NOW - timedelta(minutes=20))],
            now=NOW,
            device_stale_seconds=180,
            limit_stale_seconds=900,
            active_state_ttl_seconds=900,
        )
        self.assertEqual(result["codex_working_agents"], 0)
        self.assertEqual(result["codex_status"], "unknown")
        self.assertEqual(result["laptops"][0]["activity"]["codex"]["state"], "unknown")

    def test_change_only_working_state_persists_when_ttl_is_disabled(self) -> None:
        item = snapshot("event-mac", codex_state=AgentState.WORKING)
        item.delivery_mode = "change_only"
        item.activity[Provider.CODEX].observed_at = NOW - timedelta(hours=6)
        result = aggregate_snapshots(
            [(item, NOW - timedelta(hours=6))],
            now=NOW,
            device_stale_seconds=180,
            limit_stale_seconds=900,
            active_state_ttl_seconds=0,
        )
        self.assertEqual(result["codex_working_agents"], 1)
        self.assertEqual(result["codex_status"], "working")


if __name__ == "__main__":
    unittest.main()
