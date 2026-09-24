"""Canonical records shared by all discovery strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryMethod(StrEnum):
    DATABASE = "database"
    BACKWARD = "backward"
    FORWARD = "forward"
    AUTHOR = "author"
    MANUAL = "manual"


class SourceStatus(StrEnum):
    DISABLED = "disabled"
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(slots=True)
class WorkRecord:
    title: str
    abstract: str | None = None
    year: int | None = None
    doi: str | None = None
    authors: tuple[str, ...] = ()
    venue: str | None = None
    url: str | None = None
    source_record_id: str | None = None
    external_ids: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SearchQuery:
    query_id: str
    source_name: str
    text: str


@dataclass(slots=True, frozen=True)
class CitationSeed:
    work_id: str
    source_identifier: str


@dataclass(slots=True, frozen=True)
class AuthorSeed:
    work_id: str
    author_identifier: str


@dataclass(slots=True)
class DiscoveryEvent:
    run_id: str
    source_name: str
    method: DiscoveryMethod
    query_id: str | None = None
    query_text: str | None = None
    parent_work_id: str | None = None
    iteration: int = 0
    discovered_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class DiscoveredWork:
    record: WorkRecord
    event: DiscoveryEvent


@dataclass(slots=True)
class SourceRunReport:
    run_id: str
    source_name: str
    status: SourceStatus
    method: DiscoveryMethod
    retrieved_count: int = 0
    query_id: str | None = None
    message: str | None = None
    started_at: str = field(default_factory=utc_now_iso)
    completed_at: str = field(default_factory=utc_now_iso)
