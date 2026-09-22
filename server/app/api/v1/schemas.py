import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.validation import (
    EMAIL_MAX_LENGTH,
    NAME_MAX_LENGTH,
    NOTES_MAX_LENGTH,
    PASSWORD_MAX_LENGTH,
    SPLIT_CONFIG_MAX_CUSTOM_SPLITS,
    SPLIT_CONFIG_NAME_MAX_LENGTH,
    SPLITS_MAX_COUNT,
    TAG_NAME_MAX_LENGTH,
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
    # Optional: older app versions (before #43's configurable splits) never
    # sent this. Constant across every split for a distance-based
    # preference, but varies per split for a time-based one.
    distance_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    # Optional: older app versions (before #106) never sent this. Null when
    # the split had no target (no split-targets feature in use, or a custom
    # plan's rolled-on split beyond the last planned one).
    target_speed_mps: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ActivitySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    app_version: str


class ActivitySummary(BaseModel):
    """The phone's own numbers, uploaded verbatim — mirrors LiveMetrics.
    See docs/WEB-PLAN.md §5.3."""

    model_config = ConfigDict(extra="forbid")

    client_activity_id: str
    activity_type: Literal["running", "cycling", "walking"]
    started_at: datetime
    ended_at: datetime
    moving_seconds: float = Field(ge=0, allow_inf_nan=False)
    distance_meters: float = Field(ge=0, allow_inf_nan=False)
    avg_speed_mps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    # Optional: older app versions (before #106) never sent these.
    max_speed_mps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    elevation_gain_meters: float = Field(default=0, ge=0, allow_inf_nan=False)
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


class TagOut(BaseModel):
    id: str
    name: str


class AddTagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=TAG_NAME_MAX_LENGTH)


class ActivityListItem(BaseModel):
    id: str
    activity_type: Literal["running", "cycling", "walking"]
    started_at: datetime
    ended_at: datetime
    title: str | None
    distance_meters: float
    moving_seconds: float
    tags: list[TagOut]


class ActivityListResponse(BaseModel):
    activities: list[ActivityListItem]
    next_cursor: str | None


class AnalysisOut(BaseModel):
    status: Literal["pending", "done", "failed"]
    result: dict[str, Any] | None = None


class SplitPlanOut(BaseModel):
    """The split plan an activity was uploaded with (issue #100) — mirrors
    Activity.split_plan/app.analysis.gpx_parser.SplitPlanData. None on
    ActivityOut for an activity with no plan at all (an old upload, or a
    plain rolling preference with no target)."""

    rolling_target_mps: float | None
    # (size, target) pairs, splits 1..N of a custom plan; empty for a
    # rolling plan. Size is metres/seconds per the activity's own
    # split_type; target is null for an untargeted custom split.
    custom_splits: list[tuple[float, float | None]]
    targets_as: Literal["pace", "speed"]


class SplitPlanIn(BaseModel):
    """A client-supplied split plan (issue #126) — the same five fields as
    SplitPlanOut/app.analysis.gpx_parser.SplitPlanData, but as an untrusted
    write-side model with real validation, used to create/update a
    SplitConfig. Unlike SplitPlanOut (built server-side from a parsed GPX,
    never re-validated) this is the boundary that stops a malformed plan —
    negative sizes, an over-long custom list, both/neither of rolling vs
    custom — from ever reaching the database. Mirrors mobile's
    SplitPlan.fromJson validation exactly (see
    docs/SPLIT-CONFIGS-PLAN.md §2.2)."""

    model_config = ConfigDict(extra="forbid")

    split_type: Literal["distance_km", "distance_mi", "time_min"]
    split_value: int = Field(gt=0)
    rolling_target_mps: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    custom_splits: list[tuple[float, float | None]] = Field(
        default_factory=list, max_length=SPLIT_CONFIG_MAX_CUSTOM_SPLITS
    )
    targets_as: Literal["pace", "speed"] = "pace"

    @field_validator("custom_splits")
    @classmethod
    def _validate_custom_splits(
        cls, value: list[tuple[float, float | None]]
    ) -> list[tuple[float, float | None]]:
        for size, target in value:
            if not (size > 0) or not math.isfinite(size):
                raise ValueError("Each custom split's size must be greater than 0")
            if target is not None and (not (target > 0) or not math.isfinite(target)):
                raise ValueError("Each custom split's target must be greater than 0")
        return value

    @model_validator(mode="after")
    def _validate_rolling_vs_custom(self) -> "SplitPlanIn":
        # Mirrors mobile's SplitPlan: rolling_target_mps only ever applies to
        # a rolling plan (empty custom_splits) — a custom plan's per-split
        # targets are the only targets that apply once it is non-empty (see
        # SplitPlan.targetOf). Silently accepting both would let a client
        # send a rolling_target_mps that the server (and every other client)
        # would then ignore without any indication why.
        if self.custom_splits and self.rolling_target_mps is not None:
            raise ValueError("rolling_target_mps must not be set when custom_splits is non-empty")
        return self


class SplitConfigOut(BaseModel):
    """A saved, named split plan (issue #126).

    plan is typed as SplitPlanIn, not SplitPlanOut — unlike an activity's
    split_plan (where split_type/split_value already live on separate
    Activity columns, so SplitPlanOut only needs the other three fields), a
    SplitConfig is a standalone plan with nothing else to fall back on: its
    plan JSON carries split_type/split_value directly, and SplitPlanIn is
    the model with all five fields plus the validation new plan data must
    already have passed to be stored here."""

    id: str
    name: str
    plan: SplitPlanIn
    created_at: datetime
    updated_at: datetime


class SplitConfigListResponse(BaseModel):
    configs: list[SplitConfigOut]


class SplitConfigCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=SPLIT_CONFIG_NAME_MAX_LENGTH)
    plan: SplitPlanIn
    # When true and a config with this name already exists for the caller,
    # overwrite it in place (same id, bumped updated_at) instead of
    # rejecting with 409 — see docs/SPLIT-CONFIGS-PLAN.md §3.
    overwrite: bool = False

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class SplitConfigPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=SPLIT_CONFIG_NAME_MAX_LENGTH)
    plan: SplitPlanIn | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class ActivityOut(BaseModel):
    id: str
    client_activity_id: str
    activity_type: Literal["running", "cycling", "walking"]
    started_at: datetime
    ended_at: datetime
    title: str | None
    notes: str | None
    device_name: str | None
    client_summary: dict[str, Any]
    source_platform: str
    source_app_version: str
    created_at: datetime
    updated_at: datetime
    analysis: AnalysisOut
    tags: list[TagOut]
    split_plan: SplitPlanOut | None = None


class ActivityPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=TITLE_MAX_LENGTH)
    notes: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)
    device_name: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)


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
    activity_type: Literal["running", "cycling", "walking"]
    started_at: datetime
    ended_at: datetime
    title: str | None
    notes: str | None
    device_name: str | None = None
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


class StravaImportJobCreated(BaseModel):
    """Returned by POST /activities/import/strava (202 Accepted): the client
    polls GET /activities/import/strava/{job_id}/status for progress/result,
    mirroring the web app's own background-job flow for the same import."""

    job_id: str
    total: int


class StravaImportJobStatus(BaseModel):
    status: Literal["pending", "running", "done", "error"]
    processed: int
    total: int
    error: str | None = None
    result: ImportResult | None = None


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
