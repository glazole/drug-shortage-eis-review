"""Orchestrate database and graph discovery while preserving failure states."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from .config import SourceConfig
from .exceptions import SourceUnavailableError, UnsupportedCapabilityError
from .models import (
    AuthorSeed,
    CitationSeed,
    DiscoveredWork,
    DiscoveryEvent,
    DiscoveryMethod,
    SearchQuery,
    SourceRunReport,
    SourceStatus,
    WorkRecord,
)
from .sources.base import SourceAdapter


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryRunner:
    def __init__(
        self,
        adapters: dict[str, SourceAdapter],
        source_configs: dict[str, SourceConfig],
        *,
        min_year: int | None = None,
        max_year: int | None = None,
        include_abstracts: bool = True,
    ) -> None:
        self.adapters = adapters
        self.source_configs = source_configs
        self.min_year = min_year
        self.max_year = max_year
        self.include_abstracts = include_abstracts

    def _prepare_records(self, records: Iterable[WorkRecord]) -> list[WorkRecord]:
        prepared: list[WorkRecord] = []
        for record in records:
            if (
                record.year is not None
                and self.min_year is not None
                and record.year < self.min_year
            ):
                continue
            if (
                record.year is not None
                and self.max_year is not None
                and record.year > self.max_year
            ):
                continue
            if not self.include_abstracts:
                record.abstract = None
            prepared.append(record)
        return prepared

    def _disabled_report(
        self,
        *,
        run_id: str,
        source_name: str,
        method: DiscoveryMethod,
        query_id: str | None = None,
    ) -> SourceRunReport:
        return SourceRunReport(
            run_id=run_id,
            source_name=source_name,
            status=SourceStatus.DISABLED,
            method=method,
            query_id=query_id,
            message="Source disabled by protocol",
        )

    def search(
        self,
        *,
        run_id: str,
        queries: Iterable[SearchQuery],
        limit_per_query: int,
    ) -> tuple[list[DiscoveredWork], list[SourceRunReport]]:
        discovered: list[DiscoveredWork] = []
        reports: list[SourceRunReport] = []
        for query in queries:
            config = self.source_configs.get(query.source_name)
            adapter = self.adapters.get(query.source_name)
            if config is None or not config.enabled:
                reports.append(
                    self._disabled_report(
                        run_id=run_id,
                        source_name=query.source_name,
                        method=DiscoveryMethod.DATABASE,
                        query_id=query.query_id,
                    )
                )
                continue
            started_at = _now()
            try:
                if adapter is None:
                    raise UnsupportedCapabilityError(
                        f"No adapter registered for {query.source_name}"
                    )
                raw_records = adapter.search(query.text, limit=limit_per_query)
                records = self._prepare_records(raw_records)
                for record in records:
                    discovered.append(
                        DiscoveredWork(
                            record=record,
                            event=DiscoveryEvent(
                                run_id=run_id,
                                source_name=query.source_name,
                                method=DiscoveryMethod.DATABASE,
                                query_id=query.query_id,
                                query_text=query.text,
                            ),
                        )
                    )
                reports.append(
                    SourceRunReport(
                        run_id=run_id,
                        source_name=query.source_name,
                        status=SourceStatus.SUCCESS,
                        method=DiscoveryMethod.DATABASE,
                        query_id=query.query_id,
                        retrieved_count=len(records),
                        started_at=started_at,
                        completed_at=_now(),
                        requested_limit=limit_per_query,
                        total_results=getattr(adapter, "last_search_total", None),
                        possibly_truncated=(
                            len(raw_records) >= limit_per_query
                            and (getattr(adapter, "last_search_total", None) is None
                                 or adapter.last_search_total > len(raw_records))
                        ),
                    )
                )
            except SourceUnavailableError as exc:
                if config.required:
                    raise
                reports.append(
                    SourceRunReport(
                        run_id=run_id,
                        source_name=query.source_name,
                        status=SourceStatus.UNAVAILABLE,
                        method=DiscoveryMethod.DATABASE,
                        query_id=query.query_id,
                        message=str(exc),
                        started_at=started_at,
                        completed_at=_now(),
                    )
                )
            except Exception as exc:
                if config.required:
                    raise
                reports.append(
                    SourceRunReport(
                        run_id=run_id,
                        source_name=query.source_name,
                        status=SourceStatus.FAILED,
                        method=DiscoveryMethod.DATABASE,
                        query_id=query.query_id,
                        message=str(exc),
                        started_at=started_at,
                        completed_at=_now(),
                    )
                )
        return discovered, reports

    def citation_expand(
        self,
        *,
        run_id: str,
        source_name: str,
        method: DiscoveryMethod,
        seeds: Iterable[CitationSeed],
        iteration: int,
        limit_per_seed: int,
    ) -> tuple[list[DiscoveredWork], list[SourceRunReport]]:
        if method not in {DiscoveryMethod.BACKWARD, DiscoveryMethod.FORWARD}:
            raise ValueError("citation_expand supports backward or forward methods only")
        return self._expand(
            run_id=run_id,
            source_name=source_name,
            method=method,
            seeds=((seed.work_id, seed.source_identifier) for seed in seeds),
            iteration=iteration,
            limit_per_seed=limit_per_seed,
        )

    def author_expand(
        self,
        *,
        run_id: str,
        source_name: str,
        seeds: Iterable[AuthorSeed],
        iteration: int,
        limit_per_seed: int,
    ) -> tuple[list[DiscoveredWork], list[SourceRunReport]]:
        return self._expand(
            run_id=run_id,
            source_name=source_name,
            method=DiscoveryMethod.AUTHOR,
            seeds=((seed.work_id, seed.author_identifier) for seed in seeds),
            iteration=iteration,
            limit_per_seed=limit_per_seed,
        )

    def _expand(
        self,
        *,
        run_id: str,
        source_name: str,
        method: DiscoveryMethod,
        seeds: Iterable[tuple[str, str]],
        iteration: int,
        limit_per_seed: int,
    ) -> tuple[list[DiscoveredWork], list[SourceRunReport]]:
        config = self.source_configs[source_name]
        if not config.enabled:
            return [], [
                self._disabled_report(run_id=run_id, source_name=source_name, method=method)
            ]
        adapter = self.adapters[source_name]
        discovered: list[DiscoveredWork] = []
        reports: list[SourceRunReport] = []
        for parent_work_id, source_identifier in seeds:
            started_at = _now()
            try:
                if method == DiscoveryMethod.BACKWARD:
                    records = self._prepare_records(
                        adapter.backward(source_identifier, limit=limit_per_seed)
                    )
                elif method == DiscoveryMethod.FORWARD:
                    records = self._prepare_records(
                        adapter.forward(source_identifier, limit=limit_per_seed)
                    )
                else:
                    records = self._prepare_records(
                        adapter.author_works(source_identifier, limit=limit_per_seed)
                    )
                for record in records:
                    discovered.append(
                        DiscoveredWork(
                            record=record,
                            event=DiscoveryEvent(
                                run_id=run_id,
                                source_name=source_name,
                                method=method,
                                parent_work_id=parent_work_id,
                                iteration=iteration,
                            ),
                        )
                    )
                reports.append(
                    SourceRunReport(
                        run_id=run_id,
                        source_name=source_name,
                        status=SourceStatus.SUCCESS,
                        method=method,
                        retrieved_count=len(records),
                        message=f"seed={source_identifier}",
                        started_at=started_at,
                        completed_at=_now(),
                    )
                )
            except SourceUnavailableError as exc:
                if config.required:
                    raise
                reports.append(
                    SourceRunReport(
                        run_id=run_id,
                        source_name=source_name,
                        status=SourceStatus.UNAVAILABLE,
                        method=method,
                        message=f"seed={source_identifier}; {exc}",
                        started_at=started_at,
                        completed_at=_now(),
                    )
                )
            except Exception as exc:
                if config.required:
                    raise
                reports.append(
                    SourceRunReport(
                        run_id=run_id,
                        source_name=source_name,
                        status=SourceStatus.FAILED,
                        method=method,
                        message=f"seed={source_identifier}; {exc}",
                        started_at=started_at,
                        completed_at=_now(),
                    )
                )
        return discovered, reports
