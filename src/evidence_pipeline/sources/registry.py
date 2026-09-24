"""Build configured adapter instances without hard-wiring them into the runner."""

from __future__ import annotations

from ..config import StudyConfig
from ..http import HttpClient
from .base import SourceAdapter
from .crossref import CrossrefAdapter
from .elsevier import ScienceDirectAdapter, ScopusAdapter
from .openalex import OpenAlexAdapter
from .pubmed import PubMedAdapter
from .semantic_scholar import SemanticScholarAdapter


ADAPTER_TYPES: dict[str, type[SourceAdapter]] = {
    "openalex": OpenAlexAdapter,
    "crossref": CrossrefAdapter,
    "pubmed": PubMedAdapter,
    "scopus": ScopusAdapter,
    "sciencedirect": ScienceDirectAdapter,
    "semantic_scholar": SemanticScholarAdapter,
}


def build_source_registry(
    study: StudyConfig,
    *,
    http_client: HttpClient | None = None,
) -> dict[str, SourceAdapter]:
    registry: dict[str, SourceAdapter] = {}
    for name, source_config in study.sources.items():
        adapter_type = ADAPTER_TYPES.get(name)
        if adapter_type is None:
            continue
        registry[name] = adapter_type(
            source_config,
            contact_email=study.contact_email,
            http_client=http_client,
        )
    return registry
