"""Exact-DOI abstract enrichment with durable provenance and failure accounting."""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from .config import _env_bool, _read_yaml
from .exceptions import ConfigurationError, HttpStatusError, SourceUnavailableError
from .models import utc_now_iso
from .normalization import clean_markup, normalize_doi

LOGGER = logging.getLogger(__name__)
PROVIDERS = {"scopus", "openalex", "pubmed", "crossref"}
EMPTY_ABSTRACTS = {"no abstract available", "abstract not available", "no abstract provided", "n/a"}


def load_enrichment_config(profile: str | Path) -> dict:
    raw = _read_yaml(Path(profile) / "protocol.yaml").get("abstract_enrichment") or {}
    sources = raw.get("sources", ["scopus", "openalex", "pubmed", "crossref"])
    if not isinstance(sources, list) or not sources or any(s not in PROVIDERS for s in sources):
        raise ConfigurationError("abstract_enrichment.sources contains an unsupported provider")
    interval = float(raw.get("request_interval_seconds", 0.4))
    if interval < 0:
        raise ConfigurationError("abstract_enrichment.request_interval_seconds must be nonnegative")
    return {
        "enabled": _env_bool("EVIDENCE_ENRICH_ABSTRACTS", bool(raw.get("enabled", True)), []),
        "sources": list(dict.fromkeys(sources)), "request_interval_seconds": interval,
    }


def http_status(exc: Exception) -> int | None:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, HttpStatusError):
            return exc.status_code
        exc = exc.__cause__
    return None


def enrich_run(store, *, run_id: str, registry: dict, config: dict,
               max_works: int | None = None, discovery_source: str | None = None,
               sleep=time.sleep) -> dict:
    """Only fill missing abstracts. Lookup providers never become discovery sources."""
    if not config["enabled"]:
        return {"enabled": False}
    if max_works is not None and max_works < 1:
        raise ConfigurationError("max_works must be positive")
    with store.connect() as con:
        if not con.execute("SELECT 1 FROM search_runs WHERE run_id=?", (run_id,)).fetchone():
            raise ConfigurationError("Unknown run_id")
        rows = con.execute("""
            SELECT DISTINCT w.work_id, w.doi
            FROM works w JOIN discoveries d USING(work_id)
            WHERE d.run_id=? AND (w.abstract IS NULL OR TRIM(w.abstract)='')
              AND (? IS NULL OR d.source_name=?)
            ORDER BY w.work_id
        """, (run_id, discovery_source, discovery_source)).fetchall()
    missing_before = len(rows)
    if max_works is not None:
        rows = rows[:max_works]
    enrichment_id = "abstracts_" + uuid.uuid4().hex
    with store.connect() as con:
        con.execute("INSERT INTO enrichment_runs VALUES (?, ?, 'running', ?, ?, NULL)", (
            enrichment_id, run_id, json.dumps(config | {"max_works": max_works,
            "discovery_source": discovery_source}), utc_now_iso()))
    counts = {"enriched": 0, "without_doi": 0, "unresolved": 0}
    statuses: dict[str, dict[str, int]] = {}
    blocked: dict[str, str] = {}
    try:
        for number, row in enumerate(rows, 1):
            work_id, doi = row["work_id"], normalize_doi(row["doi"])
            if not doi:
                counts["without_doi"] += 1
                counts["unresolved"] += 1
                continue
            found = False
            for name in config["sources"]:
                adapter = registry.get(name)
                url = adapter.doi_lookup_url(doi) if adapter else ""
                message = None
                record = None
                abstract = None
                if adapter is None:
                    status = "disabled"
                elif name in blocked:
                    status, message = "skipped_unavailable", blocked[name]
                else:
                    sleep(config["request_interval_seconds"])
                    try:
                        record = adapter.lookup_doi(doi)
                        if record is None:
                            status = "not_found"
                        elif normalize_doi(record.doi) != doi:
                            status = "doi_mismatch"
                        else:
                            abstract = clean_markup(record.abstract)
                            if abstract and abstract.casefold().strip("[] .") in EMPTY_ABSTRACTS:
                                abstract = None
                            status = "found" if abstract else "no_abstract"
                    except Exception as exc:
                        code = http_status(exc)
                        status = "not_found" if code == 404 else "failed"
                        # Raw transport/HTTP messages may embed API keys; do not persist them.
                        message = f"{type(exc).__name__}" + (f" HTTP {code}" if code else "")
                        if code in {401, 403, 429} or isinstance(exc, SourceUnavailableError):
                            blocked[name] = message
                statuses.setdefault(name, {})[status] = statuses.get(name, {}).get(status, 0) + 1
                with store.connect() as con:
                    con.execute("""
                        INSERT INTO abstract_lookup_attempts(
                            enrichment_id, work_id, doi, source_name, status, source_url, message, attempted_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (enrichment_id, work_id, doi, name, status, url, message, utc_now_iso()))
                    if status == "found":
                        store.record_abstract(con, work_id=work_id, abstract=abstract, source=name,
                                              method="doi_lookup", source_url=url, run_id=run_id)
                        cursor = con.execute("""
                            UPDATE works SET abstract=?, updated_at=?
                            WHERE work_id=? AND (abstract IS NULL OR TRIM(abstract)='')
                        """, (abstract, utc_now_iso(), work_id))
                        if cursor.rowcount:
                            counts["enriched"] += 1
                        found = True
                        break
            if not found:
                counts["unresolved"] += 1
            if number % 25 == 0:
                LOGGER.info("Abstract enrichment %s: %s/%s works; %s enriched",
                            enrichment_id, number, len(rows), counts["enriched"])
    except BaseException:
        with store.connect() as con:
            con.execute("UPDATE enrichment_runs SET status='failed', completed_at=? WHERE enrichment_id=?",
                        (utc_now_iso(), enrichment_id))
        raise
    with store.connect() as con:
        con.execute("UPDATE enrichment_runs SET status='completed', completed_at=? WHERE enrichment_id=?",
                    (utc_now_iso(), enrichment_id))
    return {"enabled": True, "run_id": run_id, "enrichment_id": enrichment_id,
            "missing_before": missing_before, "attempted_works": len(rows),
            "missing_after": missing_before - counts["enriched"],
            "provider_statuses": statuses, **counts}
