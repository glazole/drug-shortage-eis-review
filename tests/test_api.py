import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from evidence_pipeline.api import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "EVIDENCE_STUDIES_ROOT": str(PROJECT_ROOT / "studies"),
                "EVIDENCE_DATABASE_PATH": str(
                    Path(self.temporary_directory.name) / "review.sqlite3"
                ),
                "EVIDENCE_DEFAULT_STUDY_ID": "drug_shortage_eis",
                "EVIDENCE_DEFAULT_PROFILE_ID": "baseline",
            },
        )
        self.environment.start()
        self.client_context = TestClient(create_app())
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.environment.stop()
        self.temporary_directory.cleanup()

    def test_health_initializes_empty_ledger(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["ledger"]["works"], 0)

    def test_study_endpoint_reports_disabled_semantic_scholar(self) -> None:
        response = self.client.get("/v1/studies/drug_shortage_eis")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["query_variants"], 15)
        self.assertEqual(body["profile_id"], "baseline")
        self.assertEqual(body["search_language"], "en")
        self.assertFalse(body["sources"]["semantic_scholar"]["enabled"])

    def test_studies_endpoint_lists_saved_profiles(self) -> None:
        response = self.client.get("/v1/studies")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["default_profile_id"], "baseline")
        self.assertIn(
            {"study_id": "drug_shortage_eis", "profiles": ["baseline"]},
            response.json()["studies"],
        )

    def test_profile_endpoint_returns_research_questions(self) -> None:
        response = self.client.get(
            "/v1/studies/drug_shortage_eis/profiles/baseline"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["research_questions"]["questions"]), 3)

    def test_search_assesses_and_rescreens_existing_run(self) -> None:
        from evidence_pipeline.models import DiscoveryEvent, DiscoveryMethod, DiscoveredWork, WorkRecord
        records = [DiscoveredWork(
            WorkRecord(title="Drug shortages monitoring", abstract="A study.", year=2026),
            DiscoveryEvent("pilot", "crossref", DiscoveryMethod.DATABASE,
                           query_id="S1_SHORTAGE_INFORMATION"),
        )]
        with patch("evidence_pipeline.service.DiscoveryRunner.search", return_value=(records, [])):
            response = self.client.post("/v1/search", json={"run_id": "pilot", "limit_per_query": 20})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["automatic_relevance"]["include"], 1)
        response = self.client.post("/v1/screening/automatic", json={"run_id": "pilot"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["works_assessed"], 1)
        self.assertEqual(self.client.get("/v1/ledger/summary").json()["discoveries"], 1)
        self.assertEqual(self.client.post("/v1/screening/automatic", json={"run_id": "missing"}).status_code, 422)

    def test_enrichment_export_and_summary_are_run_scoped(self):
        import csv
        import io
        from evidence_pipeline.models import DiscoveryEvent, DiscoveryMethod, DiscoveredWork, WorkRecord
        class Provider:
            def doi_lookup_url(self, doi):
                return "https://provider.example/" + doi
            def lookup_doi(self, doi):
                return WorkRecord(title="Drug shortages", doi=doi, abstract="Monitoring drug shortages.")
        records = [DiscoveredWork(
            WorkRecord(title="Drug shortages", doi="10.1234/test", year=2026),
            DiscoveryEvent("corpus", "scopus", DiscoveryMethod.DATABASE, query_id="S1_SHORTAGE_INFORMATION"))]
        config = {"enabled": True, "sources": ["openalex"], "request_interval_seconds": 0}
        with patch("evidence_pipeline.service.DiscoveryRunner.search", return_value=(records, [])), \
             patch("evidence_pipeline.service.build_source_registry", return_value={"openalex": Provider()}), \
             patch("evidence_pipeline.service.load_enrichment_config", return_value=config):
            response = self.client.post("/v1/search", json={"run_id": "corpus"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["abstract_enrichment"]["enriched"], 1)
            repeat = self.client.post("/v1/enrichment/abstracts", json={"run_id": "corpus"})
            self.assertEqual(repeat.status_code, 200, repeat.text)
            self.assertEqual(repeat.json()["attempted_works"], 0)
        summary = self.client.get("/v1/runs/corpus/summary")
        self.assertEqual(summary.status_code, 200, summary.text)
        response = self.client.get("/v1/runs/corpus/corpus.csv")
        self.assertEqual(response.status_code, 200, response.text)
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["abstract_source"], "openalex")
        self.assertEqual(rows[0]["discovery_sources"], "scopus")
        self.assertEqual(rows[0]["manual_decision"], "")
        self.assertEqual(self.client.get("/v1/runs/missing/corpus.csv").status_code, 404)
        self.assertEqual(self.client.get("/v1/runs/missing/summary").status_code, 404)

    def test_unknown_study_returns_not_found(self) -> None:
        response = self.client.get("/v1/studies/missing")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
