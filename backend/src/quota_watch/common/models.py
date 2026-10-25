from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


Percent = Annotated[float, Field(ge=0, le=100)]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Provider(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"


class AgentState(StrEnum):
    WORKING = "working"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    IDLE = "idle"
    ERROR = "error"
    UNKNOWN = "unknown"


class LimitWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_minutes: int = Field(gt=0, le=60 * 24 * 31)
    used_percent: Percent
    resets_at: AwareDatetime | None = None

    @property
    def remaining_percent(self) -> float:
        return round(max(0.0, 100.0 - self.used_percent), 1)


class ProviderLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(default="default", min_length=1, max_length=64)
    observed_at: AwareDatetime = Field(default_factory=utc_now)
    five_hour: LimitWindow | None = None
    weekly: LimitWindow | None = None
    source: str = Field(default="unknown", max_length=64)


class AgentActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Provider
    state: AgentState = AgentState.UNKNOWN
    session_id_hash: str | None = Field(default=None, max_length=64)
    active_sessions: int = Field(default=0, ge=0, le=100)
    working_sessions: int = Field(default=0, ge=0, le=100)
    waiting_approval_sessions: int = Field(default=0, ge=0, le=100)
    waiting_input_sessions: int = Field(default=0, ge=0, le=100)
    error_sessions: int = Field(default=0, ge=0, le=100)
    observed_at: AwareDatetime = Field(default_factory=utc_now)
    error_code: str | None = Field(default=None, max_length=64)


class DeviceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    device_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")
    display_name: str = Field(min_length=1, max_length=64)
    sent_at: AwareDatetime = Field(default_factory=utc_now)
    agent_version: str = Field(default="unknown", max_length=32)
    delivery_mode: Literal["change_only", "heartbeat"] = "change_only"
    limits: dict[Provider, ProviderLimits] = Field(default_factory=dict)
    activity: dict[Provider, AgentActivity] = Field(default_factory=dict)
