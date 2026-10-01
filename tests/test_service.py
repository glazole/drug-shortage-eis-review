import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from evidence_pipeline.config import load_database_queries, load_study_config
from evidence_pipeline.service import create_run_id, describe_study, initialize_database


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STUDY_DIR = (
    PROJECT_ROOT
    / "studies"
    / "drug_shortage_eis"
    / "profiles"
    / "baseline"
)


class ServiceTests(unittest.TestCase):
    def test_describe_study_does_not_expose_api_keys(self) -> None:
        summary = describe_study(STUDY_DIR)

        self.assertEqual(summary["study_id"], "drug_shortage_eis")
        self.assertEqual(summary["profile_id"], "baseline")
        self.assertEqual(summary["search_language"], "en")
        self.assertTrue(summary["include_abstracts"])
        self.assertEqual(summary["query_variants"], 15)
        self.assertEqual(len(summary["research_questions"]["questions"]), 3)
        self.assertFalse(summary["sources"]["semantic_scholar"]["enabled"])
        self.assertNotIn("api_key", summary["sources"]["semantic_scholar"])

    def test_environment_overrides_effective_profile_without_editing_yaml(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "EVIDENCE_MIN_YEAR": "2018",
                "EVIDENCE_MAX_YEAR": "2025",
                "EVIDENCE_INCLUDE_ABSTRACTS": "false",
                "EVIDENCE_SOURCE_SEMANTIC_SCHOLAR_ENABLED": "true",
            },
            clear=False,
        ):
            summary = describe_study(STUDY_DIR)

        self.assertEqual(summary["date_range"], {"min_year": 2018, "max_year": 2025})
        self.assertFalse(summary["include_abstracts"])
        self.assertTrue(summary["sources"]["semantic_scholar"]["enabled"])
        self.assertEqual(
            set(summary["env_overrides"]),
            {
                "EVIDENCE_MIN_YEAR",
                "EVIDENCE_MAX_YEAR",
                "EVIDENCE_INCLUDE_ABSTRACTS",
                "EVIDENCE_SOURCE_SEMANTIC_SCHOLAR_ENABLED",
            },
        )

    def test_language_selects_only_matching_query_variants(self) -> None:
        study = load_study_config(STUDY_DIR)

        english = load_database_queries(STUDY_DIR, language=study.search_language)
        russian = load_database_queries(STUDY_DIR, language="ru")

        self.assertEqual(len(english), 15)
        self.assertEqual(russian, [])

    def test_disabling_required_source_makes_it_non_required(self) -> None:
        with patch.dict(
            "os.environ",
            {"EVIDENCE_SOURCE_PUBMED_ENABLED": "false"},
            clear=False,
        ):
            summary = describe_study(STUDY_DIR)

        self.assertFalse(summary["sources"]["pubmed"]["enabled"])
        self.assertFalse(summary["sources"]["pubmed"]["required"])

    def test_initialize_database_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "review.sqlite3"

            first = initialize_database(database)
            second = initialize_database(database)

        self.assertEqual(
            first,
            {
                "works": 0,
                "discoveries": 0,
                "source_runs": 0,
                "search_runs": 0,
            },
        )
        self.assertEqual(second, first)

    def test_generated_run_ids_are_search_prefixed(self) -> None:
        self.assertRegex(create_run_id(), r"^search_\d{8}T\d{12}Z$")


if __name__ == "__main__":
    unittest.main()
