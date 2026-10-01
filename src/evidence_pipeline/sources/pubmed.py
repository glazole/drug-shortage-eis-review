"""PubMed E-utilities adapter using batched XML retrieval."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from ..models import WorkRecord
from ..normalization import normalize_doi
from .base import SourceAdapter


class PubMedAdapter(SourceAdapter):
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    @staticmethod
    def _text(element: ET.Element | None) -> str | None:
        if element is None:
            return None
        value = "".join(element.itertext()).strip()
        return re.sub(r"\s+", " ", value) or None

    @classmethod
    def _parse_articles(
        cls,
        xml_text: str,
        *,
        include_abstracts: bool = True,
    ) -> list[WorkRecord]:
        root = ET.fromstring(xml_text)
        records: list[WorkRecord] = []
        for node in root.findall(".//PubmedArticle"):
            citation = node.find("MedlineCitation")
            article = citation.find("Article") if citation is not None else None
            if citation is None or article is None:
                continue
            title = cls._text(article.find("ArticleTitle")) or ""
            if not title:
                continue
            pmid = cls._text(citation.find("PMID"))
            abstract = None
            if include_abstracts:
                abstract_parts = [
                    cls._text(value) for value in article.findall(".//Abstract/AbstractText")
                ]
                abstract = " ".join(value for value in abstract_parts if value) or None
            authors: list[str] = []
            for author in article.findall(".//AuthorList/Author"):
                collective = cls._text(author.find("CollectiveName"))
                name = " ".join(
                    filter(
                        None,
                        [
                            cls._text(author.find("ForeName")),
                            cls._text(author.find("LastName")),
                        ],
                    )
                )
                if collective or name:
                    authors.append(collective or name)
            doi = None
            for identifier in node.findall(".//PubmedData/ArticleIdList/ArticleId"):
                if identifier.attrib.get("IdType") == "doi":
                    doi = normalize_doi(cls._text(identifier))
                    break
            year_text = (
                cls._text(article.find(".//JournalIssue/PubDate/Year"))
                or cls._text(article.find(".//ArticleDate/Year"))
                or cls._text(article.find(".//JournalIssue/PubDate/MedlineDate"))
            )
            year_match = re.search(r"\b(19|20)\d{2}\b", year_text or "")
            year = int(year_match.group(0)) if year_match else None
            venue = cls._text(article.find(".//Journal/Title"))
            records.append(
                WorkRecord(
                    title=title,
                    abstract=abstract,
                    year=year,
                    doi=doi,
                    authors=tuple(authors),
                    venue=venue,
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
                    source_record_id=pmid,
                    external_ids={"pmid": pmid} if pmid else {},
                )
            )
        return records

    def search(self, query: str, *, limit: int) -> list[WorkRecord]:
        ids: list[str] = []
        page_size = min(500, max(1, limit))
        retstart = 0
        min_date = str(self.config.options.get("min_date", "2010-01-01")).replace(
            "-", "/"
        )
        max_date = str(self.config.options.get("max_date", "2026-12-31")).replace(
            "-", "/"
        )
        while len(ids) < limit:
            params: dict[str, Any] = {
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retstart": retstart,
                "retmax": min(page_size, limit - len(ids)),
                "datetype": "pdat",
                "mindate": min_date,
                "maxdate": max_date,
                "tool": "drug_shortage_eis_review",
                "email": self.contact_email,
            }
            if self.config.api_key:
                params["api_key"] = self.config.api_key
            data = self.get_json(f"{self.base_url}/esearch.fcgi", params=params)
            result = data.get("esearchresult") or {}
            batch = result.get("idlist") or []
            ids.extend(str(value) for value in batch)
            total = int(result.get("count") or 0)
            retstart += len(batch)
            if not batch or retstart >= total:
                break

        records: list[WorkRecord] = []
        for start in range(0, len(ids), 200):
            params = {
                "db": "pubmed",
                "id": ",".join(ids[start : start + 200]),
                "retmode": "xml",
                "tool": "drug_shortage_eis_review",
                "email": self.contact_email,
            }
            if self.config.api_key:
                params["api_key"] = self.config.api_key
            xml_text = self.get_text(f"{self.base_url}/efetch.fcgi", params=params)
            records.extend(
                self._parse_articles(
                    xml_text,
                    include_abstracts=self.config.include_abstracts,
                )
            )
        return records[:limit]
