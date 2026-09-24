"""OpenAlex database-search adapter."""

from __future__ import annotations

from typing import Any

from ..models import WorkRecord
from ..normalization import normalize_doi
from .base import SourceAdapter


class OpenAlexAdapter(SourceAdapter):
    base_url = "https://api.openalex.org"

    @staticmethod
    def _abstract(index: dict[str, list[int]] | None) -> str | None:
        if not index:
            return None
        positions = sorted((position, word) for word, values in index.items() for position in values)
        return " ".join(word for _, word in positions) or None

    @staticmethod
    def _map_work(item: dict[str, Any]) -> WorkRecord:
        authors = tuple(
            authorship.get("author", {}).get("display_name", "").strip()
            for authorship in item.get("authorships") or []
            if authorship.get("author", {}).get("display_name")
        )
        primary_location = item.get("primary_location") or {}
        source = primary_location.get("source") or {}
        ids = item.get("ids") or {}
        external_ids = {"openalex": item.get("id", "")}
        if ids.get("pmid"):
            external_ids["pmid"] = str(ids["pmid"]).rsplit("/", 1)[-1]
        return WorkRecord(
            title=str(item.get("title") or "").strip(),
            abstract=OpenAlexAdapter._abstract(item.get("abstract_inverted_index")),
            year=item.get("publication_year"),
            doi=normalize_doi(item.get("doi")),
            authors=authors,
            venue=source.get("display_name"),
            url=primary_location.get("landing_page_url") or item.get("id"),
            source_record_id=item.get("id"),
            external_ids={key: value for key, value in external_ids.items() if value},
        )

    def search(self, query: str, *, limit: int) -> list[WorkRecord]:
        records: list[WorkRecord] = []
        cursor = "*"
        per_page = min(200, max(1, limit))
        filters = [f"from_publication_date:{self.config.options.get('min_date', '2010-01-01')}"]
        max_date = self.config.options.get("max_date")
        if max_date:
            filters.append(f"to_publication_date:{max_date}")
        while len(records) < limit:
            params: dict[str, Any] = {
                "search": query,
                "filter": ",".join(filters),
                "per-page": min(per_page, limit - len(records)),
                "cursor": cursor,
                "mailto": self.contact_email,
            }
            if self.config.api_key:
                params["api_key"] = self.config.api_key
            data = self.get_json(f"{self.base_url}/works", params=params)
            batch = data.get("results") or []
            records.extend(self._map_work(item) for item in batch if item.get("title"))
            next_cursor = (data.get("meta") or {}).get("next_cursor")
            if not batch or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return records[:limit]

    def backward(self, work_identifier: str, *, limit: int) -> list[WorkRecord]:
        work = self.get_json(f"{self.base_url}/works/{work_identifier}")
        references = work.get("referenced_works") or []
        if not references:
            return []
        identifiers = [value.rsplit("/", 1)[-1] for value in references[:limit]]
        records: list[WorkRecord] = []
        for start in range(0, len(identifiers), 50):
            chunk = identifiers[start : start + 50]
            data = self.get_json(
                f"{self.base_url}/works",
                params={"filter": f"openalex:{'|'.join(chunk)}", "per-page": len(chunk)},
            )
            records.extend(self._map_work(item) for item in data.get("results") or [])
        return records[:limit]

    def forward(self, work_identifier: str, *, limit: int) -> list[WorkRecord]:
        identifier = work_identifier.rsplit("/", 1)[-1]
        data = self.get_json(
            f"{self.base_url}/works",
            params={"filter": f"cites:{identifier}", "per-page": min(200, limit)},
        )
        return [self._map_work(item) for item in data.get("results") or []][:limit]

    def author_works(self, author_identifier: str, *, limit: int) -> list[WorkRecord]:
        identifier = author_identifier.rsplit("/", 1)[-1]
        data = self.get_json(
            f"{self.base_url}/works",
            params={
                "filter": f"author.id:{identifier}",
                "per-page": min(200, limit),
                "sort": "publication_date:desc",
            },
        )
        return [self._map_work(item) for item in data.get("results") or []][:limit]
