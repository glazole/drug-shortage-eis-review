# Drug Shortage EIS Review

Reproducible, modular evidence-search pipeline for research at the intersection of
drug shortages, interorganizational information systems, and enterprise architecture.

The repository is intentionally split into two layers:

- `src/evidence_pipeline`: topic-independent search, provenance, screening, and storage engine;
- `studies/drug_shortage_eis`: study-specific protocol, queries, criteria, and seeds.

This is a research tool, not an automatic systematic-review generator. Automated retrieval,
normalization, and deduplication are kept separate from scientific title/abstract screening,
full-text assessment, quality appraisal, and synthesis.

## Design principles

1. Every database or API is an optional source adapter.
2. A scientific work is stored once, but every discovery path is retained.
3. Database search, backward citation search, forward citation search, and author expansion
   produce the same canonical `WorkRecord` and `DiscoveryEvent` objects.
4. A disabled source is recorded as `disabled`; a transiently inaccessible optional source is
   recorded as `unavailable`; neither is silently treated as an empty result.
5. If a source is marked `required: true`, its failure stops the run to prevent an incomplete
   search from being mistaken for a complete one.

## Semantic Scholar failure behaviour

Semantic Scholar can be disabled in `protocol.yaml`:

```yaml
semantic_scholar:
  enabled: false
  required: false
```

When enabled but unavailable because of timeout, HTTP 429, or HTTP 5xx, the adapter retries
according to its configuration. If all retries fail and `required: false`, the pipeline continues
with other sources and writes an `unavailable` source-run event. Permanent request errors are
recorded as `failed`.

## Docker Compose quick start

Docker Compose starts the FastAPI service, persists the SQLite evidence ledger in a named volume,
and reads source credentials from the local `.env` file. The `.env` file is excluded from both Git
and the Docker build context.

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

After the health check becomes healthy:

- API root: <http://localhost:8000/>;
- Swagger UI: <http://localhost:8000/docs>;
- health check: <http://localhost:8000/health>.

If `API_PORT` is changed in `.env`, use that host port instead of `8000`.

Validate the study protocol through the API:

```bash
curl http://localhost:8000/v1/studies/drug_shortage_eis
```

Start the configured database search:

```bash
curl -X POST http://localhost:8000/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"study_id":"drug_shortage_eis","limit_per_query":200}'
```

The initial API deliberately permits only one search at a time in a container. A concurrent search
returns HTTP `409`, which prevents accidental duplicate retrieval and unnecessary pressure on
external scholarly APIs. Long-running asynchronous jobs are outside this first API milestone.

Operational commands:

```bash
docker compose logs -f evidence-api
docker compose restart evidence-api
docker compose down
```

`docker compose down` keeps the `evidence-data` volume. Use `docker compose down -v` only when the
ledger should be permanently deleted.

## Local CLI quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
evidence-search validate-config --study studies/drug_shortage_eis
evidence-search init-db --database data/review.sqlite3
evidence-search search \
  --study studies/drug_shortage_eis \
  --database data/review.sqlite3 \
  --limit-per-query 200
```

API keys are read only from environment variables. They are never serialized into run metadata.

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Check the service and initialize/read the ledger |
| `GET` | `/v1/studies/{study_id}` | Validate and summarize a study protocol |
| `GET` | `/v1/ledger/summary` | Return current ledger counts |
| `POST` | `/v1/search` | Run the configured database-source retrieval |

The study response reports whether an API key is configured, but never returns the key itself.
Semantic Scholar remains disabled by default and can be enabled only through the study protocol.

## Current milestone

The first milestone provides:

- canonical work and discovery models;
- configurable OpenAlex, PubMed, Crossref, Scopus, ScienceDirect, and Semantic Scholar adapters;
- graceful degradation for optional sources;
- backward/forward citation and author-expansion capabilities where the source supports them;
- a SQLite evidence ledger preserving multiple discovery paths;
- a FastAPI delivery layer with Docker Compose startup and persistent ledger storage;
- a draft study protocol and source-specific pilot queries;
- tests for the HTTP API, service layer, source failure handling, DOI normalization, and
  provenance preservation.

The next milestone will add reviewer-oriented screening import/export, explicit exclusion-reason
codes, query recall tests against the legacy thesis corpus, and PRISMA 2020/PRISMA-S reporting.
