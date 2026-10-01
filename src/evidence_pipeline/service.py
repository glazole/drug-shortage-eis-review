"""Application services shared by the CLI and HTTP API."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_database_queries, load_profile_documents, load_study_config
from .discovery import DiscoveryRunner
from .exceptions import ConfigurationError
from .sources import build_source_registry
from .relevance import load_rules, screen_run
from .storage import SQLiteEvidenceStore


def create_run_id() -> str:
    """Return a sortable identifier with enough precision for API requests."""

    return datetime.now(timezone.utc).strftime("search_%Y%m%dT%H%M%S%fZ")


def describe_study(study_dir: str | Path) -> dict[str, Any]:
    """Load and summarize the protocol without exposing API-key values."""

    study = load_study_config(study_dir)
    queries = load_database_queries(study_dir, language=study.search_language)
    if not queries:
        raise ConfigurationError(
            f"Profile {study.study_id}/{study.profile_id} has no queries "
            f"for language {study.search_language!r}"
        )
    documents = load_profile_documents(study_dir)
    return {
        "study_id": study.study_id,
        "profile_id": study.profile_id,
        "date_range": {
            "min_year": study.min_year,
            "max_year": study.max_year,
        },
        "search_language": study.search_language,
        "include_abstracts": study.include_abstracts,
        "sources": {
            name: {
                "enabled": config.enabled,
                "required": config.required,
                "api_key_configured": bool(config.api_key),
            }
            for name, config in study.sources.items()
        },
        "query_variants": len(queries),
        "env_overrides": list(study.env_overrides),
        "automatic_relevance": load_rules(study_dir),
        **documents,
    }


def initialize_database(database_path: str | Path) -> dict[str, int]:
    """Create the evidence-ledger schema if necessary and return its summary."""

    store = SQLiteEvidenceStore(database_path)
    store.initialize()
    return store.summary()


def run_database_search(
    *,
    study_dir: str | Path,
    database_path: str | Path,
    limit_per_query: int = 200,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Execute configured database searches and persist records and provenance."""

    study = load_study_config(study_dir)
    queries = load_database_queries(study_dir, language=study.search_language)
    if not queries:
        raise ConfigurationError(
            f"Profile {study.study_id}/{study.profile_id} has no queries "
            f"for language {study.search_language!r}"
        )
    store = SQLiteEvidenceStore(database_path)
    store.initialize()

    registry = build_source_registry(study)
    relevance_rules = load_rules(study_dir)
    runner = DiscoveryRunner(
        registry,
        study.sources,
        min_year=study.min_year,
        max_year=study.max_year,
        include_abstracts=study.include_abstracts,
    )
    effective_run_id = run_id or create_run_id()
    store.start_search_run(
        run_id=effective_run_id,
        study_id=study.study_id,
        profile_id=study.profile_id,
        effective_config={
            "date_range": {"min_year": study.min_year, "max_year": study.max_year},
            "search_language": study.search_language,
            "include_abstracts": study.include_abstracts,
            "sources": {
                name: {"enabled": config.enabled, "required": config.required,
                       "search_view": config.options.get("view")}
                for name, config in study.sources.items()
            },
            "env_overrides": list(study.env_overrides),
            "automatic_relevance": relevance_rules,
        },
    )
    try:
        discovered, reports = runner.search(
            run_id=effective_run_id,
            queries=queries,
            limit_per_query=limit_per_query,
        )
        unique_works, discoveries = store.ingest(discovered)
        store.write_source_reports(reports)
        relevance = screen_run(store, run_id=effective_run_id, study_id=study.study_id,
                               profile_id=study.profile_id, rules=relevance_rules)
    except Exception:
        store.complete_search_run(effective_run_id, status="failed")
        raise
    store.complete_search_run(effective_run_id, status="completed")
    return {
        "run_id": effective_run_id,
        "study_id": study.study_id,
        "profile_id": study.profile_id,
        "search_language": study.search_language,
        "include_abstracts": study.include_abstracts,
        "date_range": {"min_year": study.min_year, "max_year": study.max_year},
        "retrieved_records": len(discovered),
        "unique_works_in_batch": unique_works,
        "new_discovery_events": discoveries,
        "automatic_relevance": relevance,
        "source_statuses": [
            {
                "source": report.source_name,
                "query_id": report.query_id,
                "status": report.status.value,
                "count": report.retrieved_count,
                "message": report.message,
            }
            for report in reports
        ],
        "ledger": store.summary(),
    }
