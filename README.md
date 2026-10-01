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

## Current capabilities

This branch provides database retrieval, normalization and deduplication, exact-DOI
abstract enrichment with provenance, advisory automatic relevance checks, and
whole-run CSV export for manual screening. API and package version: `0.2.0`;
Python: `3.12+`; storage: SQLite.

Citation and author-expansion adapters and runner methods exist, but the current
CLI/API search executes database queries only. `snowballing` settings and seeds
do not trigger an automatic iterative snowballing workflow. Human screening
import, full-text assessment, quality appraisal, synthesis, recall validation
and PRISMA report generation remain future work.

## Design principles

1. Every database or API is an optional source adapter.
2. A scientific work is stored once, but every discovery path is retained.
3. Database search, backward citation search, forward citation search, and author expansion
   produce the same canonical `WorkRecord` and `DiscoveryEvent` objects.
4. A disabled source is recorded as `disabled`; a transiently inaccessible optional source is
   recorded as `unavailable`; neither is silently treated as an empty result.
5. A required database-search source aborts the run on failure. Optional-source
   failures allow the run to complete; inspect source statuses before judging completeness.
   Abstract lookup failures are audited and allow fallback even for a required search source.

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
cp -n .env.example .env
# Edit .env: set RESEARCH_CONTACT_EMAIL and source credentials/overrides.
docker compose up --build -d
docker compose ps
```

Use `cp -n` only to create a missing `.env`; keep existing credentials when updating.
The example `.env` enables Scopus as a **required search source**, with an empty
Elsevier key. Set `ELSEVIER_API_KEY` before searching, or explicitly set
`EVIDENCE_SOURCE_SCOPUS_ENABLED=false` and `EVIDENCE_SOURCE_SCOPUS_REQUIRED=false`.
Service health checks the ledger, not access to scholarly APIs.

The YAML baseline and `.env.example` differ:

| Setting | Baseline YAML without overrides | Copied `.env.example` |
|---|---|---|
| Year range | 2010–2026 | 2021–2026 |
| Required database sources | PubMed | PubMed, OpenAlex, Crossref, Scopus |
| Scopus | Disabled, optional | Enabled, required |
| ScienceDirect | Disabled, optional | Enabled, required; no baseline database query |
| Semantic Scholar | Disabled, optional | Disabled, optional |

There are three English query groups and 15 source/query variants in the baseline
(PubMed, OpenAlex, Crossref, Scopus, Semantic Scholar). ScienceDirect has an
adapter but no baseline database query, so enabling it does not add search results.

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

The request is synchronous: `curl` waits for database retrieval, persistence,
abstract enrichment (when enabled), and automatic relevance assessment, or for
a required-source failure. Container logs are available from another terminal;
there is no dedicated progress/job-status API:

```bash
docker compose logs -f evidence-api
```

After completion, inspect the ledger counters:

```bash
curl http://localhost:8000/v1/ledger/summary
```

For a larger corpus, use another unique ID such as `baseline_corpus_<timestamp>`
and increase `limit_per_query` (default 200; allowed 1–5000). A larger limit does
not establish search completeness. Inspect totals, truncation and source failures.
See [corpus collection and export](#collect-a-corpus-enrich-abstracts-then-screen-manually).

### How often to run the same profile

Technically, the same profile and settings can be run any number of times, but:

- search, automatic assessment, enrichment and Scopus diagnostics share one
  in-process lock; a concurrent operation receives HTTP `409`;
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
3. `baseline_corpus_01`: retrieve the frozen profile, inspect source statuses and
   truncation, export the corpus, then perform manual screening.
4. Run again only to recover an unavailable source, evaluate a deliberately changed profile, or
   update the search before publication.

If a required source aborts database retrieval, the run is marked `failed`; the
current service does not persist the partial results/reports accumulated before
that abort. Completed runs with optional failures still need inspection.

Pilot and corpus runs may share one SQLite ledger. Their provenance remains distinguishable by
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

EVIDENCE_MIN_YEAR=2021
EVIDENCE_MAX_YEAR=2026
EVIDENCE_SEARCH_LANGUAGE=en
EVIDENCE_INCLUDE_ABSTRACTS=true
EVIDENCE_ENRICH_ABSTRACTS=true

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

Study/profile responses include `env_overrides`, effective settings, relevance rules
and enrichment configuration. Search responses include the effective date range,
language, abstract setting and operation summaries. `search_runs` stores queries,
limits, effective source flags/search views, relevance rules, enrichment configuration
and completion status. Its `env_overrides` list tracks the overrides handled by
the study loader; it is not a complete list of every deployment variable.

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
ledger for incoming results. When it is false, incoming abstracts are discarded
before persistence and search-time enrichment is skipped; existing canonical
abstracts from previous runs are not erased. Adapters may still receive abstract
metadata when an upstream API does not offer a field-selection option.

## Local CLI quick start

Run from the repository root with Python 3.12 or newer. Unlike Compose, the CLI
does **not** automatically load `.env`. Export its values in your shell:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp -n .env.example .env
# Edit .env before loading it. This is a trusted shell configuration.
set -a
source .env
set +a
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
| `GET` | `/` | Return service and documentation links |
| `GET` | `/health` | Check the service and initialize/read the ledger |
| `GET` | `/v1/studies` | List saved studies and profiles |
| `GET` | `/v1/studies/{study_id}` | Read the selected/default profile |
| `GET` | `/v1/studies/{study_id}/profiles/{profile_id}` | Read a specific saved profile |
| `GET` | `/v1/ledger/summary` | Return work, discovery, source-run, and search-run counts |
| `POST` | `/v1/search` | Retrieve, deduplicate, optionally enrich, then assess relevance |
| `POST` | `/v1/screening/automatic` | Assess an existing run using current rules/metadata |
| `POST` | `/v1/enrichment/abstracts` | Fill missing abstracts in an existing run |
| `POST` | `/v1/diagnostics/scopus-abstract` | Compare Scopus abstract access without ledger writes |
| `GET` | `/v1/runs/{run_id}/summary` | Return run status, corpus/abstract counts and source reports |
| `GET` | `/v1/runs/{run_id}/corpus.csv` | Download all run works with screening columns |

Profile responses include the effective date range, language, abstract setting, research
questions, concepts, eligibility criteria, sources, and applied environment overrides. They report
whether an API key is configured but never return the key itself. Semantic Scholar remains
disabled in the baseline profile unless explicitly enabled in the profile or `.env`.

## Verification

Run deterministic tests without live provider credentials:

```bash
PYTHONPATH=src python -m unittest discover -s tests -q
git diff --check
```

The current suite contains 63 tests covering API operations, DOI lookup/fallback,
provenance, deduplication, run isolation, preservation of manual decisions,
legacy schema migration, source failures, pagination and Scopus diagnostics.
Live provider availability and access are separate checks.

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
candidates does not repair recall lost through broad ranked API searches. Collect
the corpus before manual screening, and inspect retrieval limits and exclusions
before claiming completeness.

### Update the service and assess the existing pilot

Update this feature branch directly (merging is not required to use it):

```bash
cd ~/drug-shortage-eis-review
git fetch origin
git switch fix/relevance-gate-scopus
git pull --ff-only origin fix/relevance-gate-scopus
docker compose up -d --build evidence-api
```

The existing `evidence-data` volume is reused. Idempotent schema initialization
adds relevance/enrichment tables and retrieval-count columns to `source_runs`.
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
  -d '{"study_id":"drug_shortage_eis","profile_id":"baseline","run_id":"REPLACE_WITH_YOUR_PILOT_RUN_ID"}'
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

## Collect a corpus, enrich abstracts, then screen manually

New searches automatically fill missing abstracts by exact DOI in this order:
Scopus Abstract Retrieval (`META_ABS`), OpenAlex, PubMed, Crossref. Providers must
be listed under `abstract_enrichment.sources` and have a configured adapter.
**Current implementation:** source `enabled`/`required` flags govern discovery,
not DOI enrichment. A source disabled for search may still receive DOI lookups.
Remove it from `abstract_enrichment.sources` to prevent those enrichment calls.
Existing nonempty abstracts are retained by the enrichment operation. A lookup
with a different DOI is rejected; there is no title-based abstract matching.
Enrichment does not create discoveries or change the original search source.

`work_abstracts` records the provider, method (`search` or `doi_lookup`), public
URL, timestamp and text hash. `abstract_lookup_attempts` records missing texts,
DOI mismatches and failures separately. After 401/403/429 or exhausted transport
retries, that provider is skipped for the rest of this enrichment batch; later
providers are still tried. Repeat the operation to retry unresolved works.
Credentials and raw transport error messages are not written to this audit.
Older abstracts whose provenance was not recorded are exported as
`legacy_unknown`; their provider is not guessed from discovery sources.

Update the existing branch and rebuild the service:

```bash
cd ~/drug-shortage-eis-review
git fetch origin
git switch fix/relevance-gate-scopus
git pull --ff-only origin fix/relevance-gate-scopus
docker compose up -d --build
```

Check which Scopus views actually return an abstract with your credentials:

```bash
curl --fail-with-body -sS -X POST http://localhost:8000/v1/diagnostics/scopus-abstract \
  -H 'Content-Type: application/json' \
  -d '{"doi":"10.1038/s41598-025-30413-7"}'
