# Architecture decision: modular discovery and evidence ledger

## Context

The legacy thesis project combines retrieval, filtering, semantic analysis, visualization, and
export in one domain-specific class. It also stores a single source/query value on each surviving
record, which cannot represent a work found through multiple databases and snowballing paths.

## Decision

The new project separates:

1. source adapters: API syntax, pagination, response parsing, retries;
2. discovery strategies: database, backward, forward, and author expansion;
3. application services: use cases shared by the CLI and HTTP transports;
4. delivery interfaces: the command-line entrypoint and FastAPI application;
5. canonicalization: DOI/title normalization and record merging;
6. evidence ledger: every discovery path and source-run outcome;
7. scientific review: title/abstract screening, full-text assessment, appraisal, extraction;
8. reporting: PRISMA 2020, PRISMA-S, and citation-search reporting.

The container runs one Uvicorn process. The immutable image contains application code and study
protocols; Compose also mounts the host `./studies` directory read-only at `/app/studies`, so saved
profiles remain Git-versioned host artifacts. The mutable SQLite ledger is mounted at `/app/data`
from the Compose-managed `evidence-data` volume. Credentials are runtime environment variables and
are not copied into the image.

## Study and profile model

A study identifies a research area. A profile identifies a saved, reproducible variant within that
area. The effective configuration is resolved in this order:

1. profile files under `studies/<study_id>/profiles/<profile_id>`;
2. non-empty `EVIDENCE_*` runtime overrides;
3. validation of the effective configuration before search execution.

Research questions, concepts, eligibility criteria, queries, and seeds belong to the profile. They
are never stored only in environment variables because they are scientific artifacts that must be
reviewed, compared, cited, and reproduced. The API returns the names of applied overrides, and the
`search_runs` ledger table stores the full effective runtime configuration and completion status.

Query blocks carry an explicit language code. Selecting a language chooses the corresponding
source-specific query blocks; the system does not mechanically translate query syntax. The
effective date range is passed into adapters where supported and is also enforced before records
are persisted. If abstract retention is disabled, abstracts are removed before ingestion.

## Source availability semantics

| Configuration / event | Result |
|---|---|
| `enabled: false` | Record `disabled`; do not call the API |
| Enabled optional source succeeds | Record `success` and retrieved count |
| Enabled optional source exhausts retries on timeout/429/5xx | Record `unavailable`; continue |
| Enabled optional source receives permanent/request error | Record `failed`; continue |
| `required: true` source fails | Abort the run |

An unavailable source is never recorded as a successful search with zero results. This distinction
is necessary when assessing whether a search was complete enough to support scientific claims.

## Provenance model

`works` stores canonical bibliographic entities. `discoveries` stores many-to-one evidence paths:

- source name;
- discovery method;
- source-specific query ID and exact query text;
- parent seed work for citation or author expansion;
- snowballing iteration;
- retrieval timestamp and run ID.

This structure permits deterministic PRISMA counts without discarding overlap between sources.
