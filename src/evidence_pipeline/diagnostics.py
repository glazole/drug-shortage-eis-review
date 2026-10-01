"""Small credential-safe live probes; never modify the evidence ledger."""

from dataclasses import replace

from .enrichment import http_status
from .exceptions import ConfigurationError
from .normalization import normalize_doi
from .sources.elsevier import ScopusAdapter


def probe_scopus(study, doi: str) -> dict:
    doi = normalize_doi(doi)
    if not doi or '"' in doi or any(ch.isspace() for ch in doi):
        raise ConfigurationError("Provide one DOI without whitespace or quotes")
    config = study.sources.get("scopus")
    if config is None:
        raise ConfigurationError("Profile has no Scopus configuration")
    results = []
    for view in ["STANDARD", "COMPLETE", "META_ABS"]:
        adapter = ScopusAdapter(replace(config, options=config.options | {"view": view}),
                                contact_email=study.contact_email)
        try:
            if view == "META_ABS":
                record = adapter.lookup_doi(doi)
                effective_view = view
            else:
                records = adapter.search(f'DOI("{doi}")', limit=1)
                record = records[0] if records else None
                effective_view = adapter.last_search_view
            matched = bool(record and normalize_doi(record.doi) == doi)
            results.append({"requested_view": view, "effective_view": effective_view,
                            "status": "found" if matched else "not_found_or_doi_mismatch",
                            "has_abstract": bool(matched and record.abstract),
                            "abstract_characters": len(record.abstract or "") if matched else 0})
        except Exception as exc:
            results.append({"requested_view": view, "status": "failed",
                            "http_status": http_status(exc), "error_type": type(exc).__name__})
    return {"doi": doi, "api_key_configured": bool(config.api_key), "results": results,
            "note": "No records written. COMPLETE may fall back to STANDARD on HTTP 403."}