```

The diagnostic compares STANDARD, COMPLETE (including effective fallback view)
and META_ABS. It returns presence/length, not abstract text, and writes nothing
to the ledger. Search access does not guarantee Abstract Retrieval access.
A successful STANDARD lookup without an abstract followed by 401 in COMPLETE/META_ABS is reported as
such; 401 does not trigger the COMPLETE→STANDARD fallback. The diagnostic tests
Scopus explicitly even if it is disabled for discovery.

Try enrichment on five missing Scopus works in the existing pilot:

```bash
curl --fail-with-body -sS -X POST http://localhost:8000/v1/enrichment/abstracts \
  -H 'Content-Type: application/json' \
  -d '{"run_id":"baseline_pilot_v2_20261001T092422Z","discovery_source":"scopus","max_works":5}'
```

Omit `max_works` to process all missing works; omit `discovery_source` to process
all discovery sources. This updates current work metadata; previous automatic
assessments and human decisions remain as recorded. Explicitly rerun
`POST /v1/screening/automatic` if you want updated automatic assessments.

Collect a new run and export every deduplicated work for manual screening:

```bash
mkdir -p artifacts/exports
RUN_ID="baseline_corpus_$(date -u +%Y%m%dT%H%M%SZ)"
curl --fail-with-body -sS -X POST http://localhost:8000/v1/search \
  -H 'Content-Type: application/json' \
  -d "{\"run_id\":\"$RUN_ID\",\"limit_per_query\":500,\"enrich_abstracts\":true}" \
  -o "artifacts/exports/${RUN_ID}_search.json"
