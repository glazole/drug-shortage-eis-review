"""Whole-run corpus summaries and CSV for researcher-led screening."""

from __future__ import annotations

import csv
import io

from .exceptions import ConfigurationError


def run_summary(store, run_id: str) -> dict:
    with store.connect() as con:
        run = con.execute("SELECT * FROM search_runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            raise ConfigurationError("Unknown run_id")
        works = con.execute("""
            SELECT COUNT(*) AS works,
                   SUM(doi IS NOT NULL AND TRIM(doi)<>'') AS with_doi,
                   SUM(abstract IS NOT NULL AND TRIM(abstract)<>'') AS with_abstract
            FROM works WHERE work_id IN (SELECT work_id FROM discoveries WHERE run_id=?)
        """, (run_id,)).fetchone()
        sources = [dict(r) for r in con.execute("""
            SELECT source_name, COUNT(*) AS discovery_events, COUNT(DISTINCT work_id) AS unique_works
            FROM discoveries WHERE run_id=? GROUP BY source_name ORDER BY source_name
        """, (run_id,))]
        reports = [dict(r) for r in con.execute("""
            SELECT source_name, query_id, status, retrieved_count, message,
                   requested_limit, total_results, possibly_truncated
            FROM source_runs WHERE run_id=? ORDER BY source_run_id
        """, (run_id,))]
    return {"run_id": run_id, "study_id": run["study_id"], "profile_id": run["profile_id"],
            "status": run["status"], "works": works["works"],
            "with_doi": works["with_doi"] or 0, "with_abstract": works["with_abstract"] or 0,
            "without_abstract": works["works"] - (works["with_abstract"] or 0),
            "sources": sources, "source_runs": reports,
            "possibly_truncated": any(r["possibly_truncated"] for r in reports)}


def spreadsheet_safe(value):
    # Retrieved titles/abstracts are untrusted: prevent Excel formula execution.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_corpus_csv(store, run_id: str) -> str:
    """Export ALL works for a run; automatic exclusions never hide candidates."""
    with store.connect() as con:
        run = con.execute("SELECT * FROM search_runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            raise ConfigurationError("Unknown run_id")
        version = con.execute("""
            SELECT rule_version FROM automatic_relevance WHERE run_id=?
            ORDER BY assessed_at DESC LIMIT 1
        """, (run_id,)).fetchone()
        reviewer = (f"system:{run['study_id']}:{run['profile_id']}:{run_id}:{version[0]}"
                    if version else "")
        rows = con.execute("""
            SELECT * FROM works WHERE work_id IN (
                SELECT work_id FROM discoveries WHERE run_id=?
            ) ORDER BY normalized_title, work_id
        """, (run_id,)).fetchall()
        output = io.StringIO(newline="")
        output.write("\ufeff")
        writer = csv.writer(output)
        writer.writerow([
            "run_id", "work_id", "year", "title", "doi", "url", "venue", "authors_json",
            "abstract", "abstract_status", "abstract_source", "abstract_method",
            "abstract_source_url", "abstract_retrieved_at", "discovery_sources", "query_ids",
            "automatic_decision", "automatic_rule_version", "automatic_details_json",
            "manual_decision", "manual_reason_code", "screening_note", "reviewer", "screened_at",
        ])
        for row in rows:
            provenance = con.execute("""
                SELECT * FROM work_abstracts WHERE work_id=? AND abstract_text=?
                ORDER BY retrieved_at DESC, abstract_id DESC LIMIT 1
            """, (row["work_id"], row["abstract"])).fetchone()
            paths = con.execute("""
                SELECT DISTINCT source_name, query_id FROM discoveries
                WHERE run_id=? AND work_id=? ORDER BY source_name, query_id
            """, (run_id, row["work_id"])).fetchall()
            auto = con.execute("""
                SELECT * FROM screening_decisions
                WHERE work_id=? AND stage='automatic_relevance' AND reviewer_id=?
            """, (row["work_id"], reviewer)).fetchone()
            manual = con.execute("""
                SELECT * FROM screening_decisions WHERE work_id=? AND stage='title_abstract'
                ORDER BY decided_at DESC, decision_id DESC LIMIT 1
            """, (row["work_id"],)).fetchone()
            has_abstract = bool((row["abstract"] or "").strip())
            values = [
                run_id, row["work_id"], row["publication_year"], row["title"], row["doi"],
                row["url"], row["venue"], row["authors_json"], row["abstract"],
                "available" if has_abstract else "missing",
                provenance["source_name"] if provenance else "legacy_unknown" if has_abstract else "",
                provenance["method"] if provenance else "",
                provenance["source_url"] if provenance else "",
                provenance["retrieved_at"] if provenance else "",
                ",".join(sorted({r["source_name"] for r in paths})),
                ",".join(sorted({r["query_id"] for r in paths})),
                auto["decision"] if auto else "", version[0] if version else "",
                auto["note"] if auto else "",
            ]
            values += [manual[key] if manual else "" for key in
                       ["decision", "reason_code", "note", "reviewer_id", "decided_at"]]
            writer.writerow([spreadsheet_safe(value) for value in values])
    return output.getvalue()
