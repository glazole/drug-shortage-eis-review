import sqlite3
import tempfile
import unittest
import json
from pathlib import Path

from evidence_pipeline.models import (
    DiscoveredWork,
    DiscoveryEvent,
    DiscoveryMethod,
    WorkRecord,
)
from evidence_pipeline.storage import SQLiteEvidenceStore


class SQLiteEvidenceStoreTests(unittest.TestCase):
    def test_duplicate_work_preserves_two_discovery_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEvidenceStore(Path(temp_dir) / "review.sqlite3")
            store.initialize()
            first = DiscoveredWork(
                record=WorkRecord(
                    title="Drug shortages: a systems view",
                    doi="https://doi.org/10.1000/ABC",
                    abstract="Short abstract.",
                    year=2022,
                ),
                event=DiscoveryEvent(
                    run_id="run-1",
                    source_name="pubmed",
                    method=DiscoveryMethod.DATABASE,
                    query_id="Q1",
                ),
            )
            second = DiscoveredWork(
                record=WorkRecord(
                    title="Drug shortages: A systems view",
                    doi="10.1000/abc",
                    abstract="A substantially longer and more informative abstract.",
                    year=2022,
                ),
                event=DiscoveryEvent(
                    run_id="run-1",
                    source_name="openalex",
                    method=DiscoveryMethod.FORWARD,
                    parent_work_id="seed-1",
                    iteration=1,
                ),
            )

            store.ingest([first, second])
            self.assertEqual(store.summary()["works"], 1)
            self.assertEqual(store.summary()["discoveries"], 2)
            with store.connect() as connection:
                abstract = connection.execute("SELECT abstract FROM works").fetchone()[0]
                self.assertIn("substantially longer", abstract)

    def test_search_run_preserves_effective_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteEvidenceStore(Path(temp_dir) / "review.sqlite3")
            store.initialize()
            config = {
                "search_language": "en",
                "include_abstracts": False,
                "env_overrides": ["EVIDENCE_INCLUDE_ABSTRACTS"],
            }

            store.start_search_run(
                run_id="run-config",
                study_id="drug_shortage_eis",
                profile_id="baseline",
                effective_config=config,
            )
            store.complete_search_run("run-config", status="completed")

            with store.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM search_runs WHERE run_id = ?",
                    ("run-config",),
                ).fetchone()

        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["study_id"], "drug_shortage_eis")
        self.assertEqual(row["profile_id"], "baseline")
        self.assertEqual(json.loads(row["effective_config_json"]), config)
        self.assertIsNotNone(row["completed_at"])


if __name__ == "__main__":
    unittest.main()
