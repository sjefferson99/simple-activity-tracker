from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.validation import (
    EMAIL_MAX_LENGTH,
    NAME_MAX_LENGTH,
    NOTES_MAX_LENGTH,
    PASSWORD_MAX_LENGTH,
    SPLITS_MAX_COUNT,
    TITLE_MAX_LENGTH,
    ValidationFailedError,
    normalize_email,
    validate_name,
    validate_password,
)


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
    splits: list[SplitSummary] = Field(default_factory=list, max_length=SPLITS_MAX_COUNT)
    source: ActivitySource


# --- Auth ---


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str = Field(max_length=PASSWORD_MAX_LENGTH)
    device_name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        # Login intentionally accepts a malformed-looking email rather than
        # rejecting it here — the generic "invalid credentials" message
        # (docs/WEB-PLAN.md §5.6) must not distinguish "bad email shape" from
        # "wrong password", or it becomes a user-enumeration/format oracle.
        # Just lowercase+trim so lookups still match what registration stored.
        return value.strip().lower()

    @field_validator("device_name")
    @classmethod
    def _strip_device_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("device_name must not be blank")
        return stripped


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

    current_password: str = Field(max_length=PASSWORD_MAX_LENGTH)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _validate_new_password(cls, value: str) -> str:
        try:
            return validate_password(value)
        except ValidationFailedError as exc:
            raise ValueError(str(exc)) from exc


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

    title: str | None = Field(default=None, max_length=TITLE_MAX_LENGTH)
    notes: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)


class TrackPointOut(BaseModel):
    lat: float
    lon: float
    ele: float | None
    t: float


class TrackOut(BaseModel):
    segments: list[list[TrackPointOut]]


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None means "export every activity the caller owns".
    activity_ids: list[str] | None = None


class ExportManifestEntry(BaseModel):
    """One activity's metadata inside an export archive's manifest.json —
    deliberately excludes server-assigned fields (id, gpx_sha256/bytes,
    created_at/updated_at) since import re-derives all of those."""

    client_activity_id: str
    activity_type: Literal["running", "cycling"]
    started_at: datetime
    ended_at: datetime
    title: str | None
    notes: str | None
    client_summary: dict[str, Any]
    source_platform: str
    source_app_version: str
    gpx_filename: str


class ExportManifest(BaseModel):
    activities: list[ExportManifestEntry]


class ImportResultItem(BaseModel):
    client_activity_id: str
    status: Literal["imported", "skipped", "failed"]
    reason: str | None = None


class ImportResult(BaseModel):
    imported: int
    skipped: int
    failed: int
    items: list[ImportResultItem]


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

    email: str = Field(max_length=EMAIL_MAX_LENGTH)
    display_name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    password: str
    is_admin: bool = False

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        try:
            return normalize_email(value)
        except ValidationFailedError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("display_name")
    @classmethod
    def _strip_display_name(cls, value: str) -> str:
        try:
            return validate_name(value, field="Display name")
        except ValidationFailedError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        try:
            return validate_password(value)
        except ValidationFailedError as exc:
            raise ValueError(str(exc)) from exc


class AdminPatchUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    is_admin: bool | None = None
    disabled: bool | None = None

    @field_validator("display_name")
    @classmethod
    def _strip_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return validate_name(value, field="Display name")
        except ValidationFailedError as exc:
            raise ValueError(str(exc)) from exc


class AdminSetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str

    @field_validator("new_password")
    @classmethod
    def _validate_new_password(cls, value: str) -> str:
        try:
            return validate_password(value)
        except ValidationFailedError as exc:
            raise ValueError(str(exc)) from exc


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
