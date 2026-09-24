"""Crossref metadata-search adapter."""

from __future__ import annotations

from typing import Any

from ..models import WorkRecord
from ..normalization import clean_markup, normalize_doi
from .base import SourceAdapter


class CrossrefAdapter(SourceAdapter):
    base_url = "https://api.crossref.org/works"

    @staticmethod
    def _year(item: dict[str, Any]) -> int | None:
        for key in ("published-print", "published-online", "issued"):
            parts = (item.get(key) or {}).get("date-parts") or []
            if parts and parts[0]:
                try:
                    return int(parts[0][0])
                except (TypeError, ValueError):
                    pass
        return None

    @staticmethod
    def _map_work(item: dict[str, Any]) -> WorkRecord:
        authors = tuple(
            " ".join(filter(None, [author.get("given"), author.get("family")])).strip()
            for author in item.get("author") or []
            if author.get("given") or author.get("family")
        )
        title_values = item.get("title") or [""]
        venue_values = item.get("container-title") or []
        doi = normalize_doi(item.get("DOI"))
        return WorkRecord(
            title=str(title_values[0]).strip(),
            abstract=clean_markup(item.get("abstract")),
            year=CrossrefAdapter._year(item),
            doi=doi,
            authors=authors,
            venue=str(venue_values[0]).strip() if venue_values else None,
            url=item.get("URL"),
            source_record_id=doi,
            external_ids={"crossref_doi": doi} if doi else {},
        )

    def search(self, query: str, *, limit: int) -> list[WorkRecord]:
        records: list[WorkRecord] = []
        cursor = "*"
        rows = min(1000, max(1, limit))
        filters = ["type:journal-article"]
        min_date = self.config.options.get("min_date")
        max_date = self.config.options.get("max_date")
        if min_date:
            filters.append(f"from-pub-date:{min_date}")
        if max_date:
            filters.append(f"until-pub-date:{max_date}")
        while len(records) < limit:
            data = self.get_json(
                self.base_url,
                params={
                    "query.bibliographic": query,
                    "rows": min(rows, limit - len(records)),
                    "cursor": cursor,
                    "filter": ",".join(filters),
                    "mailto": self.contact_email,
                },
            )
            message = data.get("message") or {}
            items = message.get("items") or []
            records.extend(self._map_work(item) for item in items if item.get("title"))
            next_cursor = message.get("next-cursor")
            if not items or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return records[:limit]
