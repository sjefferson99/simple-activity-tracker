"""Split config files (docs/SPLIT-LIBRARY-PLAN.md §1): one config per file in a
template repo or a single-config export, and a bundle for exporting many.
Import accepts either. Plans are validated exactly as an API write is
(SplitPlanIn), so a file can never store what the editor couldn't."""

import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.api.v1.schemas import SplitPlanIn, split_plan_in_to_json
from app.models.split_config import SplitConfig
from app.validation import SPLIT_CONFIG_NAME_MAX_LENGTH

FORMAT_ONE = "sat-split-config"
FORMAT_BUNDLE = "sat-split-configs"
FORMAT_VERSION = 1
FOLDER_META_FILE = "_folder.json"
FOLDER_MAX_LENGTH = 200
# More than any real library; keeps one import from being a DB-filling tool.
MAX_CONFIGS_PER_DOCUMENT = 500


def _clean_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("name must not be blank")
    return stripped


def normalise_uid(value: str | None) -> str | None:
    """A uid as stored (canonical lowercase UUID), or None when absent.
    Raises ValueError for anything that isn't a UUID."""
    if value is None or not str(value).strip():
        return None
    return str(uuid.UUID(str(value).strip()))


def clean_folder(value: str | None) -> str | None:
    """An own config's folder: trimmed, None when blank."""
    if value is None:
        return None
    stripped = " ".join(value.split())
    if not stripped:
        return None
    if len(stripped) > FOLDER_MAX_LENGTH:
        raise ValueError(f"folder must be at most {FOLDER_MAX_LENGTH} characters")
    return stripped


class _ConfigEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str | None = None
    name: str = Field(min_length=1, max_length=SPLIT_CONFIG_NAME_MAX_LENGTH)
    folder: str | None = None
    plan: SplitPlanIn

    @field_validator("uid")
    @classmethod
    def _uid(cls, value: str | None) -> str | None:
        return normalise_uid(value)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("folder")
    @classmethod
    def _folder(cls, value: str | None) -> str | None:
        return clean_folder(value)


class _OneDocument(_ConfigEntry):
    format: Literal["sat-split-config"]
    version: int = Field(ge=1)


class _BundleDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format: Literal["sat-split-configs"]
    version: int = Field(ge=1)
    configs: list[dict[str, Any]] = Field(max_length=MAX_CONFIGS_PER_DOCUMENT)


class _FolderMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, max_length=FOLDER_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=2000)


@dataclass(frozen=True)
class ParsedConfig:
    uid: str | None
    name: str
    folder: str | None
    plan: dict[str, object]  # as stored in SplitConfig.plan


class DocumentError(ValueError):
    """A whole document is unusable (not JSON, unknown format)."""


def _first_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "invalid"
    first = errors[0]
    where = ".".join(str(p) for p in first.get("loc", ()))
    message = str(first.get("msg", "invalid"))
    return f"{where}: {message}" if where else message


def _load_json(data: bytes | str | object) -> object:
    if isinstance(data, bytes | str):
        try:
            return json.loads(data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise DocumentError("not valid JSON") from exc
    return data


def _entry_to_parsed(entry: _ConfigEntry) -> ParsedConfig:
    return ParsedConfig(
        uid=entry.uid,
        name=entry.name,
        folder=entry.folder,
        plan=split_plan_in_to_json(entry.plan),
    )


def parse_one(data: bytes | str | object) -> ParsedConfig:
    """A single-config file (a template repo file). Raises DocumentError."""
    document = _load_json(data)
    if not isinstance(document, dict) or document.get("format") != FORMAT_ONE:
        raise DocumentError(f'not a split config file (expected "format": "{FORMAT_ONE}")')
    try:
        return _entry_to_parsed(_OneDocument.model_validate(document))
    except ValidationError as exc:
        raise DocumentError(_first_error(exc)) from exc


def parse_document(data: bytes | str | object) -> tuple[list[ParsedConfig], list[str]]:
    """An import: a bundle or a single config. Returns the valid configs and
    one message per invalid entry; raises DocumentError if the document as a
    whole is unusable."""
    document = _load_json(data)
    if not isinstance(document, dict):
        raise DocumentError("not a split config file")
    if document.get("format") == FORMAT_ONE:
        return [parse_one(document)], []
    if document.get("format") != FORMAT_BUNDLE:
        raise DocumentError(
            f'not a split config file (expected "format": "{FORMAT_BUNDLE}" or "{FORMAT_ONE}")'
        )
    try:
        bundle = _BundleDocument.model_validate(document)
    except ValidationError as exc:
        raise DocumentError(_first_error(exc)) from exc
    parsed: list[ParsedConfig] = []
    errors: list[str] = []
    for i, raw in enumerate(bundle.configs, start=1):
        label = raw.get("name") if isinstance(raw.get("name"), str) else f"#{i}"
        try:
            parsed.append(_entry_to_parsed(_ConfigEntry.model_validate(raw)))
        except ValidationError as exc:
            errors.append(f"{label}: {_first_error(exc)}")
    return parsed, errors


def parse_folder_meta(data: bytes) -> tuple[str | None, str | None]:
    """(display name, description) from a _folder.json; raises DocumentError."""
    document = _load_json(data)
    try:
        meta = _FolderMeta.model_validate(document)
    except ValidationError as exc:
        raise DocumentError(_first_error(exc)) from exc
    name = meta.name.strip() if meta.name and meta.name.strip() else None
    return name, meta.description


def _plan_for_file(config: SplitConfig) -> dict[str, object]:
    # Re-validate on the way out, so a file always matches what import reads.
    return split_plan_in_to_json(SplitPlanIn.model_validate(config.plan))


def one_document(config: SplitConfig) -> dict[str, object]:
    """A single config as a file — the same format a template repo uses."""
    return {
        "format": FORMAT_ONE,
        "version": FORMAT_VERSION,
        "uid": config.uid,
        "name": config.name,
        "plan": _plan_for_file(config),
    }


def bundle_document(configs: list[tuple[SplitConfig, str | None]]) -> dict[str, object]:
    """Many configs, each with the folder name it should import into."""
    return {
        "format": FORMAT_BUNDLE,
        "version": FORMAT_VERSION,
        "configs": [
            {
                "uid": config.uid,
                "name": config.name,
                "folder": folder,
                "plan": _plan_for_file(config),
            }
            for config, folder in configs
        ],
    }
