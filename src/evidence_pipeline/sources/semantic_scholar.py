"""Semantic Scholar search and graph adapter."""

from __future__ import annotations

import urllib.parse
from typing import Any

from ..models import WorkRecord
from ..normalization import normalize_doi
from .base import SourceAdapter


class SemanticScholarAdapter(SourceAdapter):
    base_url = "https://api.semanticscholar.org/graph/v1"
    base_paper_fields = (
        "paperId,externalIds,title,year,authors,venue,url,citationCount,publicationTypes"
    )

    @property
    def paper_fields(self) -> str:
        if self.config.include_abstracts:
            return f"{self.base_paper_fields},abstract"
        return self.base_paper_fields

    @property
    def default_headers(self) -> dict[str, str]:
        headers = super().default_headers
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
        return headers

    @staticmethod
    def _map_work(item: dict[str, Any]) -> WorkRecord:
        external = item.get("externalIds") or {}
        doi = normalize_doi(external.get("DOI"))
        identifiers = {"semantic_scholar": str(item.get("paperId") or "")}
        for source_key, target_key in (("PubMed", "pmid"), ("CorpusId", "s2_corpus_id")):
            if external.get(source_key):
                identifiers[target_key] = str(external[source_key])
        return WorkRecord(
            title=str(item.get("title") or "").strip(),
            abstract=item.get("abstract"),
            year=item.get("year"),
            doi=doi,
            authors=tuple(
                str(author.get("name") or "").strip()
                for author in item.get("authors") or []
                if author.get("name")
            ),
            venue=item.get("venue"),
            url=item.get("url"),
            source_record_id=item.get("paperId"),
            external_ids={key: value for key, value in identifiers.items() if value},
        )

    def search(self, query: str, *, limit: int) -> list[WorkRecord]:
        records: list[WorkRecord] = []
        offset = 0
        while len(records) < limit:
            data = self.get_json(
                f"{self.base_url}/paper/search",
                params={
                    "query": query,
                    "offset": offset,
                    "limit": min(100, limit - len(records)),
                    "fields": self.paper_fields,
                    "year": self.config.options.get("year", "2010-2026"),
                },
            )
            batch = data.get("data") or []
            records.extend(self._map_work(item) for item in batch if item.get("title"))
            next_offset = data.get("next")
            if not batch or next_offset is None or int(next_offset) <= offset:
                break
            offset = int(next_offset)
        return records[:limit]

    def _paper_relation(
        self,
        work_identifier: str,
        *,
        relation: str,
        record_key: str,
        limit: int,
    ) -> list[WorkRecord]:
        encoded = urllib.parse.quote(work_identifier, safe="")
        records: list[WorkRecord] = []
        offset = 0
        while len(records) < limit:
            data = self.get_json(
                f"{self.base_url}/paper/{encoded}/{relation}",
                params={
                    "offset": offset,
                    "limit": min(500, limit - len(records)),
                    "fields": self.paper_fields,
                },
            )
            batch = data.get("data") or []
            for relation_item in batch:
                item = relation_item.get(record_key) or {}
                if item.get("title"):
                    records.append(self._map_work(item))
            next_offset = data.get("next")
            if not batch or next_offset is None or int(next_offset) <= offset:
                break
            offset = int(next_offset)
        return records[:limit]

    def backward(self, work_identifier: str, *, limit: int) -> list[WorkRecord]:
        return self._paper_relation(
            work_identifier,
            relation="references",
            record_key="citedPaper",
            limit=limit,
        )

    def forward(self, work_identifier: str, *, limit: int) -> list[WorkRecord]:
        return self._paper_relation(
            work_identifier,
            relation="citations",
            record_key="citingPaper",
            limit=limit,
        )

    def author_works(self, author_identifier: str, *, limit: int) -> list[WorkRecord]:
        encoded = urllib.parse.quote(author_identifier, safe="")
        records: list[WorkRecord] = []
        offset = 0
        while len(records) < limit:
            data = self.get_json(
                f"{self.base_url}/author/{encoded}/papers",
                params={
                    "offset": offset,
                    "limit": min(100, limit - len(records)),
                    "fields": self.paper_fields,
                },
            )
            batch = data.get("data") or []
            records.extend(self._map_work(item) for item in batch if item.get("title"))
            next_offset = data.get("next")
            if not batch or next_offset is None or int(next_offset) <= offset:
                break
            offset = int(next_offset)
        return records[:limit]
