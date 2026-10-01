import tempfile
import unittest
from pathlib import Path

from evidence_pipeline.service import create_run_id, describe_study, initialize_database


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = PROJECT_ROOT / "studies" / "drug_shortage_eis"


class ServiceTests(unittest.TestCase):
    def test_describe_study_does_not_expose_api_keys(self) -> None:
        summary = describe_study(STUDY_DIR)

        self.assertEqual(summary["study_id"], "drug_shortage_eis")
        self.assertEqual(summary["query_variants"], 15)
        self.assertFalse(summary["sources"]["semantic_scholar"]["enabled"])
        self.assertNotIn("api_key", summary["sources"]["semantic_scholar"])

    def test_initialize_database_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "review.sqlite3"

            first = initialize_database(database)
            second = initialize_database(database)

        self.assertEqual(first, {"works": 0, "discoveries": 0, "source_runs": 0})
        self.assertEqual(second, first)

    def test_generated_run_ids_are_search_prefixed(self) -> None:
        self.assertRegex(create_run_id(), r"^search_\d{8}T\d{12}Z$")


if __name__ == "__main__":
    unittest.main()
