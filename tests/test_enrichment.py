import csv
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evidence_pipeline.corpus import export_corpus_csv, run_summary
from evidence_pipeline.enrichment import enrich_run
from evidence_pipeline.exceptions import ConfigurationError, HttpStatusError
from evidence_pipeline.models import DiscoveredWork, DiscoveryEvent, DiscoveryMethod, WorkRecord
from evidence_pipeline.storage import SQLiteEvidenceStore


class Lookup:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def doi_lookup_url(self, doi):
        return 'https://provider.example/doi/' + doi

    def lookup_doi(self, doi):
        self.calls.append(doi)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteEvidenceStore(Path(self.tmp.name) / 'review.sqlite3')
        self.store.initialize()
        for run in ['run1', 'run2']:
            self.store.start_search_run(run_id=run, study_id='study', profile_id='baseline', effective_config={})
        self.config = {'enabled': True, 'sources': ['scopus', 'openalex', 'crossref'], 'request_interval_seconds': 0}

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, title='Drug shortages', doi='10.1234/test', abstract=None, run='run1', source='scopus'):
        record = WorkRecord(title=title, doi=doi, abstract=abstract, year=2026)
        self.store.ingest([DiscoveredWork(record, DiscoveryEvent(run, source, DiscoveryMethod.DATABASE, query_id='S1_SHORTAGE_INFORMATION'))])

    def enrich(self, providers, **kwargs):
        return enrich_run(self.store, run_id='run1', registry=providers, config=self.config, sleep=lambda _: None, **kwargs)

    def test_forbidden_scopus_falls_back_exact_doi_and_keeps_discovery_source(self):
        self.add()
        scopus = Lookup([HttpStatusError(403, 'secret-token-must-not-be-saved')])
        oa = Lookup([WorkRecord(title='Same work', doi='https://doi.org/10.1234/TEST', abstract='<jats:p>Useful abstract.</jats:p>')])
        result = self.enrich({'scopus': scopus, 'openalex': oa})
        self.assertEqual(result['enriched'], 1)
        self.assertEqual(result['missing_after'], 0)
        with self.store.connect() as con:
            self.assertEqual(con.execute('SELECT abstract FROM works').fetchone()[0], 'Useful abstract.')
            self.assertEqual(con.execute('SELECT source_name FROM discoveries').fetchone()[0], 'scopus')
            prov = con.execute('SELECT * FROM work_abstracts').fetchone()
            self.assertEqual(prov['source_name'], 'openalex')
            self.assertEqual(prov['method'], 'doi_lookup')
            self.assertEqual(prov['source_url'], 'https://provider.example/doi/10.1234/test')
            attempts = con.execute('SELECT * FROM abstract_lookup_attempts').fetchall()
            self.assertEqual([r['status'] for r in attempts], ['failed', 'found'])
            self.assertNotIn('secret-token', str([dict(r) for r in attempts]))

    def test_mismatched_doi_is_never_accepted(self):
        self.add()
        oa = Lookup([WorkRecord(title='Wrong paper', doi='10.1234/wrong', abstract='Incorrect abstract')])
        crossref = Lookup([WorkRecord(title='Correct paper', doi='10.1234/test', abstract='Correct abstract')])
        self.assertEqual(self.enrich({'openalex': oa, 'crossref': crossref})['enriched'], 1)
        with self.store.connect() as con:
            self.assertEqual(con.execute('SELECT abstract FROM works').fetchone()[0], 'Correct abstract')
            self.assertEqual(con.execute("SELECT COUNT(*) FROM abstract_lookup_attempts WHERE status='doi_mismatch'").fetchone()[0], 1)

    def test_existing_abstract_is_not_overwritten_or_requested(self):
        self.add(abstract='Existing trusted text', source='pubmed')
        source = Lookup([])
        self.assertEqual(self.enrich({'openalex': source})['attempted_works'], 0)
        self.assertEqual(source.calls, [])

    def test_deduplicated_queries_only_trigger_one_lookup(self):
        self.add()
        self.add(source='crossref')
        source = Lookup([WorkRecord(title='Same work', doi='10.1234/test', abstract='New abstract')])
        result = self.enrich({'openalex': source})
        self.assertEqual(result['attempted_works'], 1)
        self.assertEqual(len(source.calls), 1)
        self.assertEqual(self.store.summary()['discoveries'], 2)

    def test_repeated_enrichment_skips_now_complete_records(self):
        self.add()
        source = Lookup([WorkRecord(title='Same', doi='10.1234/test', abstract='New abstract')])
        self.enrich({'openalex': source})
        result = self.enrich({'openalex': source})
        self.assertEqual(result['attempted_works'], 0)
        self.assertEqual(len(source.calls), 1)

    def test_403_circuit_avoids_repeated_requests_but_preserves_audit(self):
        self.add(doi='10.1234/a')
        self.add(title='Another study', doi='10.1234/b')
        scopus = Lookup([HttpStatusError(403, 'forbidden')])
        oa = Lookup([None, None])
        result = self.enrich({'scopus': scopus, 'openalex': oa})
        self.assertEqual(len(scopus.calls), 1)
        self.assertEqual(result['provider_statuses']['scopus'], {'failed': 1, 'skipped_unavailable': 1})
        self.assertEqual(result['unresolved'], 2)

    def test_missing_doi_is_counted_and_run_scoping_is_respected(self):
        self.add(doi=None)
        self.add(title='Other run record', doi='10.1234/other', run='run2')
        source = Lookup([])
        result = self.enrich({'openalex': source})
        self.assertEqual(result['without_doi'], 1)
        self.assertEqual(result['attempted_works'], 1)
        self.assertEqual(source.calls, [])

    def test_placeholder_and_not_found_do_not_fill_abstract(self):
        self.add()
        oa = Lookup([WorkRecord(title='Same', doi='10.1234/test', abstract='No abstract available.')])
        crossref = Lookup([HttpStatusError(404, 'not found')])
        result = self.enrich({'openalex': oa, 'crossref': crossref})
        self.assertEqual(result['enriched'], 0)
        self.assertEqual(result['unresolved'], 1)
        self.assertEqual(result['provider_statuses']['crossref']['not_found'], 1)

    def test_max_works_and_source_filter_are_explicit(self):
        self.add(doi='10.1234/a')
        self.add(title='Second', doi='10.1234/b')
        self.add(title='PubMed', doi='10.1234/c', source='pubmed')
        result = self.enrich({}, max_works=1, discovery_source='scopus')
        self.assertEqual(result['missing_before'], 2)
        self.assertEqual(result['attempted_works'], 1)
        self.assertEqual(result['missing_after'], 2)

    def test_unknown_run_rejected_before_lookups(self):
        with self.assertRaises(ConfigurationError):
            enrich_run(self.store, run_id='unknown', registry={}, config=self.config)

    def test_native_provenance_and_selected_longer_abstract(self):
        self.add(abstract='Short', source='crossref')
        self.add(abstract='Longer authoritative abstract.', source='pubmed')
        data = list(csv.DictReader(io.StringIO(export_corpus_csv(self.store, 'run1').lstrip('\ufeff'))))
        self.assertEqual(data[0]['abstract_source'], 'pubmed')
        self.assertEqual(data[0]['abstract_method'], 'search')
        with self.store.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM work_abstracts').fetchone()[0], 2)

    def test_export_does_not_hide_exclusions_and_keeps_manual_columns(self):
        self.add(title='=HYPERLINK("malicious")')
        with self.store.connect() as con:
            work_id = con.execute('SELECT work_id FROM works').fetchone()[0]
            con.execute("INSERT INTO screening_decisions(work_id,stage,decision,reviewer_id,decided_at) VALUES (?, 'title_abstract', 'exclude', 'oleg', 'now')", (work_id,))
        text = export_corpus_csv(self.store, 'run1')
        data = list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['manual_decision'], 'exclude')
        self.assertEqual(data[0]['reviewer'], 'oleg')
        self.assertTrue(data[0]['title'].startswith("'="))
        self.assertEqual(run_summary(self.store, 'run1')['without_abstract'], 1)

    def test_legacy_source_is_not_guessed_and_migration_is_idempotent(self):
        self.add(abstract='Old abstract')
        with self.store.connect() as con:
            con.execute('DELETE FROM work_abstracts')
        for _ in range(2):
            self.store.initialize()
        data = list(csv.DictReader(io.StringIO(export_corpus_csv(self.store, 'run1').lstrip('\ufeff'))))
        self.assertEqual(data[0]['abstract_source'], 'legacy_unknown')

class LegacyMigrationTests(unittest.TestCase):
    def test_upgrade_preserves_old_source_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'old.sqlite3'
            with sqlite3.connect(path) as con:
                con.execute('CREATE TABLE source_runs (source_run_id INTEGER PRIMARY KEY, run_id TEXT, source_name TEXT, status TEXT, method TEXT, query_id TEXT, retrieved_count INTEGER, message TEXT, started_at TEXT, completed_at TEXT)')
                con.execute("INSERT INTO source_runs VALUES (1,'old','scopus','success','database','S1',20,NULL,'start','end')")
            store = SQLiteEvidenceStore(path)
            store.initialize()
            store.initialize()
            with store.connect() as con:
                row = con.execute('SELECT * FROM source_runs').fetchone()
                self.assertEqual(row['retrieved_count'], 20)
                self.assertIsNone(row['total_results'])
                self.assertEqual(row['possibly_truncated'], 0)
