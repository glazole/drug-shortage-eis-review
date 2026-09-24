import unittest

from evidence_pipeline.config import SourceConfig
from evidence_pipeline.exceptions import HttpStatusError, SourceRequestError, SourceUnavailableError
from evidence_pipeline.models import WorkRecord
from evidence_pipeline.sources.base import SourceAdapter


class RetryProbeAdapter(SourceAdapter):
    def search(self, query: str, *, limit: int) -> list[WorkRecord]:
        return []


class SourceRetryTests(unittest.TestCase):
    def test_transient_http_errors_are_retried_then_marked_unavailable(self) -> None:
        waits: list[float] = []
        calls = 0

        def operation() -> None:
            nonlocal calls
            calls += 1
            raise HttpStatusError(429, "rate limited")

        adapter = RetryProbeAdapter(
            SourceConfig(
                name="semantic_scholar",
                max_retries=2,
                backoff_seconds=0.25,
            ),
            contact_email="test@example.org",
            sleep=waits.append,
        )

        with self.assertRaises(SourceUnavailableError):
            adapter._with_retries(operation)

        self.assertEqual(calls, 3)
        self.assertEqual(waits, [0.25, 0.5])

    def test_permanent_http_error_is_not_retried(self) -> None:
        calls = 0

        def operation() -> None:
            nonlocal calls
            calls += 1
            raise HttpStatusError(400, "invalid query")

        adapter = RetryProbeAdapter(
            SourceConfig(name="semantic_scholar", max_retries=3),
            contact_email="test@example.org",
            sleep=lambda _: None,
        )

        with self.assertRaises(SourceRequestError):
            adapter._with_retries(operation)

        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
