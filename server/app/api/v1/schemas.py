from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SplitSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    duration_seconds: float = Field(ge=0)
    avg_speed_mps: float = Field(ge=0)


class RunSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    app_version: str


class RunSummary(BaseModel):
    """The phone's own numbers, uploaded verbatim — mirrors LiveMetrics.
    See docs/WEB-PLAN.md §5.3."""

    model_config = ConfigDict(extra="forbid")

    client_run_id: str
    started_at: datetime
    ended_at: datetime
    moving_seconds: float = Field(ge=0, allow_inf_nan=False)
    distance_meters: float = Field(ge=0, allow_inf_nan=False)
    avg_speed_mps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    splits: list[SplitSummary] = Field(default_factory=list)
    source: RunSource


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


# --- Runs ---


class RunListItem(BaseModel):
    id: str
    started_at: datetime
    ended_at: datetime
    title: str | None
    distance_meters: float
    moving_seconds: float


class RunListResponse(BaseModel):
    runs: list[RunListItem]
    next_cursor: str | None


class AnalysisOut(BaseModel):
    status: Literal["pending", "done", "failed"]
    result: dict[str, Any] | None = None


class RunOut(BaseModel):
    id: str
    client_run_id: str
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


class RunPatchRequest(BaseModel):
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
    run_count: int
    last_run_at: datetime | None
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
