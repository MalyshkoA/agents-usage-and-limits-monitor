from __future__ import annotations

import hmac
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone

from quota_watch.common.signing import sign_request, verify_signature


class SlidingWindowLimiter:
    def __init__(
        self, max_events: int, window_seconds: int = 60, max_keys: int = 10_000
    ) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        current = now if now is not None else time.monotonic()
        cutoff = current - self.window_seconds
        with self._lock:
            events = self._events.get(key)
            if events is None:
                if len(self._events) >= self.max_keys:
                    self._events.popitem(last=False)
                events = deque()
                self._events[key] = events
            else:
                self._events.move_to_end(key)
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= self.max_events:
                return False
            events.append(current)
            return True


def parse_unix_timestamp(value: str) -> datetime:
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def verify_device_request(
    *,
    secret: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
    provided_signature: str,
    now: datetime,
    max_age_seconds: int,
) -> bool:
    try:
        request_time = parse_unix_timestamp(timestamp)
    except (ValueError, OverflowError):
        return False
    if abs((now - request_time).total_seconds()) > max_age_seconds:
        return False
    expected = sign_request(
        secret=secret,
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    return verify_signature(expected=expected, provided=provided_signature)


def widget_key_is_valid(provided: str | None, valid_keys: frozenset[str]) -> bool:
    if not provided:
        return False
    return any(hmac.compare_digest(provided, valid) for valid in valid_keys)
