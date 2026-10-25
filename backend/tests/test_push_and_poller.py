from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from quota_watch.client.agent import push_if_changed
from quota_watch.client.config import ClientConfig
from quota_watch.common.models import LimitWindow, Provider, ProviderLimits
from quota_watch.poller.main import PollerConfig, build_snapshot


class HookPushTests(unittest.TestCase):
    def _config(self, state_dir: Path) -> ClientConfig:
        return ClientConfig(
            server_url="http://127.0.0.1:8787",
            device_id="local-mac",
            display_name="Local Mac",
            device_secret="d" * 64,
            state_dir=state_dir,
            codex_enabled=False,
            claude_enabled=False,
        )

    def _write_activity(self, state_dir: Path, state: str) -> None:
        record = {
            "provider": "claude",
            "session_id_hash": "abc",
            "state": state,
            "event": "Stop",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "error_code": None,
        }
        (state_dir / "activity.json").write_text(json.dumps({"sessions": {"claude:abc": record}}))

    def test_pushes_activity_only_when_it_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            config = self._config(state_dir)
            self._write_activity(state_dir, "working")
            with patch("quota_watch.client.agent.send_snapshot") as send:
                self.assertTrue(push_if_changed(config))
                self.assertFalse(push_if_changed(config))
                self._write_activity(state_dir, "idle")
                self.assertTrue(push_if_changed(config))
            self.assertEqual(send.call_count, 2)
            sent = send.call_args.args[1]
            self.assertEqual(sent.limits, {})
            self.assertEqual(sent.activity[Provider.CLAUDE].state.value, "idle")

    def test_failed_push_is_retried_by_next_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            config = self._config(state_dir)
            self._write_activity(state_dir, "working")
            with patch("quota_watch.client.agent.send_snapshot", side_effect=OSError("offline")):
                with self.assertRaises(OSError):
                    push_if_changed(config)
            with patch("quota_watch.client.agent.send_snapshot") as send:
                self.assertTrue(push_if_changed(config))
            send.assert_called_once()


class PollerSnapshotTests(unittest.TestCase):
    def test_snapshot_carries_limits_only(self) -> None:
        config = PollerConfig(
            server_url="http://quota-watch:8787",
            device_id="server-poller",
            secret="s" * 64,
            account_id="personal",
            data_dir=Path("/tmp"),
            codex_binary="codex",
            codex_seconds=15,
            claude_collector=Path("/opt/claude_usage/collect.mjs"),
            claude_seconds=15,
        )
        limits = {
            Provider.CODEX: ProviderLimits(
                account_id="personal",
                five_hour=LimitWindow(duration_minutes=300, used_percent=12),
                source="codex-app-server",
            )
        }
        snapshot = build_snapshot(config, limits)
        self.assertEqual(snapshot.device_id, "server-poller")
        self.assertEqual(snapshot.activity, {})
        self.assertEqual(snapshot.limits[Provider.CODEX].five_hour.used_percent, 12)
        self.assertEqual(config.client().device_id, "server-poller")


if __name__ == "__main__":
    unittest.main()