curl --fail-with-body -sS "http://localhost:8000/v1/runs/$RUN_ID/summary" \
  -o "artifacts/exports/${RUN_ID}_summary.json"
curl --fail-with-body -sS "http://localhost:8000/v1/runs/$RUN_ID/corpus.csv" \
  -o "artifacts/exports/${RUN_ID}.csv"
```

Search and enrichment are synchronous and may take several minutes. The example
limit is 500 per source/query; supported limits are 1–5000. Inspect
`total_results` and `possibly_truncated` for each source/query before interpreting
the corpus as complete. Totals are provider-reported, not counts of eligible
unique studies. Unknown totals are null. `possibly_truncated=false` is not proof
of completeness: it only describes the detected per-query retrieval cap.
Legacy source reports have no totals.
The run stores its actual queries, year range and retrieval limit.

The UTF-8 CSV includes all works, even automatic exclusions, plus abstract
provenance and separate discovery sources. Fill `manual_decision`,
`manual_reason_code`, `screening_note`, `reviewer`, and `screened_at` yourself.
Exporting does not import your edits back into SQLite. Each run's membership is
fixed by its discoveries, but exported metadata reflects the latest merged work
record; later discovery ingestion may select a longer abstract. Deduplication
uses the existing DOI/title/year rules; review uncertain matches manually. Abstract availability is not guaranteed for every DOI.

Set `EVIDENCE_ENRICH_ABSTRACTS=false` to disable automatic enrichment, or send
`"enrich_abstracts":false` for one search. Provider order and request pacing are
configured under `abstract_enrichment` in `protocol.yaml`. An explicit search
`enrich_abstracts` value overrides that enabled setting (including the environment
override), but `include_abstracts=false` always prevents search-time enrichment.
Explicit existing-run enrichment requires `include_abstracts=true` and honors
the current enrichment enabled setting.

Enrichment responses report missing counts for the selected run/source subset.
`max_works` bounds attempted works (API range 1–50000), not the initial missing
count. `missing_after` includes unattempted works; `unresolved` counts attempted
works that remained without text. `discovery_source` filters original discovery
paths, not the providers queried for abstracts.

CLI equivalents are `enrich-abstracts`, `export-corpus`, `run-summary`, and
`probe-scopus` (see `evidence-search <command> --help`). Run CLI mutations while
the API is idle; its in-process lock does not coordinate separate processes.

For the local CLI database (not the separate Compose volume):

```bash
RUN_ID="REPLACE_WITH_AN_EXISTING_RUN_ID"
evidence-search enrich-abstracts \
  --study studies/drug_shortage_eis/profiles/baseline \
  --database data/review.sqlite3 --run-id "$RUN_ID" \
  --discovery-source scopus --max-works 5
evidence-search run-summary \
  --database data/review.sqlite3 --run-id "$RUN_ID"
evidence-search export-corpus \
  --database data/review.sqlite3 --run-id "$RUN_ID" \
  --output "artifacts/exports/${RUN_ID}.csv"
evidence-search probe-scopus \
  --study studies/drug_shortage_eis/profiles/baseline \
  --doi '10.1038/s41598-025-30413-7'
```


Live validation on three Scopus-only pilot records found two abstracts in
OpenAlex; the third DOI was found without an abstract. The saved experiment is
[docs/abstract-enrichment-validation.json](docs/abstract-enrichment-validation.json).
This small sample does not establish recovery rates for the whole corpus or
verify your Scopus entitlement. Scopus access must be checked on your server.

Provider documentation:

- [Scopus Abstract Retrieval API](https://dev.elsevier.com/documentation/AbstractRetrievalAPI.wadl)
- [OpenAlex work attributes](https://help.openalex.org/data/works/attributes/)
- [Crossref REST API](https://github.com/CrossRef/rest-api-doc)
- [PubMed search fields](https://pubmed.ncbi.nlm.nih.gov/help/)
