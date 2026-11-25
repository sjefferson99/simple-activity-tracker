import math
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.validation import (
    EMAIL_MAX_LENGTH,
    LIVE_POINTS_MAX_PER_REQUEST,
    LIVE_VIEWERS_MAX,
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

# Every request model uses extra="ignore", never "forbid": a newer app sends
# fields this server doesn't know yet, and rejecting them (as every server up
# to v1.2.4 did) makes the upload fail outright. See docs/VERSIONING.md §5.
# test_api_contract.py separately proves the *current* app's payload has no
# field this server ignores.


class SplitSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

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
    model_config = ConfigDict(extra="ignore")

    platform: str
    app_version: str


class ActivitySummary(BaseModel):
    """The phone's own numbers, uploaded verbatim — mirrors LiveMetrics.
    See docs/WEB-PLAN.md §5.3."""

    model_config = ConfigDict(extra="ignore")

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


def known_summary_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """The uploaded summary JSON minus any field this server doesn't know.

    Uploads store the phone's summary verbatim as ``client_summary`` (original
    values and formatting intact), but request models now ignore unknown
    fields rather than rejecting them — so strip those here too, keeping the
    stored record limited to what this server actually understands. Call only
    after ``ActivitySummary`` validation has passed (shapes are assumed valid).
    """

    def pick(model: type[BaseModel], data: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in data.items() if key in model.model_fields}

    known = pick(ActivitySummary, raw)
    known["source"] = pick(ActivitySource, raw["source"])
    if "splits" in raw:
        known["splits"] = [pick(SplitSummary, split) for split in raw["splits"]]
    return known


# --- Auth ---


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

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
    model_config = ConfigDict(extra="ignore")

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
    model_config = ConfigDict(extra="ignore")

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


class SplitLayoutSplit(BaseModel):
    """One single split in a saved config's editor layout (issue #233)."""

    model_config = ConfigDict(extra="ignore")

    split: tuple[float, float | None]


class SplitLayoutRepeat(BaseModel):
    """`repeat x [splits...]` in a saved config's editor layout (issue #233),
    e.g. 5 x [3:00 @ 10 km/h, 2:00 @ 7 km/h]."""

    model_config = ConfigDict(extra="ignore")

    repeat: int = Field(ge=1, le=SPLIT_CONFIG_MAX_CUSTOM_SPLITS)
    splits: list[tuple[float, float | None]] = Field(
        min_length=1, max_length=SPLIT_CONFIG_MAX_CUSTOM_SPLITS
    )


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

    model_config = ConfigDict(extra="ignore")

    split_type: Literal["distance_km", "distance_mi", "time_min"]
    split_value: int = Field(gt=0)
    rolling_target_mps: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    custom_splits: list[tuple[float, float | None]] = Field(
        default_factory=list, max_length=SPLIT_CONFIG_MAX_CUSTOM_SPLITS
    )
    targets_as: Literal["pace", "speed"] = "pace"
    # How an editor groups custom_splits into repeat blocks (issue #233).
    # custom_splits stays the expanded list that runs, so older apps and the
    # analyzer never need this; when given it must expand to exactly
    # custom_splits. A layout with no repeat block carries nothing the flat
    # list doesn't, so it's normalised to None.
    layout: list[SplitLayoutSplit | SplitLayoutRepeat] | None = Field(
        default=None, max_length=SPLIT_CONFIG_MAX_CUSTOM_SPLITS
    )

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

    @model_validator(mode="after")
    def _validate_layout(self) -> "SplitPlanIn":
        if self.layout is None:
            return self
        if not any(isinstance(e, SplitLayoutRepeat) for e in self.layout):
            self.layout = None
            return self
        if not self.custom_splits:
            raise ValueError("layout must not be set for a rolling plan")
        # Check the size arithmetically before expanding, so a huge repeat
        # count can't allocate a huge list.
        expanded_length = sum(
            e.repeat * len(e.splits) if isinstance(e, SplitLayoutRepeat) else 1 for e in self.layout
        )
        if expanded_length != len(self.custom_splits) or (
            expand_layout(self.layout) != list(self.custom_splits)
        ):
            raise ValueError("layout must expand to exactly custom_splits")
        return self


def split_plan_in_to_json(plan: SplitPlanIn) -> dict[str, object]:
    """The JSON stored in SplitConfig.plan. `layout` is only written when the
    plan has repeat blocks, so a flat plan is stored exactly as before."""
    stored: dict[str, object] = {
        "split_type": plan.split_type,
        "split_value": plan.split_value,
        "rolling_target_mps": plan.rolling_target_mps,
        "custom_splits": [[size, target] for size, target in plan.custom_splits],
        "targets_as": plan.targets_as,
    }
    if plan.layout is not None:
        stored["layout"] = [
            {"repeat": e.repeat, "splits": [[size, target] for size, target in e.splits]}
            if isinstance(e, SplitLayoutRepeat)
            else {"split": [e.split[0], e.split[1]]}
            for e in plan.layout
        ]
    return stored


def expand_layout(
    layout: list[SplitLayoutSplit | SplitLayoutRepeat],
) -> list[tuple[float, float | None]]:
    """The flat custom_splits a layout stands for, in run order."""
    expanded: list[tuple[float, float | None]] = []
    for entry in layout:
        if isinstance(entry, SplitLayoutRepeat):
            expanded.extend(list(entry.splits) * entry.repeat)
        else:
            expanded.append(entry.split)
    return expanded


class SplitConfigSourceRef(BaseModel):
    id: str
    name: str


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
    # Split library (issue #143, API level 4). Absent from older servers, so
    # apps read them as optional.
    uid: str | None = None
    # Own configs: the folder as typed. Templates: the folder's path in the
    # repo ("" for the repo's top folder); show folder_name instead.
    folder: str | None = None
    folder_name: str | None = None
    read_only: bool = False
    source: SplitConfigSourceRef | None = None


class SplitConfigListResponse(BaseModel):
    configs: list[SplitConfigOut]


def _clean_folder_field(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = " ".join(value.split())
    return stripped or None


class SplitConfigCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=SPLIT_CONFIG_NAME_MAX_LENGTH)
    plan: SplitPlanIn
    # When true and a config with this name already exists for the caller,
    # overwrite it in place (same id, bumped updated_at) instead of
    # rejecting with 409 — see docs/SPLIT-CONFIGS-PLAN.md §3.
    overwrite: bool = False
    # Issue #143 (API level 4): the folder to file it in; blank = none. When
    # overwriting, an omitted folder keeps the existing one.
    folder: str | None = Field(default=None, max_length=SPLIT_CONFIG_NAME_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("folder")
    @classmethod
    def _folder(cls, value: str | None) -> str | None:
        return _clean_folder_field(value)


class SplitConfigPatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=SPLIT_CONFIG_NAME_MAX_LENGTH)
    plan: SplitPlanIn | None = None
    # Issue #143 (API level 4): omitted = unchanged, "" = no folder.
    folder: str | None = Field(default=None, max_length=SPLIT_CONFIG_NAME_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class SplitConfigImportResponse(BaseModel):
    """Result of importing a split config file (issue #143)."""

    created: int
    updated: int
    # "Old name → new name" for each config renamed because its name was taken.
    renamed: list[str]
    # One message per entry that couldn't be imported.
    errors: list[str]


class SplitSourceFolderOut(BaseModel):
    id: str
    folder: str
    name: str
    description: str | None
    enabled: bool
    template_count: int


class SplitSourceOut(BaseModel):
    """A split template repo the user subscribes to (issue #143). The access
    token is never returned, only whether one is set."""

    id: str
    name: str
    url: str
    host_kind: Literal["github", "gitlab", "gitea"]
    ref: str
    path: str
    enabled: bool
    is_default: bool
    has_token: bool
    last_synced_at: datetime | None
    last_commit: str | None
    last_error: str | None
    warnings: list[str]
    folders: list[SplitSourceFolderOut]


class SplitSourceListResponse(BaseModel):
    sources: list[SplitSourceOut]
    # Whether this server lets users add their own repos.
    can_add: bool


class SplitSourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str = Field(min_length=1, max_length=500)
    # Omitted: github.com/gitlab.com by name, anything else Gitea/Forgejo.
    host_kind: Literal["github", "gitlab", "gitea"] | None = None
    ref: str = Field(default="main", max_length=200)
    path: str = Field(default="splits", max_length=500)
    name: str | None = Field(default=None, max_length=SPLIT_CONFIG_NAME_MAX_LENGTH)
    token: str | None = Field(default=None, max_length=1000)


class SplitSourcePatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, max_length=SPLIT_CONFIG_NAME_MAX_LENGTH)
    ref: str | None = Field(default=None, max_length=200)
    path: str | None = Field(default=None, max_length=500)
    # A new token replaces the stored one; clear_token removes it.
    token: str | None = Field(default=None, max_length=1000)
    clear_token: bool = False
    enabled: bool | None = None


class SplitSourceFolderPatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool


class SplitSourceSyncResponse(BaseModel):
    ok: bool
    added: int
    updated: int
    removed: int
    error: str | None
    source: SplitSourceOut


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
    model_config = ConfigDict(extra="ignore")

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
    model_config = ConfigDict(extra="ignore")

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
    # Issue #190. Defaulted so archives from older servers still import.
    is_virtual: bool = False


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
    model_config = ConfigDict(extra="ignore")

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
    model_config = ConfigDict(extra="ignore")

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
    model_config = ConfigDict(extra="ignore")

    new_password: str

    @field_validator("new_password")
    @classmethod
    def _validate_new_password(cls, value: str) -> str:
        try:
            return validate_password(value)
        except ValidationFailedError as exc:
            raise ValueError(str(exc)) from exc


class ServerInfoOut(BaseModel):
    version: str
    api_level: int
    min_app_api_level: int


# --- live tracking and sharing (issue #130, API level 2) -------------------


class UserDirectoryEntry(BaseModel):
    """Another user, as anyone signed in may see them: never their email."""

    id: str
    display_name: str


class UserDirectoryResponse(BaseModel):
    users: list[UserDirectoryEntry]


class ShareOut(BaseModel):
    viewer_id: str
    display_name: str
    can_view_live: bool
    can_view_history: bool


class MySharesResponse(BaseModel):
    live_sharing_paused: bool
    shares: list[ShareOut]


class LiveSharingRequest(BaseModel):
    """The phone's whole live-sharing setting in one idempotent document, so
    a change queued while offline can be replayed as-is (last write wins).
    Sets the Live grant for exactly `live_viewer_ids`; History is untouched."""

    model_config = ConfigDict(extra="ignore")

    live_sharing_paused: bool
    live_viewer_ids: list[str] = Field(default_factory=list, max_length=LIVE_VIEWERS_MAX)


class LiveSessionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    activity_type: Literal["running", "cycling", "walking"]
    # Aware only: a naive time can't be stored (TZDateTime), and must be a 422
    # here rather than a failure at commit time, after the response is sent.
    started_at: AwareDatetime
    split_plan: SplitPlanIn | None = None


class LivePointIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    t: AwareDatetime  # see LiveSessionIn.started_at
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    ele: float | None = Field(default=None, ge=-1000, le=10000, allow_inf_nan=False)
    accuracy: float | None = Field(default=None, ge=0, le=100_000, allow_inf_nan=False)
    speed: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    # Increments on each resume after a pause.
    segment: int = Field(default=0, ge=0, le=10_000)


class LiveMetricsIn(BaseModel):
    """What the phone currently shows, displayed verbatim on the live page."""

    model_config = ConfigDict(extra="ignore")

    distance_meters: float = Field(ge=0, allow_inf_nan=False)
    elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)
    moving_seconds: float = Field(ge=0, allow_inf_nan=False)
    avg_speed_mps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    current_speed_mps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    splits: list[SplitSummary] = Field(default_factory=list, max_length=SPLITS_MAX_COUNT)


class LivePointsIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    from_index: int = Field(ge=0)
    points: list[LivePointIn] = Field(default_factory=list, max_length=LIVE_POINTS_MAX_PER_REQUEST)
    metrics: LiveMetricsIn | None = None
    state: Literal["active", "paused", "finished"] = "active"


class LiveSessionStateOut(BaseModel):
    """`next_index` is the next point the server expects; the phone resends
    from there. `state` is the server's view of the session."""

    next_index: int
    state: Literal["active", "paused", "finished", "converted"]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
