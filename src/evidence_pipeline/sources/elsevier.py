"""Separate Scopus and ScienceDirect adapters over Elsevier APIs."""

from __future__ import annotations

import os
from typing import Any

from ..exceptions import HttpStatusError, SourceRequestError
from ..models import WorkRecord
from ..normalization import clean_markup, normalize_doi
from .base import SourceAdapter


class _ElsevierAdapter(SourceAdapter):
    endpoint = ""

    @property
    def default_headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise SourceRequestError(f"{self.name} requires {self.config.api_key_env}")
        headers = super().default_headers | {"X-ELS-APIKey": self.config.api_key}
        token = os.getenv(self.config.options.get("insttoken_env", "ELSEVIER_INSTTOKEN"), "").strip()
        if token:
            headers["X-ELS-Insttoken"] = token
        return headers

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

    def _diagnostic(self, exc: SourceRequestError) -> SourceRequestError:
        cause = exc.__cause__
        status = cause.status_code if isinstance(cause, HttpStatusError) else None
        if self.name == "scopus" and status in {401, 403}:
            return SourceRequestError(
                f"scopus HTTP {status}: check ELSEVIER_API_KEY, Scopus API entitlement, "
                "institutional network or ELSEVIER_INSTTOKEN; STANDARD view also requires authorized access"
            )
        return SourceRequestError(str(exc))

    def search(self, query: str, *, limit: int) -> list[WorkRecord]:
        records: list[WorkRecord] = []
        start = 0
        fallback_to_standard = False
        while len(records) < limit:
            default_view = "STANDARD" if self.name == "scopus" else "COMPLETE"
            view = "STANDARD" if fallback_to_standard else self.config.options.get("view", default_view)
            params = {
                "query": query,
                "start": start,
                "count": min(25, limit - len(records)),
                "view": view,
            }
            if self.name == "scopus" and self.config.options.get("year"):
                params["date"] = self.config.options["year"]
            try:
                data = self.get_json(self.endpoint, params=params)
            except SourceRequestError as exc:
                cause = exc.__cause__
                if (self.name == "scopus" and params["view"] == "COMPLETE"
                        and isinstance(cause, HttpStatusError) and cause.status_code == 403):
                    # COMPLETE can require additional entitlements; retry this page once
                    # with the documented default. No fallback for invalid keys/queries.
                    params["view"] = "STANDARD"
                    fallback_to_standard = True
                    try:
                        data = self.get_json(self.endpoint, params=params)
                    except SourceRequestError as fallback_exc:
                        raise self._diagnostic(fallback_exc) from fallback_exc
                else:
                    raise self._diagnostic(exc) from exc
            if data.get("service-error") or data.get("error-response"):
                raise SourceRequestError(f"{self.name}: API returned an error payload")
            search_results = data.get("search-results")
            if not isinstance(search_results, dict):
                raise SourceRequestError(f"{self.name}: missing search-results in API response")
            batch = search_results.get("entry") or []
            if isinstance(batch, dict):
                batch = [batch]
            if any(item.get("error") for item in batch):
                if int(search_results.get("opensearch:totalResults") or 0) == 0:
                    break
                raise SourceRequestError(f"{self.name}: error entry in API response")
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
