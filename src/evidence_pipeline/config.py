"""Study protocol and source configuration loading."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import ConfigurationError
from .models import SearchQuery


@dataclass(slots=True)
class SourceConfig:
    name: str
    enabled: bool = True
    required: bool = False
    api_key_env: str | None = None
    timeout_seconds: float = 30.0
    max_retries: int = 2
    backoff_seconds: float = 1.0
    include_abstracts: bool = True
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env) if self.api_key_env else None


@dataclass(slots=True)
class StudyConfig:
    study_id: str
    profile_id: str
    min_year: int
    max_year: int
    search_language: str
    include_abstracts: bool
    sources: dict[str, SourceConfig]
    contact_email_env: str = "RESEARCH_CONTACT_EMAIL"
    env_overrides: tuple[str, ...] = ()

    @property
    def contact_email(self) -> str:
        return os.getenv(self.contact_email_env, "researcher@example.org")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigurationError(f"Configuration file does not exist: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ConfigurationError(f"Expected YAML mapping in {path}")
    return value


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def _env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _env_int(name: str, default: int, overrides: list[str]) -> int:
    value = _env_value(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    overrides.append(name)
    return parsed


def _env_bool(name: str, default: bool, overrides: list[str]) -> bool:
    value = _env_value(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in TRUE_VALUES:
        parsed = True
    elif normalized in FALSE_VALUES:
        parsed = False
    else:
        raise ConfigurationError(
            f"{name} must be one of: true, false, 1, 0, yes, no, on, off"
        )
    overrides.append(name)
    return parsed


def _source_env_name(source_name: str, setting: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", source_name).upper()
    return f"EVIDENCE_SOURCE_{normalized}_{setting}"


def resolve_profile_path(
    studies_root: str | Path,
    study_id: str,
    profile_id: str,
) -> Path:
    """Resolve a stored profile while preventing path traversal."""

    if not IDENTIFIER_PATTERN.fullmatch(study_id):
        raise ConfigurationError(f"Invalid study_id: {study_id}")
    if not IDENTIFIER_PATTERN.fullmatch(profile_id):
        raise ConfigurationError(f"Invalid profile_id: {profile_id}")
    root = Path(studies_root).resolve()
    profile = (root / study_id / "profiles" / profile_id).resolve()
    if root not in profile.parents or not profile.is_dir():
        raise ConfigurationError(f"Profile not found: {study_id}/{profile_id}")
    return profile


def list_study_profiles(studies_root: str | Path) -> list[dict[str, Any]]:
    """List saved study/profile directories, excluding private templates."""

    root = Path(studies_root).resolve()
    if not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for study_path in sorted(root.iterdir()):
        if not study_path.is_dir() or study_path.name.startswith("_"):
            continue
        profiles_path = study_path / "profiles"
        profiles = (
            sorted(
                path.name
                for path in profiles_path.iterdir()
                if path.is_dir() and not path.name.startswith("_")
            )
            if profiles_path.is_dir()
            else []
        )
        if profiles:
            result.append({"study_id": study_path.name, "profiles": profiles})
    return result


def load_study_config(study_dir: str | Path) -> StudyConfig:
    study_path = Path(study_dir)
    data = _read_yaml(study_path / "protocol.yaml")
    search_data = data.get("search") or {}
    date_range = data.get("date_range") or {}
    source_data = data.get("sources") or {}
    overrides: list[str] = []
    if not data.get("study_id"):
        raise ConfigurationError("protocol.yaml must define study_id")
    if not source_data:
        raise ConfigurationError("protocol.yaml must define at least one source")

    profile_id = str(data.get("profile_id") or study_path.name)
    min_year = _env_int(
        "EVIDENCE_MIN_YEAR",
        int(date_range.get("min_year", 2010)),
        overrides,
    )
    max_year = _env_int(
        "EVIDENCE_MAX_YEAR",
        int(date_range.get("max_year", 2026)),
        overrides,
    )
    if min_year > max_year:
        raise ConfigurationError("Effective min_year must not exceed max_year")

    language_override = _env_value("EVIDENCE_SEARCH_LANGUAGE")
    search_language = language_override or str(search_data.get("language") or "en")
    if language_override:
        overrides.append("EVIDENCE_SEARCH_LANGUAGE")
    search_language = search_language.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", search_language):
        raise ConfigurationError("Search language must be a BCP 47-style code such as en or ru")

    include_abstracts = _env_bool(
        "EVIDENCE_INCLUDE_ABSTRACTS",
        bool(search_data.get("include_abstracts", True)),
        overrides,
    )

    sources: dict[str, SourceConfig] = {}
    for name, raw in source_data.items():
        raw = raw or {}
        enabled_env_name = _source_env_name(name, "ENABLED")
        required_env_name = _source_env_name(name, "REQUIRED")
        enabled = _env_bool(
            enabled_env_name,
            bool(raw.get("enabled", True)),
            overrides,
        )
        required = _env_bool(
            required_env_name,
            bool(raw.get("required", False)),
            overrides,
        )
        if not enabled and _env_value(required_env_name) is None:
            required = False
        if required and not enabled:
            raise ConfigurationError(
                f"Source {name!r} cannot be required while it is disabled"
            )
        options = dict(raw.get("options") or {})
        if name == "scopus":
            view = (_env_value("SCOPUS_SEARCH_VIEW") or options.get("view", "STANDARD")).upper()
            if view not in {"STANDARD", "COMPLETE"}:
                raise ConfigurationError("SCOPUS_SEARCH_VIEW must be STANDARD or COMPLETE")
            options["view"] = view
            options["insttoken_env"] = "ELSEVIER_INSTTOKEN"
            if _env_value("SCOPUS_SEARCH_VIEW"):
                overrides.append("SCOPUS_SEARCH_VIEW")
        options["min_date"] = f"{min_year:04d}-01-01"
        options["max_date"] = f"{max_year:04d}-12-31"
        options["year"] = f"{min_year}-{max_year}"
        sources[name] = SourceConfig(
            name=name,
            enabled=enabled,
            required=required,
            api_key_env=raw.get("api_key_env"),
            timeout_seconds=float(raw.get("timeout_seconds", 30)),
            max_retries=int(raw.get("max_retries", 2)),
            backoff_seconds=float(raw.get("backoff_seconds", 1)),
            include_abstracts=include_abstracts,
            options=options,
        )

    return StudyConfig(
        study_id=str(data["study_id"]),
        profile_id=profile_id,
        min_year=min_year,
        max_year=max_year,
        search_language=search_language,
        include_abstracts=include_abstracts,
        sources=sources,
        contact_email_env=str(data.get("contact_email_env", "RESEARCH_CONTACT_EMAIL")),
        env_overrides=tuple(overrides),
    )


def load_database_queries(
    study_dir: str | Path,
    *,
    language: str | None = None,
) -> list[SearchQuery]:
    path = Path(study_dir) / "queries" / "database.yaml"
    data = _read_yaml(path)
    queries: list[SearchQuery] = []
    for item in data.get("queries") or []:
        query_id = str(item.get("id") or "").strip()
        source_map = item.get("sources") or {}
        if not query_id or not isinstance(source_map, dict):
            raise ConfigurationError(f"Invalid query entry in {path}: {item!r}")
        query_language = str(item.get("language") or "en").strip().lower()
        if language and query_language != language.lower():
            continue
        for source_name, text in source_map.items():
            if text and str(text).strip():
                queries.append(
                    SearchQuery(
                        query_id=query_id,
                        source_name=str(source_name),
                        text=str(text).strip(),
                    )
                )
    return queries


def load_profile_documents(study_dir: str | Path) -> dict[str, Any]:
    """Load scientific profile documents returned by the management API."""

    root = Path(study_dir)
    return {
        "research_questions": _read_yaml(root / "research_questions.yaml"),
        "concepts": _read_yaml(root / "concepts.yaml"),
        "eligibility_criteria": _read_yaml(root / "eligibility_criteria.yaml"),
    }
