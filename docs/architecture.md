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
protocols; the mutable SQLite ledger is mounted at `/app/data` from the Compose-managed
`evidence-data` volume. Credentials are runtime environment variables and are not copied into the
image.

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
