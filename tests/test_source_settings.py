import unittest
from typing import Any

from evidence_pipeline.config import SourceConfig
from evidence_pipeline.sources.pubmed import PubMedAdapter
from evidence_pipeline.sources.semantic_scholar import SemanticScholarAdapter


class RecordingHttpClient:
    def __init__(self) -> None:
        self.json_params: list[dict[str, Any]] = []

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        self.json_params.append(params or {})
        return {"esearchresult": {"idlist": [], "count": "0"}}

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> str:
        raise AssertionError("No XML fetch is expected when PubMed returns no IDs")


class SourceSettingsTests(unittest.TestCase):
    def test_pubmed_receives_effective_date_range(self) -> None:
        http = RecordingHttpClient()
        adapter = PubMedAdapter(
            SourceConfig(
                name="pubmed",
                options={
                    "min_date": "2015-01-01",
                    "max_date": "2025-12-31",
                },
            ),
            contact_email="test@example.org",
            http_client=http,
        )

        adapter.search("drug shortage", limit=10)

        self.assertEqual(http.json_params[0]["datetype"], "pdat")
        self.assertEqual(http.json_params[0]["mindate"], "2015/01/01")
        self.assertEqual(http.json_params[0]["maxdate"], "2025/12/31")

    def test_semantic_scholar_omits_abstract_field_when_disabled(self) -> None:
        adapter = SemanticScholarAdapter(
            SourceConfig(name="semantic_scholar", include_abstracts=False),
            contact_email="test@example.org",
        )

        self.assertNotIn("abstract", adapter.paper_fields.split(","))


if __name__ == "__main__":
    unittest.main()
