"""Command-line entrypoint for the first pipeline milestone."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .service import describe_study, enrich_existing_run, initialize_database, run_database_search
from .config import load_study_config
from .corpus import export_corpus_csv, run_summary
from .diagnostics import probe_scopus
from .storage import SQLiteEvidenceStore


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
    search.add_argument("--skip-enrichment", action="store_true")

    enrich = subparsers.add_parser("enrich-abstracts")
    enrich.add_argument("--study", required=True)
    enrich.add_argument("--database", required=True)
    enrich.add_argument("--run-id", required=True)
    enrich.add_argument("--max-works", type=int)
    enrich.add_argument("--discovery-source")

    export = subparsers.add_parser("export-corpus")
    export.add_argument("--database", required=True)
    export.add_argument("--run-id", required=True)
    export.add_argument("--output", required=True)

    summary = subparsers.add_parser("run-summary")
    summary.add_argument("--database", required=True)
    summary.add_argument("--run-id", required=True)

    probe = subparsers.add_parser("probe-scopus")
    probe.add_argument("--study", required=True)
    probe.add_argument("--doi", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "validate-config":
        print(json.dumps(describe_study(args.study), indent=2, ensure_ascii=False))
        return 0

    if args.command == "init-db":
        print(json.dumps(initialize_database(args.database), indent=2))
        return 0

    if args.command == "probe-scopus":
        print(json.dumps(probe_scopus(load_study_config(args.study), args.doi), indent=2))
        return 0

    if args.command == "enrich-abstracts":
        result = enrich_existing_run(study_dir=args.study, database_path=args.database,
                                     run_id=args.run_id, max_works=args.max_works,
                                     discovery_source=args.discovery_source)
        print(json.dumps(result, indent=2))
        return 0

    if args.command in {"export-corpus", "run-summary"}:
        store = SQLiteEvidenceStore(args.database)
        store.initialize()
        if args.command == "run-summary":
            print(json.dumps(run_summary(store, args.run_id), indent=2))
        else:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(export_corpus_csv(store, args.run_id), encoding="utf-8")
            print(json.dumps({"run_id": args.run_id, "output": str(output)}))
        return 0

    result = run_database_search(
        study_dir=args.study,
        database_path=args.database,
        limit_per_query=args.limit_per_query,
        run_id=args.run_id,
        enrich_abstracts=False if args.skip_enrichment else None,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
