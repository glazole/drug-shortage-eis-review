"""Command-line entrypoint for the first pipeline milestone."""

from __future__ import annotations

import argparse
import json

from .service import describe_study, initialize_database, run_database_search


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
        print(json.dumps(describe_study(args.study), indent=2, ensure_ascii=False))
        return 0

    if args.command == "init-db":
        print(json.dumps(initialize_database(args.database), indent=2))
        return 0

    result = run_database_search(
        study_dir=args.study,
        database_path=args.database,
        limit_per_query=args.limit_per_query,
        run_id=args.run_id,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
