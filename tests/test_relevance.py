import json
import tempfile
import unittest
from pathlib import Path

from evidence_pipeline.exceptions import ConfigurationError
from evidence_pipeline.models import DiscoveryEvent, DiscoveryMethod, DiscoveredWork, WorkRecord
from evidence_pipeline.relevance import evaluate, load_rules, screen_run
from evidence_pipeline.storage import SQLiteEvidenceStore

PROFILE = Path(__file__).resolve().parents[1] / 'studies/drug_shortage_eis/profiles/baseline'
S1 = 'S1_SHORTAGE_INFORMATION'
S2 = 'S2_SHORTAGE_ARCHITECTURE'
S3 = 'S3_PHARMA_IS_BRIDGE'


class RelevanceTests(unittest.TestCase):
    def setUp(self):
        self.rules = load_rules(PROFILE)

    def test_noise_and_word_boundaries(self):
        for title in ['Cloud data sharing', 'Drugstore supply chains information systems', 'Personal information online']:
            self.assertEqual(evaluate(title, 'An unrelated study.', S3, ['crossref'], self.rules)['decision'], 'exclude')

    def test_plural_hyphen_and_markup(self):
        result = evaluate('Drug shortages: <b>early-warning</b> monitoring', None, S1, ['openalex'], self.rules)
        self.assertEqual(result['decision'], 'include')
        self.assertIn('MISSING_ABSTRACT', result['reason_codes'])

    def test_data_fusion_shortage_candidate_advances_via_s1(self):
        title = "Integrative cross-supply-chain and clinical data fusion for proactive mitigation and management of pharmaceutical shortages"
        abstract = (
            "Mixing cross-supply-chain data with information from patients can support "
            "new ways to predict risks. Data fusion can dramatically improve how "
            "pharmaceutical shortages are managed by giving real-time access to supply "
            "chain operations. Stakeholders cooperate using shared information."
        )
        result = evaluate(title, abstract, S1, ['openalex'], self.rules)
        self.assertEqual(result['decision'], 'include')
        self.assertIn('data fusion', result['matched']['information'])
        self.assertEqual(evaluate(title, abstract, S3, ['openalex'], self.rules)['decision'], 'include')

    def test_essential_medicine_shortage_candidate_advances(self):
        title = "Global Shortages of Essential Medicines: Public Health Challenges and Policy Solutions"
        abstract = (
            "The global shortage of essential medicines is a public health challenge. "
            "Preventive strategies include early-warning systems. The framework integrates "
            "governance, manufacturing diversification and data transparency."
        )
        for query in [S1, S2]:
            result = evaluate(title, abstract, query, ['openalex'], self.rules)
            self.assertEqual(result['decision'], 'include')
            self.assertIn('shortages of essential medicines', result['matched']['shortage'])

    def test_reverse_shortage_form_still_requires_information(self):
        result = evaluate('Shortages of essential medicines', 'A study of manufacturing costs.', S1, ['crossref'], self.rules)
        self.assertEqual(result['decision'], 'exclude')
        self.assertEqual(result['reason_codes'], ['MISSING_INFORMATION_ANCHOR'])

    def test_data_fusion_still_requires_pharmaceutical_shortage(self):
        result = evaluate('Data fusion in photovoltaic monitoring', 'Shortages of essential equipment.', S1, ['crossref'], self.rules)
        self.assertEqual(result['decision'], 'exclude')
        self.assertEqual(result['reason_codes'], ['MISSING_SHORTAGE_ANCHOR'])

    def test_missing_abstract_does_not_exclude(self):
        result = evaluate('A pharmaceutical study', None, S1, ['crossref'], self.rules)
        self.assertEqual(result['decision'], 'review')

    def test_bridge_passes_and_requires_all_groups(self):
        self.assertEqual(evaluate('Pharmaceutical supply chains and information systems', 'Study.', S3, ['openalex'], self.rules)['decision'], 'include')
        self.assertEqual(evaluate('Pharmaceutical information systems', 'Study.', S3, ['openalex'], self.rules)['decision'], 'exclude')

    def test_native_boolean_sources_are_retained(self):
        self.assertEqual(evaluate('Shortages', None, S1, ['pubmed', 'crossref'], self.rules)['decision'], 'include')

    def test_dedup_aggregation_idempotency_manual_and_run_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteEvidenceStore(Path(tmp) / 'db.sqlite3')
            store.initialize()
            for run in ['r1', 'r2']:
                store.start_search_run(run_id=run, study_id='study', profile_id='baseline', effective_config={})
            record = WorkRecord(title='Drug shortages monitoring', abstract='A study.', doi='10.123/test')
            store.ingest([DiscoveredWork(record, DiscoveryEvent(run, 'crossref', DiscoveryMethod.DATABASE, query_id=q)) for run in ['r1', 'r2'] for q in [S1, S2]])
            with store.connect() as con:
                work_id = con.execute('SELECT work_id FROM works').fetchone()[0]
                con.execute("INSERT INTO screening_decisions(work_id,stage,decision,reviewer_id,decided_at) VALUES (?, 'title_abstract', 'exclude', 'oleg', 'now')", (work_id,))
            kwargs = dict(run_id='r1', study_id='study', profile_id='baseline', rules=self.rules)
            for _ in range(2):
                result = screen_run(store, **kwargs)
                self.assertEqual(result['include'], 1)
                self.assertEqual(result['query_assessments'], 2)
            with store.connect() as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM automatic_relevance').fetchone()[0], 2)
                self.assertEqual(con.execute('SELECT COUNT(*) FROM discoveries').fetchone()[0], 4)
                self.assertEqual(con.execute("SELECT decision FROM screening_decisions WHERE reviewer_id='oleg'").fetchone()[0], 'exclude')
                details = json.loads(con.execute('SELECT details_json FROM automatic_relevance LIMIT 1').fetchone()[0])
                self.assertIn('rules', details)
                self.assertIn('abstract', details['evidence'])
            with self.assertRaises(ConfigurationError):
                screen_run(store, **(kwargs | {'study_id': 'other'}))
