# Drug Shortage EIS Review

Reproducible, modular evidence-search pipeline for research at the intersection of
drug shortages, interorganizational information systems, and enterprise architecture.

The repository is intentionally split into two layers:

- `src/evidence_pipeline`: topic-independent search, provenance, screening, and storage engine;
- `studies/<study_id>/profiles/<profile_id>`: saved, versioned research profiles containing the
  protocol, research questions, concepts, criteria, queries, and seeds.

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
curl http://localhost:8000/v1/studies
```

Start the configured database search:

```bash
curl -X POST http://localhost:8000/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"study_id":"drug_shortage_eis","profile_id":"baseline","limit_per_query":200}'
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

### Runtime overrides in `.env`

The selected YAML profile remains the reproducible scientific protocol. Optional `.env` values
override it only for the current deployment:

```dotenv
EVIDENCE_DEFAULT_STUDY_ID=drug_shortage_eis
EVIDENCE_DEFAULT_PROFILE_ID=baseline

EVIDENCE_MIN_YEAR=2015
EVIDENCE_MAX_YEAR=2026
EVIDENCE_SEARCH_LANGUAGE=en
EVIDENCE_INCLUDE_ABSTRACTS=true

EVIDENCE_SOURCE_PUBMED_ENABLED=true
EVIDENCE_SOURCE_OPENALEX_ENABLED=true
EVIDENCE_SOURCE_CROSSREF_ENABLED=true
EVIDENCE_SOURCE_SEMANTIC_SCHOLAR_ENABLED=false
```

Every override may be left empty to keep the value from `protocol.yaml`. Source `REQUIRED`
overrides are also available in `.env.example`. If an environment override disables a source, it
is treated as non-required unless `..._REQUIRED=true` is explicitly supplied; an explicitly
required and disabled source is rejected as an invalid configuration.

After changing `.env`, recreate the service so Compose passes the new values:

```bash
docker compose up -d
```

The API response includes `env_overrides`. Every search also writes the full effective settings and
completion status to the ledger's `search_runs` table, so a pilot run cannot silently hide which
profile values were changed at runtime.

### Saved research profiles

The included profile is located at:

```text
studies/drug_shortage_eis/profiles/baseline/
```

Create a new variant without overwriting it:

```bash
cp -R \
  studies/drug_shortage_eis/profiles/baseline \
  studies/drug_shortage_eis/profiles/pilot_v2
```

Change `profile_id` in the copied `protocol.yaml`, then select it through
`EVIDENCE_DEFAULT_PROFILE_ID=pilot_v2` or in the `POST /v1/search` body. Because Compose mounts
`./studies` read-only into the container, saved profile files stay on the host, are versioned by
Git, and can be read by the API without rebuilding the image. See `studies/README.md` for the file
contract.

`search.language` selects only query blocks with the same `language` in
`queries/database.yaml`. English (`en`) is the default. This avoids pretending that one query can
be translated mechanically across languages or bibliographic databases.

`search.include_abstracts` controls whether retrieved abstracts are retained in the evidence
ledger. When it is false, abstracts are discarded before persistence; adapters may still receive
abstract metadata when an upstream API does not offer a field-selection option.

## Local CLI quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
evidence-search validate-config \
  --study studies/drug_shortage_eis/profiles/baseline
evidence-search init-db --database data/review.sqlite3
evidence-search search \
  --study studies/drug_shortage_eis/profiles/baseline \
  --database data/review.sqlite3 \
  --limit-per-query 200
```

API keys are read only from environment variables. They are never serialized into run metadata.

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Check the service and initialize/read the ledger |
| `GET` | `/v1/studies` | List saved studies and profiles |
| `GET` | `/v1/studies/{study_id}` | Read the selected/default profile |
| `GET` | `/v1/studies/{study_id}/profiles/{profile_id}` | Read a specific saved profile |
| `GET` | `/v1/ledger/summary` | Return work, discovery, source-run, and search-run counts |
| `POST` | `/v1/search` | Run the configured database-source retrieval |

Profile responses include the effective date range, language, abstract setting, research
questions, concepts, eligibility criteria, sources, and applied environment overrides. They report
whether an API key is configured but never return the key itself. Semantic Scholar remains
disabled in the baseline profile unless explicitly enabled in the profile or `.env`.

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
