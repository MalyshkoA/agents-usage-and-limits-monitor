from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from quota_watch.client.agent import (
    build_snapshot,
    main,
    should_poll_codex_limits,
    snapshot_fingerprint,
)
from quota_watch.client.config import ClientConfig
from quota_watch.common.models import AgentActivity, AgentState, Provider


class ChangeOnlyAgentTests(unittest.TestCase):
    def _config(self, state_dir: Path) -> ClientConfig:
        return ClientConfig(
            server_url="http://127.0.0.1:8787",
            device_id="local-mac",
            display_name="Local Mac",
            device_secret="d" * 64,
            state_dir=state_dir,
            codex_enabled=False,
            claude_enabled=True,
        )

    def _write_activity(self, path: Path, state: str) -> None:
        payload = {
            "sessions": {
                "claude:one": {
                    "provider": "claude",
                    "state": state,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_empty_local_state_does_not_call_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self._config(Path(directory))
            with (
                patch("quota_watch.client.agent.ClientConfig.load", return_value=config),
                patch("quota_watch.client.agent.send_snapshot") as send,
                patch.object(sys, "argv", ["quota-watch-agent", "--config", "unused", "--once"]),
            ):
                main()
            send.assert_not_called()

    def test_unchanged_local_state_does_not_call_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            config = self._config(state_dir)
            self._write_activity(state_dir / "activity.json", "idle")
            fingerprint = snapshot_fingerprint(build_snapshot(config))
            (state_dir / "sync-state.json").write_text(
                json.dumps({"last_sent_fingerprint": fingerprint}), encoding="utf-8"
            )
            with (
                patch("quota_watch.client.agent.ClientConfig.load", return_value=config),
                patch("quota_watch.client.agent.send_snapshot") as send,
                patch.object(sys, "argv", ["quota-watch-agent", "--config", "unused", "--once"]),
            ):
                main()
            send.assert_not_called()

    def test_changed_local_state_calls_network_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            config = self._config(state_dir)
            self._write_activity(state_dir / "activity.json", "idle")
            fingerprint = snapshot_fingerprint(build_snapshot(config))
            (state_dir / "sync-state.json").write_text(
                json.dumps({"last_sent_fingerprint": fingerprint}), encoding="utf-8"
            )
            self._write_activity(state_dir / "activity.json", "working")
            with (
                patch("quota_watch.client.agent.ClientConfig.load", return_value=config),
                patch("quota_watch.client.agent.send_snapshot") as send,
                patch.object(sys, "argv", ["quota-watch-agent", "--config", "unused", "--once"]),
            ):
                main()
            send.assert_called_once()

    def test_active_codex_is_polled_every_five_seconds(self) -> None:
        activity = AgentActivity(
            provider=Provider.CODEX,
            state=AgentState.WORKING,
            active_sessions=1,
        )
        self.assertFalse(
            should_poll_codex_limits(
                activity=activity,
                cache_missing=False,
                activity_changed=False,
                explicitly_requested=False,
                now_monotonic=104.9,
                last_poll_monotonic=100.0,
                poll_seconds=5.0,
            )
        )
        self.assertTrue(
            should_poll_codex_limits(
                activity=activity,
                cache_missing=False,
                activity_changed=False,
                explicitly_requested=False,
                now_monotonic=105.0,
                last_poll_monotonic=100.0,
                poll_seconds=5.0,
            )
        )

    def test_idle_codex_is_not_polled_on_timer(self) -> None:
        activity = AgentActivity(provider=Provider.CODEX, state=AgentState.IDLE)
        self.assertFalse(
            should_poll_codex_limits(
                activity=activity,
                cache_missing=False,
                activity_changed=False,
                explicitly_requested=False,
                now_monotonic=1_000.0,
                last_poll_monotonic=0.0,
                poll_seconds=5.0,
            )
        )

    def test_idle_codex_is_polled_on_timer_when_enabled(self) -> None:
        activity = AgentActivity(provider=Provider.CODEX, state=AgentState.IDLE)
        for state_activity in (activity, None):
            self.assertFalse(
                should_poll_codex_limits(
                    activity=state_activity,
                    cache_missing=False,
                    activity_changed=False,
                    explicitly_requested=False,
                    now_monotonic=104.9,
                    last_poll_monotonic=100.0,
                    poll_seconds=5.0,
                    poll_when_idle=True,
                )
            )
            self.assertTrue(
                should_poll_codex_limits(
                    activity=state_activity,
                    cache_missing=False,
                    activity_changed=False,
                    explicitly_requested=False,
                    now_monotonic=105.0,
                    last_poll_monotonic=100.0,
                    poll_seconds=5.0,
                    poll_when_idle=True,
                )
            )


if __name__ == "__main__":
    unittest.main()
