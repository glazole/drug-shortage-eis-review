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

## Quick start

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

## Current milestone

The first milestone provides:

- canonical work and discovery models;
- configurable OpenAlex, PubMed, Crossref, Scopus, ScienceDirect, and Semantic Scholar adapters;
- graceful degradation for optional sources;
- backward/forward citation and author-expansion capabilities where the source supports them;
- a SQLite evidence ledger preserving multiple discovery paths;
- a draft study protocol and source-specific pilot queries;
- unit tests for source failure handling, DOI normalization, and provenance preservation.

The next milestone will add reviewer-oriented screening import/export, explicit exclusion-reason
codes, query recall tests against the legacy thesis corpus, and PRISMA 2020/PRISMA-S reporting.
