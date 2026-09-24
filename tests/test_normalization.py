import unittest

from evidence_pipeline.normalization import candidate_work_id, normalize_doi, normalize_title


class NormalizationTests(unittest.TestCase):
    def test_doi_prefixes_are_removed(self) -> None:
        self.assertEqual(normalize_doi("https://doi.org/10.1000/ABC"), "10.1000/abc")
        self.assertEqual(normalize_doi("DOI: 10.1000/ABC"), "10.1000/abc")

    def test_title_normalization_is_punctuation_insensitive(self) -> None:
        self.assertEqual(normalize_title("Drug shortages: A systems view"), "drug shortages a systems view")

    def test_doi_work_id_is_stable(self) -> None:
        self.assertEqual(
            candidate_work_id("First title", 2020, "10.1000/ABC"),
            candidate_work_id("Changed title", 2021, "https://doi.org/10.1000/abc"),
        )


if __name__ == "__main__":
    unittest.main()
