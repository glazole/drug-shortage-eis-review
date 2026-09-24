"""Command-line entrypoint for the first pipeline milestone."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from .config import load_database_queries, load_study_config
from .discovery import DiscoveryRunner
from .sources import build_source_registry
from .storage import SQLiteEvidenceStore


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("search_%Y%m%dT%H%M%SZ")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evidence-search")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config")
    validate.add_argument("--study", required=True)

    init_db = subparsers.add_parser("init-db")
    init_db.add_argument("--database", required=True)

    search = subparsers.add_parser("search")
    search.add_argument("--study", required=True)
    search.add_argument("--database", required=True)
    search.add_argument("--run-id")
    search.add_argument("--limit-per-query", type=int, default=200)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate-config":
        study = load_study_config(args.study)
        queries = load_database_queries(args.study)
        print(
            json.dumps(
                {
                    "study_id": study.study_id,
                    "sources": {
                        name: {"enabled": cfg.enabled, "required": cfg.required}
                        for name, cfg in study.sources.items()
                    },
                    "query_variants": len(queries),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    store = SQLiteEvidenceStore(args.database)
    store.initialize()
    if args.command == "init-db":
        print(json.dumps(store.summary(), indent=2))
        return 0

    study = load_study_config(args.study)
    queries = load_database_queries(args.study)
    registry = build_source_registry(study)
    runner = DiscoveryRunner(registry, study.sources)
    run_id = args.run_id or _run_id()
    discovered, reports = runner.search(
        run_id=run_id,
        queries=queries,
        limit_per_query=args.limit_per_query,
    )
    unique_works, discoveries = store.ingest(discovered)
    store.write_source_reports(reports)
    print(
        json.dumps(
            {
                "run_id": run_id,
                "retrieved_records": len(discovered),
                "unique_works_in_batch": unique_works,
                "new_discovery_events": discoveries,
                "source_statuses": [
                    {
                        "source": report.source_name,
                        "query_id": report.query_id,
                        "status": report.status.value,
                        "count": report.retrieved_count,
                        "message": report.message,
                    }
                    for report in reports
                ],
                "ledger": store.summary(),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
