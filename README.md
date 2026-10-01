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

### Run a pilot search

Start with a small pilot before requesting hundreds of records from every enabled source. The
following command requests at most 20 records per source-specific query, assigns an explicit
`run_id`, and saves the response under `artifacts/runs`:

```bash
cd ~/drug-shortage-eis-review

mkdir -p artifacts/runs

RUN_ID="baseline_pilot_$(date -u +%Y%m%dT%H%M%SZ)"

curl --fail-with-body -sS \
  -X POST http://localhost:8000/v1/search \
  -H "Content-Type: application/json" \
  -d "{
    \"study_id\": \"drug_shortage_eis\",
    \"profile_id\": \"baseline\",
    \"run_id\": \"${RUN_ID}\",
    \"limit_per_query\": 20
  }" \
  | tee "artifacts/runs/${RUN_ID}.json"
```

The request is synchronous: `curl` waits until all configured source queries complete or a required
source aborts the run. Watch progress from another terminal:

```bash
docker compose logs -f evidence-api
```

After completion, inspect the ledger counters:

```bash
curl http://localhost:8000/v1/ledger/summary
```

For a full run, use another unique ID such as `baseline_full_<timestamp>` and increase
`limit_per_query`, for example to `200`.

### How often to run the same profile

Technically, the same profile and settings can be run any number of times, but:

- only one search may run at a time; a concurrent request receives HTTP `409`;
- every run must have a unique `run_id`;
- an existing `run_id`, including one belonging to a failed run, must not be reused;
- external scholarly APIs have their own quotas and rate limits;
- each run adds a `search_runs` record, source-run reports, and run-specific discovery events;
- canonical publications in `works` are deduplicated across runs.

Repeatedly running an unchanged profile after a complete successful run is normally unnecessary.
A practical sequence is:

1. `baseline_pilot_01`: retrieve 10–20 records per query and assess query behaviour.
2. If the protocol changes, save it as another profile such as `pilot_v2` instead of overwriting
   `baseline`.
3. `baseline_full_01`: execute the frozen full search.
4. Run again only to recover an unavailable source, evaluate a deliberately changed profile, or
   update the search before publication.

Pilot and final runs may share one SQLite ledger. Their provenance remains distinguishable by
`run_id`, while duplicate works remain canonicalized in `works`.

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

## Automatic relevance checks (pilot)

The baseline profile now defines query-specific anchor groups in `relevance.yaml`.
For Crossref, OpenAlex and Semantic Scholar, every group must match a whole word
or phrase in the normalized title + abstract. Unicode, markup and hyphens are
normalized; plural terms are explicit. PubMed and Scopus retain their native
Boolean-query candidates for manual screening (`SOURCE_QUERY_ANCHORED`).

All retrieved works and discovery events remain in the ledger. The new
`automatic_relevance` table records each run/work/query assessment, rule hash,
full rules, matched terms, missing anchors and the evidence used. New searches
return an `automatic_relevance` summary. `include` means advance to manual
screening, not final inclusion. If no abstract exists and the title does not
satisfy all groups, the result is `review`, never automatic exclusion.

A work advances if **any** query passes; otherwise it needs review if any query
has insufficient evidence; only failure of all evaluated queries yields
`exclude`. Run/profile-scoped system decisions are stored in
`screening_decisions`; human decisions are preserved. Repeating assessment with
unchanged rules updates the same assessment; changed rules get a new hash.
Assessments use the currently merged work metadata, which may have been enriched
by subsequent searches. Evidence snapshots make that input explicit.

These are draft lexical heuristics. Validate recall against known relevant papers
and manually audit exclusions before using counts in the final review. Filtering
candidates does not repair recall lost through broad ranked API searches; do not
increase the pilot limit or claim a complete corpus on this basis alone.

### Update the service and assess the existing pilot

After merging the changes:

```bash
cd ~/drug-shortage-eis-review
git pull --ff-only
docker compose up -d --build evidence-api
```

The existing `evidence-data` volume is reused; schema initialization adds a table.
Use the exact `run_id` in your pilot JSON (or list runs with the command below):

```bash
docker compose exec -T evidence-api python - <<'PY'
import sqlite3
with sqlite3.connect('file:/app/data/review.sqlite3?mode=ro', uri=True) as con:
    for row in con.execute('SELECT run_id, study_id, profile_id, status FROM search_runs ORDER BY started_at DESC'):
        print(row)
PY
```

```bash
curl --fail-with-body -sS -X POST http://localhost:8000/v1/screening/automatic \
  -H 'Content-Type: application/json' \
  -d '{"study_id":"drug_shortage_eis","profile_id":"baseline","run_id":"REPLACE_WITH_YOUR_PILOT_RUN_ID"}' | jq
```

Inspect decisions and reasons without rerunning searches:

```bash
docker compose exec -T evidence-api python - <<'PY'
import json
import sqlite3
with sqlite3.connect('file:/app/data/review.sqlite3?mode=ro', uri=True) as con:
    for run_id, query, decision, title, details in con.execute('''
        SELECT a.run_id, a.query_id, a.decision, w.title, a.details_json
        FROM automatic_relevance a JOIN works w USING(work_id)
        ORDER BY a.run_id, a.query_id, a.decision, w.title
    '''):
        evidence = json.loads(details)['evidence']
        print(run_id, query, decision, title, evidence['reason_codes'], sep=' | ')
PY
```

### Scopus access and search views

The Scopus adapter previously always requested `COMPLETE`. It now defaults to
`STANDARD`; set `SCOPUS_SEARCH_VIEW=COMPLETE` if your access supports that view.
A COMPLETE request rejected with HTTP 403 retries that page once in STANDARD and
uses STANDARD for subsequent pages. HTTP 401 and invalid-query errors do not
trigger a view fallback. The configured year interval is sent via `date`.

Add these settings to your existing `.env` (do not overwrite the file):

```dotenv
SCOPUS_SEARCH_VIEW=STANDARD
ELSEVIER_INSTTOKEN=
```

Keep your existing `ELSEVIER_API_KEY`. The optional institutional token is sent
as `X-ELS-Insttoken`; it must be issued for the associated API key. A STANDARD
request can still fail without valid Scopus access, recognized institutional
network or the appropriate token. The adapter reports actionable diagnostics for
401/403 and rejects error payloads instead of treating them as zero results.
ScienceDirect remains a separate adapter and access entitlement.

Official references:
- [Scopus Search API: views, institutional token, date](https://dev.elsevier.com/documentation/ScopusSearchAPI.wadl)
- [Elsevier authentication](https://dev.elsevier.com/tecdoc_api_authentication.html)

Test Scopus alone without altering the ledger or exposing keys:

```bash
docker compose exec -T evidence-api python - <<'PY'
from evidence_pipeline.config import load_database_queries, load_study_config
from evidence_pipeline.sources.elsevier import ScopusAdapter
profile = '/app/studies/drug_shortage_eis/profiles/baseline'
study = load_study_config(profile)
query = next(q for q in load_database_queries(profile) if q.source_name == 'scopus')
adapter = ScopusAdapter(study.sources['scopus'], contact_email=study.contact_email)
for record in adapter.search(query.text, limit=5):
    print(record.year, record.title, record.doi, sep=' | ')
PY
```

This performs a small live API request. Automated tests use simulated responses;
live entitlement verification must happen on the server with your credentials.
