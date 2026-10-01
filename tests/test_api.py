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

    def test_unknown_study_returns_not_found(self) -> None:
        response = self.client.get("/v1/studies/missing")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
