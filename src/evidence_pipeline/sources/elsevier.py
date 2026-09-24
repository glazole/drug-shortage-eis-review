"""Separate Scopus and ScienceDirect adapters over Elsevier APIs."""

from __future__ import annotations

from typing import Any

from ..exceptions import SourceRequestError
from ..models import WorkRecord
from ..normalization import clean_markup, normalize_doi
from .base import SourceAdapter


class _ElsevierAdapter(SourceAdapter):
    endpoint = ""

    @property
    def default_headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise SourceRequestError(f"{self.name} requires {self.config.api_key_env}")
        return super().default_headers | {"X-ELS-APIKey": self.config.api_key}

    @staticmethod
    def _map_work(item: dict[str, Any]) -> WorkRecord:
        doi = normalize_doi(item.get("prism:doi"))
        identifier = item.get("eid") or item.get("dc:identifier")
        authors_raw = item.get("author") or []
        if isinstance(authors_raw, dict):
            authors_raw = [authors_raw]
        authors = tuple(
            str(author.get("authname") or author.get("ce:indexed-name") or "").strip()
            for author in authors_raw
            if isinstance(author, dict)
        )
        year_raw = str(item.get("prism:coverDate") or "")[:4]
        year = int(year_raw) if year_raw.isdigit() else None
        return WorkRecord(
            title=str(item.get("dc:title") or "").strip(),
            abstract=clean_markup(item.get("dc:description")),
            year=year,
            doi=doi,
            authors=tuple(value for value in authors if value),
            venue=item.get("prism:publicationName"),
            url=item.get("prism:url"),
            source_record_id=identifier,
            external_ids={"elsevier_id": str(identifier)} if identifier else {},
        )

    def search(self, query: str, *, limit: int) -> list[WorkRecord]:
        records: list[WorkRecord] = []
        start = 0
        while len(records) < limit:
            data = self.get_json(
                self.endpoint,
                params={
                    "query": query,
                    "start": start,
                    "count": min(25, limit - len(records)),
                    "view": "COMPLETE",
                },
            )
            search_results = data.get("search-results") or {}
            batch = search_results.get("entry") or []
            records.extend(self._map_work(item) for item in batch if item.get("dc:title"))
            start += len(batch)
            total = int(search_results.get("opensearch:totalResults") or 0)
            if not batch or start >= total:
                break
        return records[:limit]


class ScopusAdapter(_ElsevierAdapter):
    endpoint = "https://api.elsevier.com/content/search/scopus"


class ScienceDirectAdapter(_ElsevierAdapter):
    endpoint = "https://api.elsevier.com/content/search/sciencedirect"
