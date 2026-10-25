from __future__ import annotations

import unittest
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from quota_watch.client.agent import (
    _codex_activity_token,
    _read_activity,
    snapshot_fingerprint,
    snapshot_needs_upload,
    should_refresh_codex_limits,
)
from quota_watch.client.claude_statusline import extract_rate_limits
from quota_watch.client.codex_adapter import parse_codex_limits
from quota_watch.common.models import (
    AgentActivity,
    AgentState,
    DeviceSnapshot,
    LimitWindow,
    Provider,
    ProviderLimits,
)


class AdapterTests(unittest.TestCase):
    def test_codex_app_server_shape(self) -> None:
        result = parse_codex_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 12.5,
                        "windowDurationMins": 300,
                        "resetsAt": 1_800_000_000,
                    },
                    "secondary": {
                        "usedPercent": 34,
                        "windowDurationMins": 10080,
                        "resetsAt": 1_800_010_000,
                    },
                }
            },
            account_id="personal",
        )
        self.assertEqual(result.five_hour.used_percent, 12.5)
        self.assertEqual(result.weekly.duration_minutes, 10080)
        self.assertEqual(result.source, "codex-app-server")

    def test_codex_does_not_mislabel_a_non_five_hour_primary_window(self) -> None:
        result = parse_codex_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 12.5,
                        "windowDurationMins": 15,
                        "resetsAt": 1_800_000_000,
                    }
                }
            },
            account_id="personal",
        )
        self.assertIsNone(result.five_hour)

    def test_claude_status_line_shape(self) -> None:
        result = extract_rate_limits(
            {
                "rate_limits": {
                    "five_hour": {"used_percentage": 23.5, "resets_at": 1_800_000_000},
                    "seven_day": {"used_percentage": 41.2, "resets_at": 1_800_010_000},
                }
            }
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["five_hour"]["used_percent"], 23.5)
        self.assertEqual(result["weekly"]["duration_minutes"], 10080)

    def test_claude_absent_rate_limits_is_safe(self) -> None:
        self.assertIsNone(extract_rate_limits({"model": {"display_name": "Claude"}}))

    def test_mixed_parallel_sessions_keep_separate_counts(self) -> None:
        now = datetime.now(timezone.utc)
        payload = {
            "sessions": {
                "one": {
                    "provider": "codex",
                    "state": "working",
                    "observed_at": now.isoformat(),
                },
                "two": {
                    "provider": "codex",
                    "state": "waiting_approval",
                    "observed_at": now.isoformat(),
                },
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            activity = _read_activity(path, now=now)[Provider.CODEX]
        self.assertEqual(activity.state, AgentState.WAITING_APPROVAL)
        self.assertEqual(activity.active_sessions, 2)
        self.assertEqual(activity.working_sessions, 1)
        self.assertEqual(activity.waiting_approval_sessions, 1)

    def test_snapshot_fingerprint_ignores_only_volatile_timestamps(self) -> None:
        first = DeviceSnapshot(
            device_id="local-mac",
            display_name="Local Mac",
            limits={
                Provider.CODEX: ProviderLimits(
                    observed_at=datetime(2026, 9, 20, 10, tzinfo=timezone.utc),
                    five_hour=LimitWindow(duration_minutes=300, used_percent=20),
                )
            },
            activity={
                Provider.CODEX: AgentActivity(
                    provider=Provider.CODEX,
                    state=AgentState.WORKING,
                    working_sessions=1,
                    active_sessions=1,
                    observed_at=datetime(2026, 9, 20, 10, tzinfo=timezone.utc),
                )
            },
        )
        second = first.model_copy(deep=True)
        second.sent_at = datetime(2026, 9, 20, 11, tzinfo=timezone.utc)
        second.limits[Provider.CODEX].observed_at = second.sent_at
        second.activity[Provider.CODEX].observed_at = second.sent_at
        self.assertEqual(snapshot_fingerprint(first), snapshot_fingerprint(second))

        second.limits[Provider.CODEX].five_hour.used_percent = 21
        self.assertNotEqual(snapshot_fingerprint(first), snapshot_fingerprint(second))

    def test_unchanged_or_empty_snapshot_never_needs_network(self) -> None:
        empty = DeviceSnapshot(device_id="local-mac", display_name="Local Mac")
        self.assertFalse(snapshot_needs_upload(empty, None))

        populated = DeviceSnapshot(
            device_id="local-mac",
            display_name="Local Mac",
            activity={
                Provider.CLAUDE: AgentActivity(
                    provider=Provider.CLAUDE,
                    state=AgentState.IDLE,
                )
            },
        )
        fingerprint = snapshot_fingerprint(populated)
        self.assertFalse(snapshot_needs_upload(populated, fingerprint))
        self.assertTrue(snapshot_needs_upload(populated, fingerprint, force=True))

    def test_codex_activity_token_changes_only_for_semantic_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.json"
            record = {
                "provider": "codex",
                "state": "working",
                "observed_at": "2026-09-20T10:00:00+00:00",
            }
            path.write_text(json.dumps({"sessions": {"codex:one": record}}), encoding="utf-8")
            first = _codex_activity_token(path)

            record["observed_at"] = "2026-09-20T10:01:00+00:00"
            path.write_text(json.dumps({"sessions": {"codex:one": record}}), encoding="utf-8")
            self.assertEqual(first, _codex_activity_token(path))

            record["state"] = "idle"
            path.write_text(json.dumps({"sessions": {"codex:one": record}}), encoding="utf-8")
            self.assertNotEqual(first, _codex_activity_token(path))

    def test_codex_limit_refresh_is_deferred_until_work_finishes(self) -> None:
        working = AgentActivity(provider=Provider.CODEX, state=AgentState.WORKING)
        idle = AgentActivity(provider=Provider.CODEX, state=AgentState.IDLE)
        self.assertFalse(
            should_refresh_codex_limits(
                activity_changed=True,
                activity=working,
                cache_missing=False,
                explicitly_requested=False,
            )
        )
        self.assertTrue(
            should_refresh_codex_limits(
                activity_changed=True,
                activity=idle,
                cache_missing=False,
                explicitly_requested=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
