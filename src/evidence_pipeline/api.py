"""FastAPI entrypoint for the evidence-search service."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from .config import IDENTIFIER_PATTERN, list_study_profiles, resolve_profile_path
from .exceptions import ConfigurationError, EvidencePipelineError, SourceUnavailableError
from .service import describe_study, initialize_database, run_database_search
from .relevance import load_rules, screen_run
from .storage import SQLiteEvidenceStore


_search_lock = Lock()


def _studies_root() -> Path:
    return Path(os.getenv("EVIDENCE_STUDIES_ROOT", "studies")).resolve()


def _database_path() -> Path:
    return Path(os.getenv("EVIDENCE_DATABASE_PATH", "data/review.sqlite3")).resolve()


def _default_study_id() -> str:
    return os.getenv("EVIDENCE_DEFAULT_STUDY_ID", "drug_shortage_eis")


def _default_profile_id() -> str:
    return os.getenv("EVIDENCE_DEFAULT_PROFILE_ID", "baseline")


def _resolve_profile(study_id: str, profile_id: str) -> Path:
    if not IDENTIFIER_PATTERN.fullmatch(study_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="study_id may contain only letters, digits, underscores, and hyphens",
        )
    if not IDENTIFIER_PATTERN.fullmatch(profile_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="profile_id may contain only letters, digits, underscores, and hyphens",
        )
    try:
        return resolve_profile_path(_studies_root(), study_id, profile_id)
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


class SearchRequest(BaseModel):
    study_id: str = Field(default_factory=_default_study_id, pattern=IDENTIFIER_PATTERN.pattern)
    profile_id: str = Field(
        default_factory=_default_profile_id,
        pattern=IDENTIFIER_PATTERN.pattern,
    )
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    limit_per_query: int = Field(default=200, ge=1, le=1000)


class LedgerSummary(BaseModel):
    works: int
    discoveries: int
    source_runs: int
    search_runs: int


class SourceStatusResult(BaseModel):
    source: str
    query_id: str | None
    status: str
    count: int
    message: str | None


class DateRangeResult(BaseModel):
    min_year: int
    max_year: int


class SearchResponse(BaseModel):
    run_id: str
    study_id: str
    profile_id: str
    search_language: str
    include_abstracts: bool
    date_range: DateRangeResult
    retrieved_records: int
    unique_works_in_batch: int
    new_discovery_events: int
    source_statuses: list[SourceStatusResult]
    ledger: LedgerSummary
    automatic_relevance: dict[str, Any] = Field(default_factory=dict)


class ScreeningRequest(BaseModel):
    study_id: str = Field(default_factory=_default_study_id, pattern=IDENTIFIER_PATTERN.pattern)
    profile_id: str = Field(default_factory=_default_profile_id, pattern=IDENTIFIER_PATTERN.pattern)
    run_id: str = Field(min_length=1, max_length=128)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database(_database_path())
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Modular Evidence Search API",
        version="0.2.0",
        description=(
            "HTTP interface for protocol validation, evidence-ledger inspection, "
            "and reproducible database searches."
        ),
        lifespan=lifespan,
    )

    @application.get("/", tags=["service"])
    def root() -> dict[str, str]:
        return {
            "service": "drug-shortage-eis-evidence-api",
            "docs": "/docs",
            "health": "/health",
            "studies": "/v1/studies",
        }

    @application.get("/health", tags=["service"])
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "ledger": initialize_database(_database_path()),
        }

    @application.get("/v1/studies", tags=["studies"])
    def get_studies() -> dict[str, Any]:
        return {
            "default_study_id": _default_study_id(),
            "default_profile_id": _default_profile_id(),
            "studies": list_study_profiles(_studies_root()),
        }

    @application.get("/v1/studies/{study_id}", tags=["studies"])
    def get_study(study_id: str, profile_id: str | None = None) -> dict[str, Any]:
        try:
            return describe_study(
                _resolve_profile(study_id, profile_id or _default_profile_id())
            )
        except ConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @application.get(
        "/v1/studies/{study_id}/profiles/{profile_id}",
        tags=["studies"],
    )
    def get_profile(study_id: str, profile_id: str) -> dict[str, Any]:
        try:
            return describe_study(_resolve_profile(study_id, profile_id))
        except ConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @application.get(
        "/v1/ledger/summary",
        response_model=LedgerSummary,
        tags=["ledger"],
    )
    def ledger_summary() -> dict[str, int]:
        return initialize_database(_database_path())

    @application.post(
        "/v1/search",
        response_model=SearchResponse,
        tags=["search"],
    )
    def search(request: SearchRequest) -> dict[str, Any]:
        if not _search_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Another search is already running",
            )
        try:
            return run_database_search(
                study_dir=_resolve_profile(request.study_id, request.profile_id),
                database_path=_database_path(),
                limit_per_query=request.limit_per_query,
                run_id=request.run_id,
            )
        except ConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        except SourceUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        except EvidencePipelineError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        finally:
            _search_lock.release()

    @application.post("/v1/screening/automatic", tags=["ledger"])
    def automatic_screening(request: ScreeningRequest) -> dict[str, Any]:
        if not _search_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Another search or screening is running")
        try:
            profile = _resolve_profile(request.study_id, request.profile_id)
            store = SQLiteEvidenceStore(_database_path())
            store.initialize()
            return screen_run(store, run_id=request.run_id, study_id=request.study_id,
                              profile_id=request.profile_id, rules=load_rules(profile))
        except ConfigurationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            _search_lock.release()

    return application


app = create_app()
