from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SplitSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    duration_seconds: float = Field(ge=0)
    avg_speed_mps: float = Field(ge=0)


class ActivitySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    app_version: str


class ActivitySummary(BaseModel):
    """The phone's own numbers, uploaded verbatim — mirrors LiveMetrics.
    See docs/WEB-PLAN.md §5.3."""

    model_config = ConfigDict(extra="forbid")

    client_activity_id: str
    activity_type: Literal["running", "cycling"]
    started_at: datetime
    ended_at: datetime
    moving_seconds: float = Field(ge=0, allow_inf_nan=False)
    distance_meters: float = Field(ge=0, allow_inf_nan=False)
    avg_speed_mps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    splits: list[SplitSummary] = Field(default_factory=list)
    source: ActivitySource


# --- Auth ---


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str
    device_name: str


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    is_admin: bool


class DeviceOut(BaseModel):
    id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None


class LoginResponse(BaseModel):
    token: str
    device: DeviceOut
    user: UserOut


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str


# --- Activities ---


class ActivityListItem(BaseModel):
    id: str
    activity_type: Literal["running", "cycling"]
    started_at: datetime
    ended_at: datetime
    title: str | None
    distance_meters: float
    moving_seconds: float


class ActivityListResponse(BaseModel):
    activities: list[ActivityListItem]
    next_cursor: str | None


class AnalysisOut(BaseModel):
    status: Literal["pending", "done", "failed"]
    result: dict[str, Any] | None = None


class ActivityOut(BaseModel):
    id: str
    client_activity_id: str
    activity_type: Literal["running", "cycling"]
    started_at: datetime
    ended_at: datetime
    title: str | None
    notes: str | None
    client_summary: dict[str, Any]
    source_platform: str
    source_app_version: str
    created_at: datetime
    updated_at: datetime
    analysis: AnalysisOut


class ActivityPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)


class TrackPointOut(BaseModel):
    lat: float
    lon: float
    ele: float | None
    t: float


class TrackOut(BaseModel):
    segments: list[list[TrackPointOut]]


# --- Admin ---


class AdminUserOut(BaseModel):
    id: str
    email: str
    display_name: str
    is_admin: bool
    disabled: bool
    activity_count: int
    last_activity_at: datetime | None
    created_at: datetime


class AdminCreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    display_name: str
    password: str
    is_admin: bool = False


class AdminPatchUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    is_admin: bool | None = None
    disabled: bool | None = None


class AdminSetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
