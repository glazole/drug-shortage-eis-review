import unittest

from evidence_pipeline.config import SourceConfig
from evidence_pipeline.discovery import DiscoveryRunner
from evidence_pipeline.exceptions import SourceUnavailableError
from evidence_pipeline.models import SearchQuery, SourceStatus, WorkRecord
from evidence_pipeline.sources.base import SourceAdapter


class FakeAdapter(SourceAdapter):
    def __init__(self, config: SourceConfig, outcome: object) -> None:
        super().__init__(config, contact_email="test@example.org", sleep=lambda _: None)
        self.outcome = outcome
        self.calls = 0

    def search(self, query: str, *, limit: int) -> list[WorkRecord]:
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return list(self.outcome)[:limit]


class DiscoveryRunnerTests(unittest.TestCase):
    def test_disabled_source_is_not_called(self) -> None:
        config = SourceConfig(name="semantic_scholar", enabled=False)
        adapter = FakeAdapter(config, [])
        runner = DiscoveryRunner({config.name: adapter}, {config.name: config})

        records, reports = runner.search(
            run_id="run-1",
            queries=[SearchQuery("Q1", config.name, "drug shortage")],
            limit_per_query=10,
        )

        self.assertEqual(records, [])
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(reports[0].status, SourceStatus.DISABLED)

    def test_optional_unavailable_source_does_not_stop_other_sources(self) -> None:
        semantic_config = SourceConfig(name="semantic_scholar", required=False)
        pubmed_config = SourceConfig(name="pubmed", required=True)
        semantic = FakeAdapter(semantic_config, SourceUnavailableError("temporary outage"))
        pubmed = FakeAdapter(pubmed_config, [WorkRecord(title="Relevant paper")])
        runner = DiscoveryRunner(
            {"semantic_scholar": semantic, "pubmed": pubmed},
            {"semantic_scholar": semantic_config, "pubmed": pubmed_config},
        )

        records, reports = runner.search(
            run_id="run-2",
            queries=[
                SearchQuery("Q1", "semantic_scholar", "drug shortage"),
                SearchQuery("Q1", "pubmed", "drug shortage"),
            ],
            limit_per_query=10,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(
            [report.status for report in reports],
            [SourceStatus.UNAVAILABLE, SourceStatus.SUCCESS],
        )

    def test_required_unavailable_source_aborts(self) -> None:
        config = SourceConfig(name="pubmed", required=True)
        adapter = FakeAdapter(config, SourceUnavailableError("temporary outage"))
        runner = DiscoveryRunner({config.name: adapter}, {config.name: config})

        with self.assertRaises(SourceUnavailableError):
            runner.search(
                run_id="run-3",
                queries=[SearchQuery("Q1", config.name, "drug shortage")],
                limit_per_query=10,
            )

    def test_effective_date_range_and_abstract_setting_are_applied(self) -> None:
        config = SourceConfig(name="pubmed")
        adapter = FakeAdapter(
            config,
            [
                WorkRecord(title="Too old", year=2009, abstract="old"),
                WorkRecord(title="In range", year=2020, abstract="remove me"),
            ],
        )
        runner = DiscoveryRunner(
            {config.name: adapter},
            {config.name: config},
            min_year=2010,
            max_year=2026,
            include_abstracts=False,
        )

        records, reports = runner.search(
            run_id="run-filter",
            queries=[SearchQuery("Q1", config.name, "drug shortage")],
            limit_per_query=10,
        )

        self.assertEqual([item.record.title for item in records], ["In range"])
        self.assertIsNone(records[0].record.abstract)
        self.assertEqual(reports[0].retrieved_count, 1)


if __name__ == "__main__":
    unittest.main()
