"""SQLite evidence ledger preserving record-level provenance."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from ..models import DiscoveredWork, SourceRunReport, WorkRecord, utc_now_iso
from ..normalization import candidate_work_id, normalize_doi, normalize_title


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS works (
    work_id TEXT PRIMARY KEY,
    doi TEXT,
    normalized_title TEXT NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT,
    publication_year INTEGER,
    authors_json TEXT NOT NULL,
    venue TEXT,
    url TEXT,
    identifiers_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_works_doi
ON works(doi) WHERE doi IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_works_title_year
ON works(normalized_title, publication_year);

CREATE TABLE IF NOT EXISTS search_runs (
    run_id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    status TEXT NOT NULL,
    effective_config_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS discoveries (
    discovery_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    work_id TEXT NOT NULL REFERENCES works(work_id),
    source_name TEXT NOT NULL,
    method TEXT NOT NULL,
    query_id TEXT NOT NULL DEFAULT '',
    query_text TEXT,
    parent_work_id TEXT NOT NULL DEFAULT '',
    iteration INTEGER NOT NULL DEFAULT 0,
    discovered_at TEXT NOT NULL,
    UNIQUE(run_id, work_id, source_name, method, query_id, parent_work_id, iteration)
);

CREATE TABLE IF NOT EXISTS source_runs (
    source_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL,
    method TEXT NOT NULL,
    query_id TEXT NOT NULL DEFAULT '',
    retrieved_count INTEGER NOT NULL,
    message TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screening_decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id TEXT NOT NULL REFERENCES works(work_id),
    stage TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason_code TEXT,
    note TEXT,
    reviewer_id TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    UNIQUE(work_id, stage, reviewer_id)
);

CREATE TABLE IF NOT EXISTS automatic_relevance (
    run_id TEXT NOT NULL REFERENCES search_runs(run_id),
    work_id TEXT NOT NULL REFERENCES works(work_id),
    query_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    study_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    details_json TEXT NOT NULL,
    assessed_at TEXT NOT NULL,
    PRIMARY KEY(run_id, work_id, query_id, rule_version)
);
"""


class SQLiteEvidenceStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def start_search_run(
        self,
        *,
        run_id: str,
        study_id: str,
        profile_id: str,
        effective_config: dict,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO search_runs(
                    run_id, study_id, profile_id, status,
                    effective_config_json, started_at, completed_at
                ) VALUES (?, ?, ?, 'running', ?, ?, NULL)
                """,
                (
                    run_id,
                    study_id,
                    profile_id,
                    json.dumps(effective_config, ensure_ascii=False, sort_keys=True),
                    utc_now_iso(),
                ),
            )

    def complete_search_run(self, run_id: str, *, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE search_runs
                   SET status = ?, completed_at = ?
                 WHERE run_id = ?
                """,
                (status, utc_now_iso(), run_id),
            )

    @staticmethod
    def _find_existing(connection: sqlite3.Connection, record: WorkRecord) -> sqlite3.Row | None:
        doi = normalize_doi(record.doi)
        if doi:
            row = connection.execute("SELECT * FROM works WHERE doi = ?", (doi,)).fetchone()
            if row:
                return row
        return connection.execute(
            """
            SELECT * FROM works
            WHERE normalized_title = ?
              AND (publication_year = ? OR publication_year IS NULL OR ? IS NULL)
            ORDER BY publication_year IS NULL, created_at
            LIMIT 1
            """,
            (normalize_title(record.title), record.year, record.year),
        ).fetchone()

    @staticmethod
    def _prefer_text(old: str | None, new: str | None) -> str | None:
        if not old:
            return new
        if not new:
            return old
        return new if len(new) > len(old) else old

    def upsert_work(self, connection: sqlite3.Connection, record: WorkRecord) -> str:
        existing = self._find_existing(connection, record)
        doi = normalize_doi(record.doi)
        now = utc_now_iso()
        if existing:
            work_id = str(existing["work_id"])
            old_authors = tuple(json.loads(existing["authors_json"]))
            authors = tuple(dict.fromkeys(old_authors + tuple(record.authors)))
            identifiers = json.loads(existing["identifiers_json"])
            identifiers.update(record.external_ids)
            connection.execute(
                """
                UPDATE works
                   SET doi = COALESCE(doi, ?),
                       title = ?,
                       normalized_title = ?,
                       abstract = ?,
                       publication_year = COALESCE(publication_year, ?),
                       authors_json = ?,
                       venue = COALESCE(venue, ?),
                       url = COALESCE(url, ?),
                       identifiers_json = ?,
                       updated_at = ?
                 WHERE work_id = ?
                """,
                (
                    doi,
                    self._prefer_text(existing["title"], record.title),
                    normalize_title(record.title or existing["title"]),
                    self._prefer_text(existing["abstract"], record.abstract),
                    record.year,
                    json.dumps(authors, ensure_ascii=False),
                    record.venue,
                    record.url,
                    json.dumps(identifiers, ensure_ascii=False, sort_keys=True),
                    now,
                    work_id,
                ),
            )
            return work_id

        work_id = candidate_work_id(record.title, record.year, doi)
        connection.execute(
            """
            INSERT INTO works(
                work_id, doi, normalized_title, title, abstract, publication_year,
                authors_json, venue, url, identifiers_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                work_id,
                doi,
                normalize_title(record.title),
                record.title,
                record.abstract,
                record.year,
                json.dumps(record.authors, ensure_ascii=False),
                record.venue,
                record.url,
                json.dumps(record.external_ids, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        return work_id

    def ingest(self, discovered: list[DiscoveredWork]) -> tuple[int, int]:
        work_ids: set[str] = set()
        discovery_count = 0
        with self.connect() as connection:
            for item in discovered:
                work_id = self.upsert_work(connection, item.record)
                work_ids.add(work_id)
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO discoveries(
                        run_id, work_id, source_name, method, query_id, query_text,
                        parent_work_id, iteration, discovered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.event.run_id,
                        work_id,
                        item.event.source_name,
                        item.event.method.value,
                        item.event.query_id or "",
                        item.event.query_text,
                        item.event.parent_work_id or "",
                        item.event.iteration,
                        item.event.discovered_at,
                    ),
                )
                discovery_count += max(cursor.rowcount, 0)
        return len(work_ids), discovery_count

    def write_source_reports(self, reports: list[SourceRunReport]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO source_runs(
                    run_id, source_name, status, method, query_id, retrieved_count,
                    message, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        report.run_id,
                        report.source_name,
                        report.status.value,
                        report.method.value,
                        report.query_id or "",
                        report.retrieved_count,
                        report.message,
                        report.started_at,
                        report.completed_at,
                    )
                    for report in reports
                ],
            )

    def summary(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                "works": connection.execute("SELECT COUNT(*) FROM works").fetchone()[0],
                "discoveries": connection.execute(
                    "SELECT COUNT(*) FROM discoveries"
                ).fetchone()[0],
                "source_runs": connection.execute("SELECT COUNT(*) FROM source_runs").fetchone()[0],
                "search_runs": connection.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0],
            }
