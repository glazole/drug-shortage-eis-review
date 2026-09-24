"""Study protocol and source configuration loading."""

from __future__ import annotations

import os
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
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env) if self.api_key_env else None


@dataclass(slots=True)
class StudyConfig:
    study_id: str
    min_year: int
    max_year: int
    sources: dict[str, SourceConfig]
    contact_email_env: str = "RESEARCH_CONTACT_EMAIL"

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


def load_study_config(study_dir: str | Path) -> StudyConfig:
    study_path = Path(study_dir)
    data = _read_yaml(study_path / "protocol.yaml")
    date_range = data.get("date_range") or {}
    source_data = data.get("sources") or {}
    if not data.get("study_id"):
        raise ConfigurationError("protocol.yaml must define study_id")
    if not source_data:
        raise ConfigurationError("protocol.yaml must define at least one source")

    sources: dict[str, SourceConfig] = {}
    for name, raw in source_data.items():
        raw = raw or {}
        sources[name] = SourceConfig(
            name=name,
            enabled=bool(raw.get("enabled", True)),
            required=bool(raw.get("required", False)),
            api_key_env=raw.get("api_key_env"),
            timeout_seconds=float(raw.get("timeout_seconds", 30)),
            max_retries=int(raw.get("max_retries", 2)),
            backoff_seconds=float(raw.get("backoff_seconds", 1)),
            options=dict(raw.get("options") or {}),
        )

    return StudyConfig(
        study_id=str(data["study_id"]),
        min_year=int(date_range.get("min_year", 2010)),
        max_year=int(date_range.get("max_year", 2026)),
        sources=sources,
        contact_email_env=str(data.get("contact_email_env", "RESEARCH_CONTACT_EMAIL")),
    )


def load_database_queries(study_dir: str | Path) -> list[SearchQuery]:
    path = Path(study_dir) / "queries" / "database.yaml"
    data = _read_yaml(path)
    queries: list[SearchQuery] = []
    for item in data.get("queries") or []:
        query_id = str(item.get("id") or "").strip()
        source_map = item.get("sources") or {}
        if not query_id or not isinstance(source_map, dict):
            raise ConfigurationError(f"Invalid query entry in {path}: {item!r}")
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
